import logging
import secrets as pysecrets
from datetime import datetime, timezone

import pytest

from config import secrets as sec
from ingest.http import HttpClient, SourcePolicy, TransportError
from pipelines import bronze, daily_collect as dc
from tests.fixtures import fake_http as fh

NOW = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)  # main cron, after the close


def routes(n_massive=100):
    return {
        "nasdaqlisted": fh.resp(fh.symdir_nasdaq(5)),
        "otherlisted": fh.resp(fh.symdir_other(4)),
        "/v2/aggs/grouped/": fh.resp(fh.massive_grouped(n_massive)),
        "fred/series/observations": fh.resp(fh.fred_obs(["2026-09-29"], ["1.0"])),
        "fja05680": fh.resp(fh.membership_csv([("2026-08-18", fh.tickers(503))])),
        "hanshof": fh.resp(fh.membership_csv([("2025-08-23", fh.tickers(500))])),
    }


def make_client(tmp_path, r, now=NOW):
    t = fh.RoutingTransport(r)
    c = HttpClient(archive_root=tmp_path, transport=t, user_agent="ua-test",
                   default_policy=SourcePolicy(max_retries=0), sleep=lambda s: None,
                   now=lambda: now)
    return c, t


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    sec._clear_registry_for_tests()
    monkeypatch.setenv("MASSIVE_API_KEY", "fake-" + pysecrets.token_hex(16))
    monkeypatch.setenv("FRED_API_KEY", "fake-" + pysecrets.token_hex(16))
    yield
    sec._clear_registry_for_tests()


def run(tmp_path, r=None, now=NOW, extra=()):
    c, t = make_client(tmp_path, r or routes(), now)
    code = dc.main(["--data-root", str(tmp_path), *extra], client=c, now=now)
    return code, t


def test_full_run_writes_all_bronze(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="daily_collect")
    code, t = run(tmp_path)
    assert code == 0
    b = tmp_path / "bronze"
    assert (b / "massive_grouped" / "date=2026-09-30.parquet").exists()
    assert (b / "nasdaq_symdir" / "snapshot=2026-09-30.parquet").exists()
    assert (b / "fred" / "fetch=2026-09-30.parquet").exists()
    assert (b / "sp500_membership" / "fetch=2026-09-30.parquet").exists()
    assert "hanshof stale" in caplog.text
    assert "done: 4 sources, 0 failed" in caplog.text


def test_rerun_is_idempotent_and_skips_calls(tmp_path):
    run(tmp_path)
    code, t = run(tmp_path)
    assert code == 0
    urls = [c["url"] for c in t.calls]
    assert not any("/v2/aggs/grouped/" in u for u in urls)   # already collected
    assert not any("fja05680" in u for u in urls)            # weekly, not due


def test_logs_contain_no_data_values(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="daily_collect")
    run(tmp_path)
    for value in ("M001", "NQ002", "10.5", "Synthetic", "T001"):
        assert value not in caplog.text


def test_holiday_no_session(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="daily_collect")
    thanksgiving = datetime(2026, 11, 26, 23, 30, tzinfo=timezone.utc)
    code, t = run(tmp_path, now=thanksgiving, extra=["--date", "2026-11-26",
                                                     "--sources", "massive"])
    assert code == 0
    assert "holiday=Thanksgiving Day" in caplog.text
    assert "no_session" in caplog.text
    assert t.calls == []


def test_zero_rows_on_session_is_failure(tmp_path):
    r = routes()
    r["/v2/aggs/grouped/"] = fh.resp({"status": "OK", "adjusted": False, "resultsCount": 0})
    code, _ = run(tmp_path, r, extra=["--sources", "massive"])
    assert code == 1
    assert not (tmp_path / "bronze" / "massive_grouped").exists()


def test_injected_failure_isolated_and_alerts(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="daily_collect")
    r = routes()
    r["/v2/aggs/grouped/"] = TransportError("ConnectionError")
    code, _ = run(tmp_path, r)
    assert code == 1
    assert "done: 4 sources, 1 failed" in caplog.text
    assert (tmp_path / "bronze" / "fred" / "fetch=2026-09-30.parquet").exists()


def test_missing_key_fails_by_name(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="daily_collect")
    monkeypatch.delenv("MASSIVE_API_KEY")
    code, _ = run(tmp_path, extra=["--sources", "massive"])
    assert code == 1
    assert "MASSIVE_API_KEY" in caplog.text


def test_row_count_jump_blocks_write(tmp_path):
    prev_now = datetime(2026, 9, 29, 23, 30, tzinfo=timezone.utc)
    r = routes(100)
    run(tmp_path, r, now=prev_now, extra=["--sources", "massive"])
    r["/v2/aggs/grouped/"] = fh.resp(fh.massive_grouped(90))   # -10%
    code, _ = run(tmp_path, r, extra=["--sources", "massive"])
    assert code == 1
    assert not (tmp_path / "bronze" / "massive_grouped" / "date=2026-09-30.parquet").exists()


def test_integrity_check_pure():
    import pandas as pd
    today = pd.DataFrame({"date": [1, 1, 1], "ticker": ["A", "A", "B"], "close": [1.0, 0.0, None]})
    prev = pd.DataFrame({"date": [0] * 10, "ticker": list("ABCDEFGHIJ"), "close": [1.0] * 10})
    problems = dc.check_integrity(today, prev, ("date", "ticker"), "close")
    assert any("1 duplicate keys" in p for p in problems)
    assert any("2 rows with close" in p for p in problems)
    assert any("row count changed" in p for p in problems)
    assert dc.check_integrity(today.iloc[[0]], None, ("date", "ticker"), "close") == []


def test_shrink_reported_not_raised(tmp_path):
    r = routes()
    run(tmp_path, r, extra=["--sources", "nasdaq_symdir"])
    r["otherlisted"] = fh.resp(fh.symdir_other(3))  # 1 symbol fewer, same snapshot
    code, _ = run(tmp_path, r, extra=["--sources", "nasdaq_symdir"])
    assert code == 1
    assert len(bronze.read_partition(tmp_path, "nasdaq_symdir", "snapshot=2026-09-30")) == 9


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(SystemExit):
        run(tmp_path, extra=["--sources", "nope"])
