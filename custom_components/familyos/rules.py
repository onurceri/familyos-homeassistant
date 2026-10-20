"""Reading and writing repeat rules (RFC 5545 text) the way FamilyOS repeats things."""

import datetime as dt
from zoneinfo import ZoneInfo

from familyos import Occurrence, Recurrence

_FREQUENCIES = {"DAILY": "daily", "WEEKLY": "weekly", "MONTHLY": "monthly"}
_WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}


def recurrence_from_rrule(rule: str) -> Recurrence:
    """FamilyOS' repeat for an RRULE; ValueError when FamilyOS cannot repeat that way."""
    parts: dict[str, str] = {}
    for piece in rule.removeprefix("RRULE:").split(";"):
        name, separator, value = piece.partition("=")
        if not separator or not value:
            raise ValueError(rule)
        parts[name.upper()] = value
    if set(parts) - {"FREQ", "INTERVAL", "BYDAY", "UNTIL"}:
        raise ValueError(rule)
    freq = _FREQUENCIES.get(parts.get("FREQ", ""))
    if freq is None:
        raise ValueError(rule)
    interval = int(parts["INTERVAL"]) if "INTERVAL" in parts else 1
    if interval < 1:
        raise ValueError(rule)
    by_day: list[str] | None = None
    if "BYDAY" in parts:
        by_day = parts["BYDAY"].upper().split(",")
        if freq != "weekly" or not set(by_day) <= _WEEKDAYS:
            raise ValueError(rule)
    until: dt.date | None = None
    if "UNTIL" in parts:
        text = parts["UNTIL"][:8]
        try:
            until = dt.datetime.strptime(text, "%Y%m%d").date()
        except ValueError as err:
            raise ValueError(rule) from err
    return Recurrence(freq=freq, interval=interval, by_day=by_day, until=until)


def same_repeat(rule: str, existing: Recurrence | None) -> bool:
    """Whether the RRULE says what the event already repeats as."""
    try:
        wanted = recurrence_from_rrule(rule)
    except ValueError:
        return False
    if existing is None:
        return False
    return (wanted.freq, wanted.interval, wanted.by_day or [], wanted.until) == (
        existing.freq,
        existing.interval,
        existing.by_day or [],
        existing.until,
    )


def rrule_from_recurrence(recurrence: Recurrence) -> str:
    """The RRULE text for a FamilyOS repeat (the API gives the structure; Home Assistant wants the text)."""
    parts = [f"FREQ={recurrence.freq.upper()}"]
    if recurrence.interval != 1:
        parts.append(f"INTERVAL={recurrence.interval}")
    if recurrence.by_day:
        parts.append("BYDAY=" + ",".join(recurrence.by_day))
    if recurrence.until is not None:
        parts.append("UNTIL=" + recurrence.until.strftime("%Y%m%d"))
    return ";".join(parts)


def instance_id(occurrence: Occurrence, zone: ZoneInfo) -> str:
    """The name of a date within its series: the moment (or day) it was first due.

    A date moved out of a series reports its new moment as ``recurrence_id``; the one it was due is its
    ``recurrence_key`` (epoch milliseconds, or a day for an all-day event).
    """
    key = occurrence.recurrence_key
    if occurrence.series_id and key:
        if key.isdecimal():
            return dt.datetime.fromtimestamp(int(key) / 1000, zone).isoformat()
        try:
            return dt.date.fromisoformat(key).isoformat()
        except ValueError:
            pass  # a key of another kind (a subscription's): the date keeps the moment it shows
    return occurrence.recurrence_id.isoformat()
