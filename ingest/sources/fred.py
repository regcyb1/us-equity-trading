"""FRED macro series.

Values FRED reports as "." are kept as NaN (missing), never filled. The vintage is the
observation's realtime_start: what FRED showed as of that date.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from config.secrets import get_secret

SOURCE = "fred"
KEY_ENV = "FRED_API_KEY"
URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES = ("DGS10", "DGS2", "T10Y2Y", "DFF", "VIXCLS", "BAMLH0A0HYM2")
KEY = ("series", "date", "vintage")
COLUMNS = ["date", "series", "value", "vintage"]
_REQUIRED = ["date", "value", "realtime_start"]


class FredResponseError(ValueError):
    pass


def parse_observations(payload: dict, series: str) -> pd.DataFrame:
    """Parse a series/observations payload into the bronze fred shape. Pure."""
    if "observations" not in payload:
        raise FredResponseError(f"{series}: no observations field")
    obs = payload["observations"]
    if not obs:
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                             "series": pd.Series(dtype="str"),
                             "value": pd.Series(dtype="float64"),
                             "vintage": pd.Series(dtype="datetime64[ns]")})
    raw = pd.DataFrame(obs)
    missing = [c for c in _REQUIRED if c not in raw.columns]
    if missing:
        raise FredResponseError(f"{series}: observations missing fields {missing}")
    value = pd.to_numeric(raw["value"].where(raw["value"] != "."), errors="coerce")
    bad = int(value.isna().sum() - (raw["value"] == ".").sum())
    if bad:
        raise FredResponseError(f"{series}: {bad} unparseable values")
    return pd.DataFrame({
        "date": pd.to_datetime(raw["date"]),
        "series": series,
        "value": value.astype("float64"),
        "vintage": pd.to_datetime(raw["realtime_start"]),
    }, columns=COLUMNS)


def fetch_series(client, series: str, start: date, end: date) -> pd.DataFrame:
    """Fetch observations for one series over [start, end] (raw-archived by the client)."""
    key = get_secret(KEY_ENV)
    resp = client.get(SOURCE, URL, params={
        "series_id": series, "api_key": key.reveal(), "file_type": "json",
        "observation_start": start.isoformat(), "observation_end": end.isoformat(),
    })
    return parse_observations(json.loads(resp.content), series)


def fetch_all(client, start: date, end: date, series: tuple[str, ...] = SERIES) -> pd.DataFrame:
    return pd.concat([fetch_series(client, s, start, end) for s in series], ignore_index=True)
