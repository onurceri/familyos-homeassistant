"""Reading and writing repeat rules (RFC 5545 text) the way FamilyOS repeats things."""

import datetime as dt

from familyos import Recurrence

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
