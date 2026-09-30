"""Nasdaq symbol directory daily snapshot.

nasdaqlisted.txt and otherlisted.txt are pipe-delimited with a "File Creation Time"
footer. A file without the footer is treated as truncated and rejected.
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd

from config.market_calendar import ET

SOURCE = "nasdaq_symdir"
BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/"
LIST_FILES = ("nasdaqlisted", "otherlisted")
KEY = ("list_file", "symbol")
COLUMNS = ["snapshot_date", "file_created", "list_file", "symbol", "security_name",
           "exchange", "etf", "test_issue", "round_lot"]

_FOOTER = "File Creation Time:"
_REQUIRED = {
    "nasdaqlisted": ["Symbol", "Security Name", "Test Issue", "Round Lot Size", "ETF"],
    "otherlisted": ["ACT Symbol", "Security Name", "Exchange", "ETF", "Round Lot Size",
                    "Test Issue"],
}


class SymdirParseError(ValueError):
    pass


def _parse_created(footer: str) -> datetime:
    stamp = footer.split(_FOOTER, 1)[1].split("|", 1)[0].strip()  # MMDDYYYYHH:MM, ET
    try:
        return datetime.strptime(stamp, "%m%d%Y%H:%M").replace(tzinfo=ET)
    except ValueError:
        raise SymdirParseError("unreadable file creation time") from None


def parse_symdir(text: str, list_file: str) -> pd.DataFrame:
    """Parse one directory file into the bronze nasdaq_symdir shape. Pure."""
    if list_file not in _REQUIRED:
        raise ValueError(f"unknown list file {list_file!r}")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2 or not lines[-1].startswith(_FOOTER):
        raise SymdirParseError(f"{list_file}: missing footer (truncated file?)")
    created = _parse_created(lines[-1])
    raw = pd.read_csv(io.StringIO("\n".join(lines[:-1])), sep="|", dtype=str,
                      keep_default_na=False)
    missing = [c for c in _REQUIRED[list_file] if c not in raw.columns]
    if missing:
        raise SymdirParseError(f"{list_file}: missing columns {missing}")

    sym_col = "Symbol" if list_file == "nasdaqlisted" else "ACT Symbol"
    exchange = "Q" if list_file == "nasdaqlisted" else raw["Exchange"]
    df = pd.DataFrame({
        "snapshot_date": pd.Timestamp(created.date()),
        "file_created": pd.Timestamp(created).tz_convert("UTC"),
        "list_file": list_file,
        "symbol": raw[sym_col].str.strip(),
        "security_name": raw["Security Name"].str.strip(),
        "exchange": exchange,
        "etf": raw["ETF"].eq("Y"),
        "test_issue": raw["Test Issue"].eq("Y"),
        "round_lot": pd.to_numeric(raw["Round Lot Size"], errors="coerce").astype("Int64"),
    }, columns=COLUMNS)
    if (df["symbol"] == "").any():
        raise SymdirParseError(f"{list_file}: empty symbols")
    return df


def fetch_snapshot(client) -> pd.DataFrame:
    """Fetch both directory files (raw-archived by the client) and return one frame."""
    frames = []
    for name in LIST_FILES:
        resp = client.get(SOURCE, f"{BASE_URL}{name}.txt")
        frames.append(parse_symdir(resp.content.decode("utf-8", errors="replace"), name))
    return pd.concat(frames, ignore_index=True)
