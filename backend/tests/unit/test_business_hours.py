from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from blinkengage.domain.business_hours import (
    add_business_minutes,
    is_within_business_hours,
    resolve_schedule,
)

_NINE_TO_FIVE_WEEKDAYS = {
    "monday": {"open": "09:00", "close": "17:00", "closed": False},
    "tuesday": {"open": "09:00", "close": "17:00", "closed": False},
    "wednesday": {"open": "09:00", "close": "17:00", "closed": False},
    "thursday": {"open": "09:00", "close": "17:00", "closed": False},
    "friday": {"open": "09:00", "close": "17:00", "closed": False},
    "saturday": {"open": "09:00", "close": "17:00", "closed": True},
    "sunday": {"open": "09:00", "close": "17:00", "closed": True},
}


def _settings(*, enabled: bool = True, timezone: str = "UTC") -> dict:
    return {
        "timezone": timezone,
        "business_hours": {"enabled": enabled, "schedule": _NINE_TO_FIVE_WEEKDAYS},
    }


def test_disabled_business_hours_is_always_within_hours() -> None:
    schedule = resolve_schedule(_settings(enabled=False))
    midnight_saturday = datetime(2026, 1, 3, 0, 0, tzinfo=UTC)  # a Saturday
    assert is_within_business_hours(midnight_saturday, schedule) is True


def test_within_business_hours_on_an_open_weekday() -> None:
    schedule = resolve_schedule(_settings())
    monday_noon = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)  # a Monday
    assert is_within_business_hours(monday_noon, schedule) is True


def test_outside_business_hours_before_open_and_after_close() -> None:
    schedule = resolve_schedule(_settings())
    before_open = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    after_close = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)  # close is exclusive
    assert is_within_business_hours(before_open, schedule) is False
    assert is_within_business_hours(after_close, schedule) is False


def test_closed_weekday_is_never_within_hours() -> None:
    schedule = resolve_schedule(_settings())
    saturday_noon = datetime(2026, 1, 3, 12, 0, tzinfo=UTC)
    assert is_within_business_hours(saturday_noon, schedule) is False


def test_fixed_holiday_overrides_an_otherwise_open_weekday() -> None:
    schedule = resolve_schedule(_settings(), holiday_dates=[datetime(2026, 1, 5).date()])
    monday_noon = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    assert is_within_business_hours(monday_noon, schedule) is False


def test_recurring_holiday_matches_month_and_day_regardless_of_year() -> None:
    # New Year's Day, recurring, falls on a Thursday in 2026 (an
    # otherwise-open weekday per the fixture schedule).
    schedule = resolve_schedule(_settings(), recurring_holidays=[(1, 1)])
    new_years_2026 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    new_years_2027 = datetime(2027, 1, 1, 12, 0, tzinfo=UTC)
    assert is_within_business_hours(new_years_2026, schedule) is False
    assert is_within_business_hours(new_years_2027, schedule) is False


def test_add_business_minutes_disabled_is_plain_wall_clock() -> None:
    schedule = resolve_schedule(_settings(enabled=False))
    start = datetime(2026, 1, 3, 23, 0, tzinfo=UTC)  # Saturday night
    deadline = add_business_minutes(start, 60, schedule)
    assert deadline == datetime(2026, 1, 4, 0, 0, tzinfo=UTC)


def test_add_business_minutes_completes_within_the_same_day() -> None:
    schedule = resolve_schedule(_settings())
    start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)  # Monday 10am
    deadline = add_business_minutes(start, 60, schedule)
    assert deadline == datetime(2026, 1, 5, 11, 0, tzinfo=UTC)


def test_add_business_minutes_clips_a_start_before_open_to_that_days_open_time() -> None:
    schedule = resolve_schedule(_settings())
    start = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)  # Monday 3am, before 9am open
    deadline = add_business_minutes(start, 30, schedule)
    assert deadline == datetime(2026, 1, 5, 9, 30, tzinfo=UTC)


def test_add_business_minutes_skips_the_weekend() -> None:
    schedule = resolve_schedule(_settings())
    start = datetime(2026, 1, 9, 16, 30, tzinfo=UTC)  # Friday 4:30pm, 30 min before close
    deadline = add_business_minutes(start, 60, schedule)
    # 30 minutes left Friday + 30 minutes into Monday's 9am open.
    assert deadline == datetime(2026, 1, 12, 9, 30, tzinfo=UTC)


def test_add_business_minutes_skips_a_holiday() -> None:
    # Monday 2026-01-05 is a fixed holiday; a target starting Friday
    # afternoon that would otherwise land on Monday must skip to Tuesday.
    schedule = resolve_schedule(_settings(), holiday_dates=[datetime(2026, 1, 5).date()])
    start = datetime(2026, 1, 2, 16, 30, tzinfo=UTC)  # Friday 4:30pm
    deadline = add_business_minutes(start, 60, schedule)
    assert deadline == datetime(2026, 1, 6, 9, 30, tzinfo=UTC)  # Tuesday


def test_add_business_minutes_is_timezone_aware() -> None:
    # 11pm UTC Monday is already Tuesday 10am in Sydney (AEDT, UTC+11 in
    # January) — well within that day's business hours, so the deadline
    # is same-day in local time even though it's still "Monday" in UTC.
    schedule = resolve_schedule(_settings(timezone="Australia/Sydney"))
    start = datetime(2026, 1, 5, 23, 0, tzinfo=UTC)
    deadline = add_business_minutes(start, 30, schedule)
    assert deadline.astimezone(ZoneInfo("Australia/Sydney")) == datetime(
        2026, 1, 6, 10, 30, tzinfo=ZoneInfo("Australia/Sydney")
    )


def test_add_business_minutes_raises_if_every_day_is_closed() -> None:
    all_closed = {
        day: {"open": "09:00", "close": "17:00", "closed": True} for day in _NINE_TO_FIVE_WEEKDAYS
    }
    schedule = resolve_schedule(
        {"timezone": "UTC", "business_hours": {"enabled": True, "schedule": all_closed}}
    )
    with pytest.raises(RuntimeError):
        add_business_minutes(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), 30, schedule)
