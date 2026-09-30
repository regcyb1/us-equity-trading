"""Massive grouped daily prices.

One call returns the whole US stock market for one session, unadjusted, delisted names
included. The key is sent as a Bearer header, never in the URL.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from config.secrets import get_secret

SOURCE = "massive"
KEY_ENV = "MASSIVE_API_KEY"
BASE_URL = "https://api.massive.com"
KEY = ("date", "ticker")
COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume", "vwap",
           "n_trades", "otc"]

_FIELDS = {"T": "ticker", "o": "open", "h": "high", "l": "low", "c": "close",
           "v": "volume", "vw": "vwap", "n": "n_trades", "otc": "otc"}
_REQUIRED = ["T", "o", "h", "l", "c", "v"]
_DTYPES = {"date": "datetime64[ns]", "ticker": "str", "open": "float64", "high": "float64",
           "low": "float64", "close": "float64", "volume": "float64", "vwap": "float64",
           "n_trades": "Int64", "otc": "bool"}


class MassiveResponseError(ValueError):
    pass


def grouped_daily_url(session: date) -> str:
    return f"{BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{session.isoformat()}"


def parse_grouped(payload: dict, session: date) -> pd.DataFrame:
    """Parse a grouped-daily payload into the bronze massive_grouped shape. Pure.

    Zero rows is returned as an empty frame; the caller decides whether that is valid
    (only on a non-session day).
    """
    status = payload.get("status")
    if status not in ("OK", "DELAYED"):
        raise MassiveResponseError(f"unexpected status {status!r}")
    if payload.get("adjusted") is not False:
        raise MassiveResponseError("expected unadjusted prices (adjusted=false)")
    results = payload.get("results") or []
    if not results:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in _DTYPES.items()})
    raw = pd.DataFrame(results)
    missing = [c for c in _REQUIRED if c not in raw.columns]
    if missing:
        raise MassiveResponseError(f"results missing fields {missing}")
    for k in _FIELDS:
        if k not in raw.columns:
            raw[k] = False if k == "otc" else float("nan")
    df = raw[list(_FIELDS)].rename(columns=_FIELDS)
    df.insert(0, "date", pd.Timestamp(session))
    df["otc"] = df["otc"].fillna(False).astype(bool)
    df["volume"] = df["volume"].astype(float)  # Massive can return fractional volume
    df["n_trades"] = pd.to_numeric(df["n_trades"], errors="coerce").astype("Int64")
    df = df.astype({c: t for c, t in _DTYPES.items() if c not in ("date", "n_trades")})
    count = payload.get("resultsCount")
    if count is not None and count != len(df):
        raise MassiveResponseError(f"resultsCount {count} != parsed rows {len(df)}")
    return df[COLUMNS]


def fetch_grouped(client, session: date) -> pd.DataFrame:
    """Fetch the grouped daily bars for one session (raw-archived by the client)."""
    key = get_secret(KEY_ENV)
    resp = client.get(SOURCE, grouped_daily_url(session), params={"adjusted": "false"},
                      headers={"Authorization": f"Bearer {key.reveal()}"})
    return parse_grouped(json.loads(resp.content), session)
