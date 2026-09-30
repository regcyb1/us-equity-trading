"""Rate-limited, retrying HTTP client that writes the raw archive before returning.

Every HTTP call in the project goes through HttpClient:
- per-source rate limiting (SourcePolicy.rate_per_sec; SEC capped at 5 req/s),
- retry with exponential backoff on 429/5xx and transport errors (honours Retry-After),
- a timeout on every call, TLS verification always on, https only,
- User-Agent from the HTTP_USER_AGENT env var unless passed explicitly,
- the final response is archived (secrets stripped from url, params and headers)
  before it is returned or raised.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config.secrets import MASK, get_setting, redact
from ingest.raw_archive import write_raw

DEFAULT_USER_AGENT = "us-equity-trading/0.0.1"
SEC_MAX_RATE = 5.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

_SENSITIVE_WORDS = ("key", "token", "secret", "password", "auth", "signature", "cookie")
_SENSITIVE_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie",
                                "set-cookie", "user-agent"})


class TransportError(Exception):
    """Connection failure or timeout raised by a Transport (retryable)."""


class HttpError(Exception):
    """Final non-2xx response or retries exhausted. Message has no secrets."""

    def __init__(self, source: str, status: int | None, message: str):
        self.source = source
        self.status = status
        super().__init__(f"[{source}] {message}")


@dataclass(frozen=True)
class Response:
    status_code: int
    headers: dict[str, str]
    content: bytes
    archive_path: Path | None = None


class Transport(Protocol):
    def send(self, method: str, url: str, *, params: dict[str, Any], headers: dict[str, str],
             timeout: tuple[float, float], verify: bool) -> Response: ...


class RequestsTransport:
    """Default transport backed by requests.Session."""

    def __init__(self) -> None:
        import requests

        self._requests = requests
        self._session = requests.Session()
        self._session.trust_env = False  # no .netrc / env proxies injecting credentials

    def send(self, method, url, *, params, headers, timeout, verify):
        try:
            r = self._session.request(method, url, params=params, headers=headers,
                                      timeout=timeout, verify=verify, allow_redirects=True)
        except (self._requests.ConnectionError, self._requests.Timeout) as e:
            raise TransportError(type(e).__name__) from None
        return Response(r.status_code, dict(r.headers), r.content)


@dataclass(frozen=True)
class SourcePolicy:
    rate_per_sec: float = 1.0
    max_retries: int = 4
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0

    def __post_init__(self) -> None:
        if self.rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("timeouts must be > 0")


DEFAULT_POLICIES: dict[str, SourcePolicy] = {
    "sec_edgar": SourcePolicy(rate_per_sec=SEC_MAX_RATE),
}


class RateLimiter:
    """Minimum spacing between calls, per source. Thread-safe."""

    def __init__(self, rate_per_sec: float, clock: Callable[[], float],
                 sleep: Callable[[float], None]):
        self._interval = 1.0 / rate_per_sec
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next - now
            if wait > 0:
                self._sleep(wait)
                now += wait
            self._next = now + self._interval


def _is_sensitive(name: str, extra: frozenset[str]) -> bool:
    low = name.lower()
    return low in extra or any(w in low for w in _SENSITIVE_WORDS)


def strip_params(params: dict[str, Any] | None, extra: frozenset[str] = frozenset()) -> dict[str, Any]:
    return {k: (MASK if _is_sensitive(k, extra) else redact(str(v)))
            for k, v in (params or {}).items()}


def strip_url(url: str, extra: frozenset[str] = frozenset()) -> str:
    parts = urlsplit(url)
    query = [(k, MASK if _is_sensitive(k, extra) else v)
             for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return redact(urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), "")))


def strip_headers(headers: dict[str, str] | None, extra: frozenset[str] = frozenset()) -> dict[str, str]:
    out = {}
    for k, v in (headers or {}).items():
        low = k.lower()
        out[k] = MASK if (low in _SENSITIVE_HEADERS or _is_sensitive(k, extra)) else redact(str(v))
    return out


@dataclass
class HttpClient:
    archive_root: Path | str
    transport: Transport | None = None
    user_agent: str | None = None
    policies: dict[str, SourcePolicy] = field(default_factory=lambda: dict(DEFAULT_POLICIES))
    default_policy: SourcePolicy = field(default_factory=SourcePolicy)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = RequestsTransport()
        if self.user_agent is None:
            self.user_agent = get_setting("HTTP_USER_AGENT", DEFAULT_USER_AGENT)
        sec = self.policies.get("sec_edgar")
        if sec is not None and sec.rate_per_sec > SEC_MAX_RATE:
            raise ValueError("sec_edgar rate must be <= 5 requests/s")
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    def policy(self, source: str) -> SourcePolicy:
        return self.policies.get(source, self.default_policy)

    def _limiter(self, source: str) -> RateLimiter:
        with self._lock:
            if source not in self._limiters:
                self._limiters[source] = RateLimiter(self.policy(source).rate_per_sec,
                                                     self.clock, self.sleep)
            return self._limiters[source]

    def _backoff(self, pol: SourcePolicy, attempt: int, resp: Response | None) -> float:
        delay = pol.backoff_base * (2 ** attempt)
        if resp is not None:
            ra = {k.lower(): v for k, v in resp.headers.items()}.get("retry-after")
            if ra is not None:
                try:
                    delay = max(delay, float(ra))
                except ValueError:
                    pass
        return min(delay, pol.backoff_max)

    def get(self, source: str, url: str, *, params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
            secret_names: tuple[str, ...] = ()) -> Response:
        """GET url for source. secret_names: extra param/header names to strip."""
        return self.request("GET", source, url, params=params, headers=headers,
                            secret_names=secret_names)

    def request(self, method: str, source: str, url: str, *,
                params: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None,
                secret_names: tuple[str, ...] = ()) -> Response:
        if urlsplit(url).scheme != "https":
            raise ValueError("only https URLs are allowed")
        extra = frozenset(n.lower() for n in secret_names)
        pol = self.policy(source)
        send_headers = {"User-Agent": self.user_agent, **(headers or {})}
        params = dict(params or {})
        meta = {
            "method": method.upper(),
            "url": strip_url(url, extra),
            "params": strip_params(params, extra),
            "headers": strip_headers(send_headers, extra),
        }

        limiter = self._limiter(source)
        resp: Response | None = None
        last_error: str | None = None
        attempts = 0
        for attempt in range(pol.max_retries + 1):
            attempts = attempt + 1
            limiter.acquire()
            try:
                resp = self.transport.send(method.upper(), url, params=params,
                                           headers=send_headers,
                                           timeout=(pol.connect_timeout, pol.read_timeout),
                                           verify=True)
                last_error = None
            except TransportError as e:
                resp, last_error = None, str(e)
            retryable = resp is None or resp.status_code in RETRY_STATUSES
            if not retryable or attempt == pol.max_retries:
                break
            self.sleep(self._backoff(pol, attempt, resp))

        if resp is None:
            raise HttpError(source, None, f"transport failed after {attempts} attempts: {last_error}")

        meta["attempts"] = attempts
        path = write_raw(self.archive_root, source, self.now(), meta, resp.status_code,
                         strip_headers(resp.headers, extra), resp.content)
        resp = Response(resp.status_code, resp.headers, resp.content, path)
        if not 200 <= resp.status_code < 300:
            raise HttpError(source, resp.status_code,
                            f"HTTP {resp.status_code} after {attempts} attempts")
        return resp
