import secrets as pysecrets
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from config import secrets as sec
from config.secrets import MissingSecretError
from ingest.http import HttpClient, SourcePolicy
from ingest.raw_archive import read_raw
from ingest.sources import fred, massive, nasdaq_symdir, sp500_membership
from tests.fixtures import fake_http as fh

S = date(2026, 9, 30)


def client(tmp_path, routes):
    t = fh.RoutingTransport(routes)
    c = HttpClient(archive_root=tmp_path, transport=t, user_agent="ua-test",
                   default_policy=SourcePolicy(max_retries=0), sleep=lambda s: None,
                   now=lambda: datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc))
    return c, t


@pytest.fixture(autouse=True)
def _clean_registry():
    sec._clear_registry_for_tests()
    yield
    sec._clear_registry_for_tests()


# --- nasdaq symbol directory ---

def test_symdir_parse_nasdaq():
    df = nasdaq_symdir.parse_symdir(fh.symdir_nasdaq(5), "nasdaqlisted")
    assert list(df.columns) == nasdaq_symdir.COLUMNS
    assert len(df) == 5
    assert df["exchange"].eq("Q").all()
    assert df["test_issue"].sum() == 1 and df["etf"].sum() == 1
    assert df["snapshot_date"].iloc[0] == pd.Timestamp("2026-09-30")
    assert str(df["file_created"].dt.tz) == "UTC"
    assert df["file_created"].iloc[0] == pd.Timestamp("2026-09-30 07:03", tz="UTC")


def test_symdir_parse_other():
    df = nasdaq_symdir.parse_symdir(fh.symdir_other(4), "otherlisted")
    assert len(df) == 4 and df["exchange"].eq("N").all()


def test_symdir_truncated_rejected():
    text = fh.symdir_nasdaq(5).rsplit("File Creation", 1)[0]
    with pytest.raises(nasdaq_symdir.SymdirParseError, match="footer"):
        nasdaq_symdir.parse_symdir(text, "nasdaqlisted")


def test_symdir_missing_column_rejected():
    text = fh.symdir_nasdaq(3).replace("Round Lot Size", "Lot")
    with pytest.raises(nasdaq_symdir.SymdirParseError, match="missing columns"):
        nasdaq_symdir.parse_symdir(text, "nasdaqlisted")


def test_symdir_fetch_archives_both(tmp_path):
    c, t = client(tmp_path, {"nasdaqlisted": fh.resp(fh.symdir_nasdaq(5)),
                             "otherlisted": fh.resp(fh.symdir_other(4))})
    df = nasdaq_symdir.fetch_snapshot(c)
    assert len(df) == 9
    assert len(list((tmp_path / "raw" / "nasdaq_symdir").rglob("*.json.gz"))) == 2


# --- massive ---

def test_massive_parse():
    df = massive.parse_grouped(fh.massive_grouped(100), S)
    assert list(df.columns) == massive.COLUMNS and len(df) == 100
    assert df["date"].eq(pd.Timestamp(S)).all()
    assert df["otc"].sum() == 1
    assert df["volume"].dtype == "float64" and df["n_trades"].dtype == "Int64"


def test_massive_optional_fields_missing_stay_missing():
    df = massive.parse_grouped(fh.massive_grouped(3, drop_optional=True), S)
    assert df["vwap"].isna().all() and df["n_trades"].isna().all()
    assert df["close"].notna().all()


def test_massive_empty_results():
    p = {"status": "OK", "adjusted": False, "resultsCount": 0, "queryCount": 0}
    df = massive.parse_grouped(p, S)
    assert df.empty and list(df.columns) == massive.COLUMNS


@pytest.mark.parametrize("mutate,match", [
    (lambda p: p.update(status="ERROR"), "status"),
    (lambda p: p.update(adjusted=True), "unadjusted"),
    (lambda p: p.update(resultsCount=999), "resultsCount"),
    (lambda p: [r.pop("c") for r in p["results"]], "missing fields"),
])
def test_massive_bad_payloads(mutate, match):
    p = fh.massive_grouped(5)
    mutate(p)
    with pytest.raises(massive.MassiveResponseError, match=match):
        massive.parse_grouped(p, S)


def test_massive_fetch_uses_header_and_strips_key(tmp_path, monkeypatch):
    key = "fake-" + pysecrets.token_hex(16)
    monkeypatch.setenv("MASSIVE_API_KEY", key)
    c, t = client(tmp_path, {"/v2/aggs/grouped/": fh.resp(fh.massive_grouped(10))})
    df = massive.fetch_grouped(c, S)
    assert len(df) == 10
    call = t.calls[0]
    assert call["url"].endswith("/stocks/2026-09-30") and key not in call["url"]
    assert call["params"] == {"adjusted": "false"}
    assert call["headers"]["Authorization"] == f"Bearer {key}"
    path = next((tmp_path / "raw" / "massive").rglob("*.json.gz"))
    assert key not in path.read_bytes().decode("latin-1")
    assert read_raw(path)["request"]["headers"]["Authorization"] == "***"


def test_massive_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    c, t = client(tmp_path, {})
    with pytest.raises(MissingSecretError, match="MASSIVE_API_KEY"):
        massive.fetch_grouped(c, S)
    assert t.calls == []


# --- fred ---

def test_fred_parse_keeps_missing_as_nan():
    df = fred.parse_observations(fh.fred_obs(["2026-09-28", "2026-09-29"], ["4.10", "."]),
                                 "DGS10")
    assert list(df.columns) == fred.COLUMNS
    assert df["value"].iloc[0] == 4.10 and pd.isna(df["value"].iloc[1])
    assert df["vintage"].eq(pd.Timestamp("2026-09-30")).all()


def test_fred_unparseable_value_rejected():
    with pytest.raises(fred.FredResponseError, match="unparseable"):
        fred.parse_observations(fh.fred_obs(["2026-09-28"], ["n/a"]), "DGS10")


def test_fred_missing_observations_rejected():
    with pytest.raises(fred.FredResponseError):
        fred.parse_observations({"error_code": 400}, "DGS10")


def test_fred_fetch_all_strips_key(tmp_path, monkeypatch):
    key = "fake-" + pysecrets.token_hex(16)
    monkeypatch.setenv("FRED_API_KEY", key)
    c, t = client(tmp_path, {"fred/series/observations": fh.resp(
        fh.fred_obs(["2026-09-29"], ["1.0"]))})
    df = fred.fetch_all(c, date(2026, 9, 16), S)
    assert len(df) == len(fred.SERIES)
    assert {call["params"]["series_id"] for call in t.calls} == set(fred.SERIES)
    for p in (tmp_path / "raw" / "fred").rglob("*.json.gz"):
        assert read_raw(p)["request"]["params"]["api_key"] == "***"


# --- s&p 500 membership ---

def test_membership_parse_and_latest():
    csv = fh.membership_csv([("2026-08-01", fh.tickers(500)),
                             ("2026-08-18", fh.tickers(501))])
    hist = sp500_membership.parse_history(csv, "fja05680")
    assert list(hist.columns) == sp500_membership.COLUMNS and len(hist) == 1001
    snap = sp500_membership.latest_snapshot(hist)
    assert len(snap) == 501 and snap["date"].eq(pd.Timestamp("2026-08-18")).all()


def test_membership_implausible_count_rejected():
    hist = sp500_membership.parse_history(fh.membership_csv([("2026-08-18", fh.tickers(20))]), "x")
    with pytest.raises(sp500_membership.MembershipParseError, match="20 members"):
        sp500_membership.latest_snapshot(hist)


def test_membership_bad_dates_rejected():
    with pytest.raises(sp500_membership.MembershipParseError):
        sp500_membership.parse_history(fh.membership_csv([("18/08/2026", ["A"])]), "x")



def test_membership_conflicting_duplicate_dates_dropped():
    csv = fh.membership_csv([("2026-08-01", ["A", "B"]), ("2026-08-01", ["A", "C"]),
                             ("2026-08-05", ["A"]), ("2026-08-05", ["A"]),
                             ("2026-08-18", ["B"])])
    hist = sp500_membership.parse_history(csv, "x")
    assert hist.attrs["conflicting_dates"] == 1
    assert pd.Timestamp("2026-08-01") not in set(hist["date"])
    assert (hist["date"] == pd.Timestamp("2026-08-05")).sum() == 1  # identical dup kept once


def test_membership_diff():
    old = pd.DataFrame({"ticker": ["A", "B", "C"]})
    new = pd.DataFrame({"ticker": ["B", "C", "D", "E"]})
    assert sp500_membership.diff_snapshots(old, new) == {"added": 2, "removed": 1, "kept": 2}
