"""S&P 500 membership files, weekly pull and diff.

Two community histories (tier C) with the same shape: `date,tickers` where tickers is a
comma-separated list. Bronze keeps each source's latest snapshot; the full history
stays in the raw archive.
"""

from __future__ import annotations

import io

import pandas as pd

SOURCE = "sp500_membership"
FILES = {
    "fja05680": "https://raw.githubusercontent.com/fja05680/sp500/master/"
                "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv",
    "hanshof": "https://raw.githubusercontent.com/hanshof/sp500_constituents/main/"
               "sp_500_historical_components.csv",
}
KEY = ("source", "date", "ticker")
COLUMNS = ["source", "date", "ticker"]
MIN_MEMBERS, MAX_MEMBERS = 480, 520  # the index holds ~500-505 share classes


class MembershipParseError(ValueError):
    pass


def parse_history(text: str, source: str) -> pd.DataFrame:
    """Parse a `date,tickers` history into long (source, date, ticker) rows. Pure."""
    raw = pd.read_csv(io.StringIO(text), dtype=str)
    missing = [c for c in ("date", "tickers") if c not in raw.columns]
    if missing:
        raise MembershipParseError(f"{source}: missing columns {missing}")
    raw["date"] = pd.to_datetime(raw["date"], format="%Y-%m-%d", errors="coerce")
    if raw["date"].isna().any() or raw["tickers"].isna().any():
        raise MembershipParseError(f"{source}: unparseable rows")
    # A date listed twice with different lists is untrustworthy: drop all its rows.
    # The count is kept in attrs; the raw archive still holds the original file.
    n_lists = raw.groupby("date")["tickers"].transform("nunique")
    conflicting = raw.loc[n_lists > 1, "date"].nunique()
    raw = raw[n_lists == 1].drop_duplicates()
    long = raw.assign(ticker=raw["tickers"].str.split(",")).explode("ticker")
    long["ticker"] = long["ticker"].str.strip()
    long = long[long["ticker"] != ""]
    long.insert(0, "source", source)
    out = long[COLUMNS].drop_duplicates().sort_values(["date", "ticker"]).reset_index(drop=True)
    out.attrs["conflicting_dates"] = int(conflicting)
    return out


def latest_snapshot(history: pd.DataFrame) -> pd.DataFrame:
    """Rows for the latest date only. Raises if the member count is implausible."""
    missing = [c for c in COLUMNS if c not in history.columns]
    if missing:
        raise MembershipParseError(f"missing columns {missing}")
    last = history["date"].max()
    snap = history[history["date"] == last].reset_index(drop=True)
    if not MIN_MEMBERS <= len(snap) <= MAX_MEMBERS:
        raise MembershipParseError(f"latest snapshot has {len(snap)} members")
    return snap


def diff_snapshots(old: pd.DataFrame, new: pd.DataFrame) -> dict[str, int]:
    """Counts of tickers added/removed/kept between two snapshots. Pure."""
    a, b = set(old["ticker"]), set(new["ticker"])
    return {"added": len(b - a), "removed": len(a - b), "kept": len(a & b)}


def fetch_latest(client) -> tuple[pd.DataFrame, dict[str, pd.Timestamp], dict[str, int]]:
    """Fetch every source; return latest snapshots, each source's last date and its
    count of dropped conflicting dates."""
    frames, last_dates, conflicts = [], {}, {}
    for source, url in FILES.items():
        resp = client.get(SOURCE, url)
        hist = parse_history(resp.content.decode("utf-8"), source)
        snap = latest_snapshot(hist)
        frames.append(snap)
        last_dates[source] = snap["date"].iloc[0]
        conflicts[source] = hist.attrs["conflicting_dates"]
    return pd.concat(frames, ignore_index=True), last_dates, conflicts
