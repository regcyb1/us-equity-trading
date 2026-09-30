import io
import logging
import pickle
import secrets as pysecrets
import string

import pytest

from config import secrets as sec


@pytest.fixture(autouse=True)
def _clean_registry():
    sec._clear_registry_for_tests()
    yield
    sec._clear_registry_for_tests()


@pytest.fixture
def fake_value():
    return "fake-" + pysecrets.token_hex(16)


def _capture_logger(name):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    sec.install_log_redaction(logger)
    return logger, stream


# --- missing key raises, naming the variable only ---

def test_missing_secret_raises_with_name(monkeypatch):
    monkeypatch.delenv("TEST_MISSING_KEY", raising=False)
    with pytest.raises(sec.MissingSecretError) as exc:
        sec.get_secret("TEST_MISSING_KEY")
    assert "TEST_MISSING_KEY" in str(exc.value)
    assert exc.value.name == "TEST_MISSING_KEY"


def test_empty_secret_treated_as_missing(monkeypatch):
    monkeypatch.setenv("TEST_EMPTY_KEY", "   ")
    with pytest.raises(sec.MissingSecretError):
        sec.get_secret("TEST_EMPTY_KEY")


def test_loaded_value_not_in_error_messages(monkeypatch, fake_value):
    monkeypatch.setenv("TEST_KEY", fake_value)
    s = sec.get_secret("TEST_KEY")
    try:
        raise ValueError(f"bad key {s}")
    except ValueError as e:
        assert fake_value not in str(e)


def test_get_setting_default_and_missing(monkeypatch):
    monkeypatch.delenv("TEST_SETTING", raising=False)
    assert sec.get_setting("TEST_SETTING", "paper") == "paper"
    with pytest.raises(sec.MissingSecretError):
        sec.get_setting("TEST_SETTING")


# --- redacting repr ---

def test_repr_str_format_are_masked(monkeypatch, fake_value):
    monkeypatch.setenv("TEST_KEY", fake_value)
    s = sec.get_secret("TEST_KEY")
    for rendered in (repr(s), str(s), f"{s}", f"{s!r}", repr({"k": s}), repr([s])):
        assert fake_value not in rendered
        assert sec.MASK in rendered
    assert "TEST_KEY" in repr(s)
    assert s.reveal() == fake_value


def test_secret_cannot_be_pickled(monkeypatch, fake_value):
    monkeypatch.setenv("TEST_KEY", fake_value)
    with pytest.raises(TypeError):
        pickle.dumps(sec.get_secret("TEST_KEY"))


# --- log redaction filter ---

def test_log_masks_loaded_value_in_args(monkeypatch, fake_value):
    monkeypatch.setenv("TEST_KEY", fake_value)
    s = sec.get_secret("TEST_KEY")
    logger, stream = _capture_logger("t.args")
    logger.info("url=https://x.test/?k=%s", s.reveal())
    logger.info("raw %s", fake_value)
    out = stream.getvalue()
    assert fake_value not in out
    assert out.count(sec.MASK) == 2


def test_log_masks_value_in_exception_text(monkeypatch, fake_value):
    monkeypatch.setenv("TEST_KEY", fake_value)
    sec.get_secret("TEST_KEY")
    logger, stream = _capture_logger("t.exc")
    try:
        raise RuntimeError("failed with " + fake_value)
    except RuntimeError:
        logger.exception("boom")
    assert fake_value not in stream.getvalue()


def test_log_masks_known_patterns_never_loaded():
    alnum = string.ascii_letters + string.digits
    pat = "ghp_" + "".join(pysecrets.choice(alnum) for _ in range(36))
    qs_val = pysecrets.token_hex(12)
    logger, stream = _capture_logger("t.pat")
    logger.info("token %s", pat)
    logger.info("GET /v1?apiKey=%s&x=1", qs_val)
    out = stream.getvalue()
    assert pat not in out
    assert qs_val not in out
    assert "x=1" in out


def test_install_is_idempotent():
    logger, _ = _capture_logger("t.idem")
    sec.install_log_redaction(logger)
    assert sum(isinstance(f, sec.RedactingFilter) for f in logger.handlers[0].filters) == 1
