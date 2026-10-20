"""Repeat rules."""

import datetime as dt

import pytest
from familyos import Recurrence

from custom_components.familyos.rules import recurrence_from_rrule, rrule_from_recurrence, same_repeat


def test_weekly_rule() -> None:
    rule = recurrence_from_rrule("RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;UNTIL=20261231T000000Z")
    assert rule == Recurrence(freq="weekly", interval=2, by_day=["MO", "WE"], until=dt.date(2026, 12, 31))
    assert rrule_from_recurrence(rule) == "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;UNTIL=20261231"


@pytest.mark.parametrize(
    "rule",
    [
        "FREQ=YEARLY",
        "FREQ=DAILY;COUNT=3",
        "FREQ=DAILY;BYDAY=MO",
        "FREQ=WEEKLY;BYDAY=XX",
        "FREQ=DAILY;INTERVAL=0",
        "FREQ=DAILY;UNTIL=soon",
        "FREQ",
        "INTERVAL=2",
    ],
)
def test_rules_family_os_cannot_repeat(rule: str) -> None:
    with pytest.raises(ValueError, match=rule.split(";")[0]):
        recurrence_from_rrule(rule)


def test_same_repeat() -> None:
    weekly = Recurrence(freq="weekly", interval=1, by_day=["MO"])
    assert same_repeat("FREQ=WEEKLY;BYDAY=MO", weekly)
    assert not same_repeat("FREQ=WEEKLY;BYDAY=TU", weekly)
    assert not same_repeat("FREQ=WEEKLY", None)
    assert not same_repeat("FREQ=YEARLY", weekly)
