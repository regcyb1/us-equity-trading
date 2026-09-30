import gzip
import secrets as pysecrets
from datetime import datetime, timezone

import pytest

from config import secrets as sec
from ingest.http import (HttpClient, HttpError, Response, SourcePolicy, TransportError)
from ingest.raw_archive import read_raw, write_raw

FIXED_NOW = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeTransport:
    """Returns scripted responses (or raises TransportError) and records calls."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def send(self, method, url, *, params, headers, timeout, verify):
        self.calls.append(dict(method=method, url=url, params=params, headers=headers,
                               timeout=timeout, verify=verify))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(body=b'{"rows": 1}', status=200, headers=None):
    return Response(status, headers or {"Content-Type": "application/json"}, body)


def make_client(tmp_path, script, **kw):
    fc = FakeClock()
    t = FakeTransport(script)
    kw.setdefault("default_policy", SourcePolicy(rate_per_sec=2.0, max_retries=3,
                                                 backoff_base=1.0, backoff_max=8.0))
    c = HttpClient(archive_root=tmp_path, transport=t, user_agent="ua-test",
                   clock=fc.clock, sleep=fc.sleep, now=lambda: FIXED_NOW, **kw)
    return c, t, fc


@pytest.fixture(autouse=True)
def _clean_registry():
    sec._clear_registry_for_tests()
    yield
    sec._clear_registry_for_tests()


def test_success_archives_before_return(tmp_path):
    c, t, _ = make_client(tmp_path, [ok()])
    r = c.get("massive", "https://api.example.test/v2/grouped", params={"date": "2026-09-30"})
    assert r.status_code == 200
    assert r.archive_path.exists()
    assert r.archive_path.parent == tmp_path / "raw" / "massive" / "2026" / "09" / "30"
    env = read_raw(r.archive_path)
    assert env["body"] == b'{"rows": 1}'
    assert env["request"]["params"] == {"date": "2026-09-30"}
    assert env["status"] == 200


def test_tls_timeout_and_user_agent_always_sent(tmp_path):
    c, t, _ = make_client(tmp_path, [ok()])
    c.get("massive", "https://api.example.test/x")
    call = t.calls[0]
    assert call["verify"] is True
    assert call["timeout"] == (10.0, 30.0)
    assert call["headers"]["User-Agent"] == "ua-test"


def test_user_agent_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_USER_AGENT", "research-bot contact@example.test")
    c = HttpClient(archive_root=tmp_path, transport=FakeTransport([]))
    assert c.user_agent == "research-bot contact@example.test"


def test_http_url_rejected(tmp_path):
    c, t, _ = make_client(tmp_path, [ok()])
    with pytest.raises(ValueError):
        c.get("massive", "http://api.example.test/x")
    assert t.calls == []


def test_secrets_stripped_from_archive(tmp_path, monkeypatch):
    key = "fake-" + pysecrets.token_hex(16)
    monkeypatch.setenv("TEST_API_KEY", key)
    s = sec.get_secret("TEST_API_KEY")
    c, t, _ = make_client(tmp_path, [ok(headers={"Set-Cookie": "sid=" + key})])
    r = c.get("massive", f"https://u:{key}@api.example.test/x?apiKey={key}&d=1",
              params={"apiKey": s.reveal(), "q": "AAPL", "custom": s.reveal()},
              headers={"Authorization": "Bearer " + key, "X-Plain": "hello"},
              secret_names=("custom",))
    # the real key went out on the wire
    assert t.calls[0]["params"]["apiKey"] == key
    raw = gzip.decompress(r.archive_path.read_bytes()).decode()
    assert key not in raw
    env = read_raw(r.archive_path)
    assert env["request"]["params"] == {"apiKey": "***", "q": "AAPL", "custom": "***"}
    assert env["request"]["headers"]["Authorization"] == "***"
    assert env["request"]["headers"]["User-Agent"] == "***"
    assert env["request"]["headers"]["X-Plain"] == "hello"
    assert "u:" not in env["request"]["url"] and "d=1" in env["request"]["url"]


def test_retry_with_exponential_backoff_then_success(tmp_path):
    c, t, fc = make_client(tmp_path, [ok(status=503), TransportError("Timeout"),
                                      ok(status=500), ok()])
    r = c.get("massive", "https://api.example.test/x")
    assert r.status_code == 200
    assert len(t.calls) == 4
    backoffs = [s for s in fc.sleeps if s in (1.0, 2.0, 4.0)]
    assert backoffs[:3] == [1.0, 2.0, 4.0]
    assert read_raw(r.archive_path)["request"]["attempts"] == 4


def test_retry_after_header_honoured_and_capped(tmp_path):
    c, t, fc = make_client(tmp_path, [ok(status=429, headers={"Retry-After": "5"}),
                                      ok(status=429, headers={"Retry-After": "999"}), ok()])
    c.get("massive", "https://api.example.test/x")
    assert 5.0 in fc.sleeps
    assert 8.0 in fc.sleeps  # capped at backoff_max
    assert 999.0 not in fc.sleeps


def test_retries_exhausted_raises_and_archives_last(tmp_path):
    c, t, _ = make_client(tmp_path, [ok(status=503)] * 4)
    with pytest.raises(HttpError) as e:
        c.get("massive", "https://api.example.test/x")
    assert e.value.status == 503
    assert len(t.calls) == 4
    assert len(list((tmp_path / "raw").rglob("*.json.gz"))) == 1


def test_non_retryable_4xx_no_retry_but_archived(tmp_path):
    c, t, _ = make_client(tmp_path, [ok(status=404, body=b"nope")])
    with pytest.raises(HttpError):
        c.get("massive", "https://api.example.test/x")
    assert len(t.calls) == 1
    assert len(list((tmp_path / "raw").rglob("*.json.gz"))) == 1


def test_transport_errors_exhausted(tmp_path):
    c, t, _ = make_client(tmp_path, [TransportError("ConnectionError")] * 4)
    with pytest.raises(HttpError) as e:
        c.get("massive", "https://api.example.test/x")
    assert e.value.status is None
    assert not (tmp_path / "raw").exists()


def test_rate_limit_per_source(tmp_path):
    c, t, fc = make_client(tmp_path, [ok(b"1"), ok(b"2"), ok(b"3"), ok(b"4")])
    c.get("massive", "https://api.example.test/a")
    c.get("massive", "https://api.example.test/b")
    c.get("massive", "https://api.example.test/c")
    assert fc.sleeps == [0.5, 0.5]  # 2 req/s
    c.get("fred", "https://api.example.test/d")  # separate limiter, no wait
    assert fc.sleeps == [0.5, 0.5]


def test_sec_rate_cap_enforced(tmp_path):
    with pytest.raises(ValueError):
        HttpClient(archive_root=tmp_path, transport=FakeTransport([]), user_agent="x",
                   policies={"sec_edgar": SourcePolicy(rate_per_sec=10)})
    c = HttpClient(archive_root=tmp_path, transport=FakeTransport([]), user_agent="x")
    assert c.policy("sec_edgar").rate_per_sec <= 5


def test_archive_never_overwrites(tmp_path):
    meta = {"method": "GET", "url": "https://a.test/x", "params": {}}
    p1 = write_raw(tmp_path, "s", FIXED_NOW, meta, 200, {}, b"one")
    p_same = write_raw(tmp_path, "s", FIXED_NOW, meta, 200, {}, b"one")
    p2 = write_raw(tmp_path, "s", FIXED_NOW, meta, 200, {}, b"two")
    assert p1 == p_same
    assert p2 != p1
    assert read_raw(p1)["body"] == b"one"
    assert read_raw(p2)["body"] == b"two"


def test_archive_rejects_bad_source_and_naive_time(tmp_path):
    meta = {"method": "GET", "url": "https://a.test/x", "params": {}}
    with pytest.raises(ValueError):
        write_raw(tmp_path, "../x", FIXED_NOW, meta, 200, {}, b"")
    with pytest.raises(ValueError):
        write_raw(tmp_path, "s", datetime(2026, 1, 1), meta, 200, {}, b"")
