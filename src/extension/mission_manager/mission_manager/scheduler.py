"""Pure date/time rules for robot-side mission schedules."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_utc(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("UTC timestamp is required")
    if parsed.tzinfo is None:
        raise ValueError("UTC timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validated_config(recurrence, timezone_name, local_time, start_date, weekdays):
    if recurrence not in {"once", "daily", "weekly"}:
        raise ValueError("recurrence must be once, daily, or weekly")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("timezone is required")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    try:
        hour, minute = (int(part) for part in local_time.split(":"))
        at_time = time(hour, minute)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("local_time must use HH:MM") from exc
    if len(local_time) != 5 or local_time[2] != ":":
        raise ValueError("local_time must use HH:MM")
    weekdays = sorted(set(weekdays or []))
    if any(not isinstance(day, int) or isinstance(day, bool) or day < 0 or day > 6 for day in weekdays):
        raise ValueError("weekdays must contain weekday numbers from 0 to 6")
    if recurrence == "weekly" and not weekdays:
        raise ValueError("weekly schedules need at least one weekday")
    if recurrence == "once":
        try:
            once_date = date.fromisoformat(start_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("once schedules need start_date in YYYY-MM-DD format") from exc
    else:
        once_date = None
    return zone, at_time, once_date, weekdays


def next_run_at(now, recurrence, timezone_name, local_time, start_date=None, weekdays=None):
    """Return next UTC run time. Nonexistent DST wall times are skipped; folds use the first occurrence."""
    now_utc = parse_utc(now)
    zone, at_time, once_date, weekdays = _validated_config(
        recurrence, timezone_name, local_time, start_date, weekdays
    )
    local_now = now_utc.astimezone(zone)
    first_day = once_date if recurrence == "once" else local_now.date()
    search_days = 1 if recurrence == "once" else 8
    for offset in range(search_days):
        candidate_day = first_day + timedelta(days=offset)
        if recurrence == "weekly" and candidate_day.weekday() not in weekdays:
            continue
        wall_time = datetime.combine(candidate_day, at_time)
        # fold=0 selects the first instant when a wall time repeats in autumn.
        candidate = wall_time.replace(tzinfo=zone, fold=0)
        candidate_utc = candidate.astimezone(timezone.utc)
        # Round-trip detects local wall times skipped by a spring DST transition.
        if candidate_utc.astimezone(zone).replace(tzinfo=None) != wall_time:
            continue
        if candidate_utc > now_utc:
            return candidate_utc.isoformat()
    return None
