"""NYSE sessions, holidays and early closes.

Loaded from configs/nyse_calendar.yaml. Fails closed: asking about a year the file does
not cover raises CalendarRangeError instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ET = ZoneInfo("America/New_York")
REGULAR_CLOSE = time(16, 0)
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "configs" / "nyse_calendar.yaml"


class CalendarRangeError(LookupError):
    """The date is outside the years the calendar file covers."""


@dataclass(frozen=True)
class MarketCalendar:
    years: frozenset[int]
    holidays: dict[date, str]
    early_closes: dict[date, time]

    def _check(self, d: date) -> None:
        if d.year not in self.years:
            raise CalendarRangeError(f"calendar does not cover {d.year}")

    def is_session(self, d: date) -> bool:
        self._check(d)
        return d.weekday() < 5 and d not in self.holidays

    def holiday_name(self, d: date) -> str | None:
        self._check(d)
        return self.holidays.get(d)

    def close_time(self, d: date) -> time:
        """Session close in ET. Raises ValueError if d is not a session."""
        if not self.is_session(d):
            raise ValueError(f"{d} is not a session")
        return self.early_closes.get(d, REGULAR_CLOSE)

    def close_utc(self, d: date) -> datetime:
        return datetime.combine(d, self.close_time(d), ET).astimezone(timezone.utc)

    def previous_session(self, d: date) -> date:
        """Latest session strictly before d."""
        cur = d - timedelta(days=1)
        while not self.is_session(cur):
            cur -= timedelta(days=1)
        return cur

    def next_session(self, d: date) -> date:
        """Earliest session strictly after d."""
        cur = d + timedelta(days=1)
        while not self.is_session(cur):
            cur += timedelta(days=1)
        return cur

    def last_completed_session(self, now: datetime) -> date:
        """Latest session whose close is at or before now (tz-aware)."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        today = now.astimezone(ET).date()
        if self.is_session(today) and now >= self.close_utc(today):
            return today
        return self.previous_session(today)

    def sessions(self, start: date, end: date) -> list[date]:
        """All sessions in [start, end]."""
        out, cur = [], start
        while cur <= end:
            if self.is_session(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def parse_calendar(data: dict) -> MarketCalendar:
    years = frozenset(int(y) for y in data["years"])
    holidays = {_as_date(k): str(v) for k, v in (data.get("holidays") or {}).items()}
    early = {_as_date(k): time.fromisoformat(str(v)) for k, v in (data.get("early_closes") or {}).items()}
    for d in list(holidays) + list(early):
        if d.year not in years:
            raise ValueError(f"calendar entry {d} outside declared years")
        if d.weekday() >= 5:
            raise ValueError(f"calendar entry {d} falls on a weekend")
    overlap = set(holidays) & set(early)
    if overlap:
        raise ValueError(f"{len(overlap)} dates are both holiday and early close")
    return MarketCalendar(years, holidays, early)


def load_calendar(path: Path | str = DEFAULT_PATH) -> MarketCalendar:
    with open(path, encoding="utf-8") as f:
        return parse_calendar(yaml.safe_load(f))
