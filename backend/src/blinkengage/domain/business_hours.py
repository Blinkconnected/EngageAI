"""Business-hours-aware SLA deadline calculation — pure Python, no
persistence or framework dependency (same reasoning as ``domain/rbac.py``
and ``domain/company_settings.py``).

Deliberately its own module rather than more functions on
``domain/company_settings.py``: those are single-key boolean readers off
a flat dict; this module does real datetime arithmetic (timezone
conversion, weekday schedule lookup, holiday exclusion) that needs its
own normalized intermediate representation (``BusinessHoursSchedule``)
built once via ``resolve_schedule`` rather than re-parsed on every call.

See ``docs/architecture/sla.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DEFAULT_TIMEZONE = "UTC"

# Hard safety cap on how many calendar days add_business_minutes() will
# walk forward looking for open time — a company with business hours
# "enabled" but every single day marked closed (a real, if unusual,
# configuration mistake) must still terminate rather than loop forever.
# ~10 years of days is far beyond any realistic SLA target.
_MAX_DAYS_TO_SEARCH = 3660


@dataclass(frozen=True, slots=True)
class DaySchedule:
    open_time: time
    close_time: time
    closed: bool


@dataclass(frozen=True, slots=True)
class BusinessHoursSchedule:
    """Normalized, ready-to-calculate-with view of a company's
    ``settings.business_hours`` + ``settings.timezone`` + its current
    ``Holiday`` rows — built once via ``resolve_schedule`` rather than
    threaded through call sites as raw dicts."""

    enabled: bool
    timezone: ZoneInfo
    days: dict[str, DaySchedule]
    holiday_dates: frozenset[date]
    recurring_holidays: frozenset[tuple[int, int]]  # (month, day) pairs

    def is_holiday(self, day: date) -> bool:
        return day in self.holiday_dates or (day.month, day.day) in self.recurring_holidays

    def day_schedule(self, day: date) -> DaySchedule | None:
        if self.is_holiday(day):
            return None
        return self.days.get(_WEEKDAY_NAMES[day.weekday()])


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def resolve_schedule(
    settings: dict[str, Any],
    *,
    holiday_dates: list[date] | None = None,
    recurring_holidays: list[tuple[int, int]] | None = None,
) -> BusinessHoursSchedule:
    """Builds a ``BusinessHoursSchedule`` from a ``Company.settings``
    dict plus that company's current ``Holiday`` rows (split into fixed
    dates and (month, day) recurring pairs by the caller — this module
    has no repository access, matching the rest of ``domain/``).

    Tolerant of a completely absent/malformed ``business_hours`` section
    (defaults to disabled) for the same reason
    ``domain.company_settings``'s readers are: a row written before this
    feature existed must still resolve safely.
    """
    business_hours = settings.get("business_hours")
    business_hours = business_hours if isinstance(business_hours, dict) else {}
    enabled = bool(business_hours.get("enabled", False))

    timezone_name = settings.get("timezone")
    timezone = ZoneInfo(timezone_name if isinstance(timezone_name, str) else _DEFAULT_TIMEZONE)

    raw_schedule = business_hours.get("schedule")
    raw_schedule = raw_schedule if isinstance(raw_schedule, dict) else {}
    days: dict[str, DaySchedule] = {}
    for day_name in _WEEKDAY_NAMES:
        raw_day = raw_schedule.get(day_name)
        raw_day = raw_day if isinstance(raw_day, dict) else {}
        closed = bool(raw_day.get("closed", False))
        days[day_name] = DaySchedule(
            open_time=_parse_hhmm(raw_day.get("open", "09:00")),
            close_time=_parse_hhmm(raw_day.get("close", "17:00")),
            closed=closed,
        )

    return BusinessHoursSchedule(
        enabled=enabled,
        timezone=timezone,
        days=days,
        holiday_dates=frozenset(holiday_dates or ()),
        recurring_holidays=frozenset(recurring_holidays or ()),
    )


def is_within_business_hours(moment: datetime, schedule: BusinessHoursSchedule) -> bool:
    """``True`` unconditionally when business hours aren't enabled —
    "not enforced" means every moment counts as open, not that none do."""
    if not schedule.enabled:
        return True
    local = moment.astimezone(schedule.timezone)
    day = schedule.day_schedule(local.date())
    if day is None or day.closed:
        return False
    return day.open_time <= local.time() < day.close_time


def _start_of_next_day(moment: datetime) -> datetime:
    return datetime.combine(moment.date() + timedelta(days=1), time.min, tzinfo=moment.tzinfo)


def add_business_minutes(
    start: datetime, minutes: int, schedule: BusinessHoursSchedule
) -> datetime:
    """The moment ``minutes`` of *business* time after ``start`` —
    skipping closed weekdays, holidays, and outside-hours gaps entirely.
    A conversation created at 11pm Friday with a 60-minute target and
    9-5 weekday hours deadlines at 10am Monday, not midnight Friday.

    Equivalent to plain ``start + timedelta(minutes=minutes)`` when
    business hours aren't enabled — every moment is "open," so there is
    nothing to skip.

    ``start`` may fall outside business hours itself (e.g. a
    conversation created overnight) — the first partial day is clipped
    forward to that day's own open time before spending any of
    ``minutes``, exactly as if the clock only started ticking once the
    business day began.
    """
    if not schedule.enabled:
        return start + timedelta(minutes=minutes)

    remaining = timedelta(minutes=minutes)
    cursor = start.astimezone(schedule.timezone)

    for _ in range(_MAX_DAYS_TO_SEARCH):
        day = schedule.day_schedule(cursor.date())
        if day is None or day.closed:
            cursor = _start_of_next_day(cursor)
            continue

        day_open = datetime.combine(cursor.date(), day.open_time, tzinfo=schedule.timezone)
        day_close = datetime.combine(cursor.date(), day.close_time, tzinfo=schedule.timezone)
        if cursor < day_open:
            cursor = day_open
        if cursor >= day_close:
            cursor = _start_of_next_day(cursor)
            continue

        available_today = day_close - cursor
        if remaining <= available_today:
            return (cursor + remaining).astimezone(start.tzinfo)
        remaining -= available_today
        cursor = _start_of_next_day(cursor)

    raise RuntimeError(
        "add_business_minutes: no open business hours found within "
        f"{_MAX_DAYS_TO_SEARCH} days — check that at least one weekday isn't closed"
    )
