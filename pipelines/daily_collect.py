"""Forward collector run by GitHub Actions.

Per run: Nasdaq symbol directory snapshot, Massive grouped daily for the last completed
session, FRED macro series, and (weekly) S&P 500 membership. Every source is
independent: one failing does not stop the others, but any failure makes the exit
code non-zero. Idempotent: re-running a day rewrites nothing that is already there.

Logs print statuses and counts only, never data values (Actions logs are public).

    python -m pipelines.daily_collect [--date YYYY-MM-DD] [--sources a,b] [--data-root data]
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from config.market_calendar import ET, MarketCalendar, load_calendar
from config.secrets import MissingSecretError, install_log_redaction
from ingest.http import HttpClient, HttpError
from ingest.sources import fred, massive, nasdaq_symdir, sp500_membership
from pipelines import bronze

log = logging.getLogger("daily_collect")

ROW_TOLERANCE = 0.05
FRED_LOOKBACK_DAYS = 14
MEMBERSHIP_EVERY_DAYS = 7
MEMBERSHIP_STALE_DAYS = 45
ALL_SOURCES = ("nasdaq_symdir", "massive", "fred", "sp500_membership")


@dataclass
class Result:
    source: str
    status: str  # ok | unchanged | skipped | no_session | error
    rows: int = 0
    detail: str = ""


@dataclass
class Context:
    client: HttpClient
    calendar: MarketCalendar
    data_root: Path
    session: date
    now: datetime


# --- pure checks -------------------------------------------------------------

def check_integrity(today: pd.DataFrame, prev: pd.DataFrame | None, key: tuple[str, ...],
                    price_col: str | None = None,
                    tolerance: float = ROW_TOLERANCE) -> list[str]:
    """Row count within tolerance of prev, no duplicate keys, prices > 0. Counts only."""
    missing = [c for c in key + ((price_col,) if price_col else ()) if c not in today.columns]
    if missing:
        return [f"missing columns {missing}"]
    problems = []
    n_dup = int(today.duplicated(list(key)).sum())
    if n_dup:
        problems.append(f"{n_dup} duplicate keys")
    if price_col:
        n_bad = int((~(today[price_col] > 0)).sum())  # NaN counts as bad
        if n_bad:
            problems.append(f"{n_bad} rows with {price_col} <= 0 or missing")
    if prev is not None and len(prev):
        change = abs(len(today) - len(prev)) / len(prev)
        if change > tolerance:
            problems.append(f"row count changed {change:.1%} vs previous (limit {tolerance:.0%})")
    return problems


# --- per-source steps --------------------------------------------------------

def _write(df, ctx, table, partition, key, prev_partition=None, price_col=None) -> Result:
    prev = bronze.read_partition(ctx.data_root, table, prev_partition) if prev_partition else None
    problems = check_integrity(df, prev, key, price_col)
    if problems:
        return Result(table, "error", len(df), "integrity: " + "; ".join(problems))
    status = bronze.write_partition(df, ctx.data_root, table, partition, key)
    return Result(table, "unchanged" if status == "unchanged" else "ok", len(df), status)


def collect_symdir(ctx: Context) -> Result:
    df = nasdaq_symdir.fetch_snapshot(ctx.client)
    part = f"snapshot={df['snapshot_date'].max().date().isoformat()}"
    prev = bronze.latest_partition_before(ctx.data_root, nasdaq_symdir.SOURCE, part)
    return _write(df, ctx, nasdaq_symdir.SOURCE, part, nasdaq_symdir.KEY, prev)


def collect_massive(ctx: Context) -> Result:
    table = "massive_grouped"
    if not ctx.calendar.is_session(ctx.session):
        return Result(table, "no_session", detail=str(ctx.session))
    part = f"date={ctx.session.isoformat()}"
    if bronze.read_partition(ctx.data_root, table, part) is not None:
        return Result(table, "unchanged", detail="already collected")
    df = massive.fetch_grouped(ctx.client, ctx.session)
    if df.empty:
        return Result(table, "error", 0, "0 rows on a session day (not yet published?)")
    prev = f"date={ctx.calendar.previous_session(ctx.session).isoformat()}"
    return _write(df, ctx, table, part, massive.KEY, prev, price_col="close")


def collect_fred(ctx: Context) -> Result:
    start = ctx.session - timedelta(days=FRED_LOOKBACK_DAYS)
    df = fred.fetch_all(ctx.client, start, ctx.session)
    part = f"fetch={ctx.now.date().isoformat()}"
    return _write(df, ctx, fred.SOURCE, part, fred.KEY)


def collect_membership(ctx: Context) -> Result:
    table = sp500_membership.SOURCE
    part = f"fetch={ctx.now.date().isoformat()}"
    if bronze.read_partition(ctx.data_root, table, part) is not None:
        return Result(table, "skipped", detail="already pulled today")
    prev_name = bronze.latest_partition_before(ctx.data_root, table, part)
    if prev_name:
        prev_day = date.fromisoformat(prev_name.split("=", 1)[1])
        if (ctx.now.date() - prev_day).days < MEMBERSHIP_EVERY_DAYS:
            return Result(table, "skipped", detail="not due (weekly)")
    df, last_dates, conflicts = sp500_membership.fetch_latest(ctx.client)
    notes = [f"{src} dropped {n} conflicting dates" for src, n in conflicts.items() if n]
    for source, last in last_dates.items():
        age = (ctx.now.date() - last.date()).days
        if age > MEMBERSHIP_STALE_DAYS:
            notes.append(f"{source} stale {age}d")
    if prev_name:
        prev = bronze.read_partition(ctx.data_root, table, prev_name)
        for source in last_dates:
            d = sp500_membership.diff_snapshots(prev[prev["source"] == source],
                                                df[df["source"] == source])
            notes.append(f"{source} +{d['added']}/-{d['removed']}")
    # Membership legitimately changes, so no row-count tolerance here.
    status = bronze.write_partition(df, ctx.data_root, table, part, sp500_membership.KEY)
    return Result(table, "unchanged" if status == "unchanged" else "ok", len(df),
                  ", ".join(notes))


STEPS: dict[str, Callable[[Context], Result]] = {
    "nasdaq_symdir": collect_symdir,
    "massive": collect_massive,
    "fred": collect_fred,
    "sp500_membership": collect_membership,
}


# --- orchestration -----------------------------------------------------------

def _safe_detail(exc: Exception) -> str:
    # Our own error types carry count-only messages; anything else logs its type only.
    ours = (HttpError, MissingSecretError, bronze.ShrinkError, bronze.DuplicateKeyError,
            massive.MassiveResponseError, fred.FredResponseError,
            nasdaq_symdir.SymdirParseError, sp500_membership.MembershipParseError)
    return f"{type(exc).__name__}: {exc}" if isinstance(exc, ours) else type(exc).__name__


def run(sources: tuple[str, ...], ctx: Context) -> list[Result]:
    results = []
    for name in sources:
        try:
            results.append(STEPS[name](ctx))
        except Exception as exc:  # isolate sources; report without data values
            results.append(Result(name, "error", detail=_safe_detail(exc)))
    return results


def main(argv: list[str] | None = None, client: HttpClient | None = None,
         now: datetime | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--date", type=date.fromisoformat, help="session date (default: last completed)")
    p.add_argument("--sources", default=",".join(ALL_SOURCES))
    p.add_argument("--data-root", type=Path, default=Path("data"))
    args = p.parse_args(argv)

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    unknown = [s for s in sources if s not in STEPS]
    if unknown:
        p.error(f"unknown sources {unknown}")

    now = now or datetime.now(timezone.utc)
    cal = load_calendar()
    session = args.date or cal.last_completed_session(now)
    today_et = now.astimezone(ET).date()
    holiday = cal.holiday_name(today_et) if today_et.year in cal.years else None
    log.info("session=%s today_et=%s%s", session, today_et,
             f" holiday={holiday}" if holiday else "")

    ctx = Context(client or HttpClient(archive_root=args.data_root), cal, args.data_root,
                  session, now)
    results = run(sources, ctx)
    for r in results:
        log.info("%-18s %-10s rows=%-6d %s", r.source, r.status, r.rows, r.detail)
    failed = [r for r in results if r.status == "error"]
    log.info("done: %d sources, %d failed", len(results), len(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    install_log_redaction()
    sys.exit(main())
