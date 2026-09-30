"""Env-only secret loading, redacting repr and log redaction filter.

Secrets are read only from environment variables. A missing or empty variable raises
MissingSecretError naming the variable, never a value. Loaded values are wrapped in
SecretValue, whose repr/str is "***", and registered so RedactingFilter can mask them
in log records.
"""

from __future__ import annotations

import logging
import os
import re
import threading

MASK = "***"
_MIN_REGISTERED_LEN = 4  # shorter values would mask unrelated text

# Known key shapes, masked even if never loaded through this module.
_KNOWN_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|apikey|token|secret|password)=)[^&\s]+"),
]

_lock = threading.Lock()
_loaded: set[str] = set()


class MissingSecretError(RuntimeError):
    """A required environment variable is unset or empty."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Required environment variable {name!r} is not set")


class SecretValue:
    """Holds a secret. repr/str never show it; call reveal() at the point of use."""

    __slots__ = ("_name", "_value")

    def __init__(self, name: str, value: str):
        self._name = name
        self._value = value

    @property
    def name(self) -> str:
        return self._name

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"SecretValue({self._name}={MASK})"

    def __str__(self) -> str:
        return MASK

    def __format__(self, spec: str) -> str:
        return MASK

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretValue) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __reduce__(self):
        raise TypeError("SecretValue cannot be pickled")


def _register(value: str) -> None:
    if len(value) >= _MIN_REGISTERED_LEN:
        with _lock:
            _loaded.add(value)


def get_secret(name: str) -> SecretValue:
    """Load a secret from the environment. Raises MissingSecretError if unset/empty."""
    value = os.environ.get(name, "")
    if not value.strip():
        raise MissingSecretError(name)
    _register(value)
    return SecretValue(name, value)


def get_setting(name: str, default: str | None = None) -> str:
    """Load a non-secret setting from the environment (e.g. TRADING_MODE)."""
    value = os.environ.get(name, "")
    if value.strip():
        return value
    if default is not None:
        return default
    raise MissingSecretError(name)


def redact(text: str) -> str:
    """Mask every loaded secret value and known key pattern in text."""
    with _lock:
        values = sorted(_loaded, key=len, reverse=True)
    for v in values:
        text = text.replace(v, MASK)
    for pat in _KNOWN_PATTERNS:
        if pat.groups:
            text = pat.sub(lambda m: m.group(1) + MASK, text)
        else:
            text = pat.sub(MASK, text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that masks secrets in the rendered message and exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def install_log_redaction(logger: logging.Logger | None = None) -> RedactingFilter:
    """Attach one RedactingFilter to every handler of logger (default: root)."""
    logger = logger or logging.getLogger()
    filt = RedactingFilter()
    for handler in logger.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(filt)
    return filt


def _clear_registry_for_tests() -> None:
    with _lock:
        _loaded.clear()
