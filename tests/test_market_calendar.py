from datetime import date, datetime, time, timezone

import pytest

from config.market_calendar import CalendarRangeError, load_calendar, parse_calendar

CAL = load_calendar()


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_weekends_and_holidays_closed():
    assert not CAL.is_session(date(2026, 10, 3))            # Saturday
    assert not CAL.is_session(date(2026, 11, 26))           # Thanksgiving
    assert not CAL.is_session(date(2026, 7, 3))             # Independence Day observed
    assert CAL.holiday_name(date(2027, 12, 24)) == "Christmas Day (observed)"
    assert CAL.is_session(date(2026, 9, 30))
    assert CAL.is_session(date(2028, 1, 3))                 # no New Year observed in 2028


def test_early_close():
    assert CAL.close_time(date(2026, 11, 27)) == time(13, 0)
    assert CAL.close_time(date(2026, 9, 30)) == time(16, 0)
    with pytest.raises(ValueError):
        CAL.close_time(date(2026, 11, 26))


def test_close_utc_handles_dst():
    assert CAL.close_utc(date(2026, 9, 30)) == utc(2026, 9, 30, 20)   # EDT
    assert CAL.close_utc(date(2026, 12, 1)) == utc(2026, 12, 1, 21)   # EST


def test_previous_and_next_session():
    assert CAL.previous_session(date(2026, 11, 27)) == date(2026, 11, 25)
    assert CAL.next_session(date(2026, 11, 25)) == date(2026, 11, 27)
    assert CAL.previous_session(date(2026, 9, 8)) == date(2026, 9, 4)  # Labor Day Monday


def test_last_completed_session():
    assert CAL.last_completed_session(utc(2026, 9, 30, 23, 30)) == date(2026, 9, 30)
    assert CAL.last_completed_session(utc(2026, 9, 30, 19, 59)) == date(2026, 9, 29)
    assert CAL.last_completed_session(utc(2026, 10, 1, 11)) == date(2026, 9, 30)  # retry cron
    assert CAL.last_completed_session(utc(2026, 11, 26, 23, 30)) == date(2026, 11, 25)
    assert CAL.last_completed_session(utc(2026, 11, 27, 18, 30)) == date(2026, 11, 27)
    with pytest.raises(ValueError):
        CAL.last_completed_session(datetime(2026, 9, 30, 23))


def test_uncovered_year_fails_closed():
    with pytest.raises(CalendarRangeError):
        CAL.is_session(date(2025, 12, 31))
    with pytest.raises(CalendarRangeError):
        CAL.previous_session(date(2026, 1, 2))  # walks into 2025


def test_sessions_count_2026():
    assert len(CAL.sessions(date(2026, 1, 1), date(2026, 12, 31))) == 251


@pytest.mark.parametrize("data", [
    {"years": [2026], "holidays": {"2027-01-01": "x"}},
    {"years": [2026], "holidays": {"2026-10-03": "weekend"}},
    {"years": [2026], "holidays": {"2026-11-27": "x"}, "early_closes": {"2026-11-27": "13:00"}},
])
def test_bad_calendar_rejected(data):
    with pytest.raises(ValueError):
        parse_calendar(data)
