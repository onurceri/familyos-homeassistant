"""Repeat rules."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from familyos import Recurrence

from custom_components.familyos.rules import instance_id, recurrence_from_rrule, rrule_from_recurrence, same_repeat

from .common import occurrence


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


ZONE = ZoneInfo("Europe/Amsterdam")


def test_instance_id_of_a_date_in_its_series_is_its_own_moment() -> None:
    assert instance_id(occurrence(recurring=True), ZONE) == "2026-10-21T09:30:00+02:00"


def test_instance_id_of_a_moved_date_is_when_it_was_due() -> None:
    moved = occurrence(
        "Swimming",
        "2026-10-21T18:00:00+02:00",
        "2026-10-21T19:00:00+02:00",
        series_id="cal_event_2",
        recurrence_key="1792594800000",
    )
    assert instance_id(moved, ZONE) == "2026-10-21T17:00:00+02:00"
    all_day = occurrence(
        "Trip", "2026-10-23", "2026-10-23", all_day=True, series_id="cal_event_2", recurrence_key="2026-10-22"
    )
    assert instance_id(all_day, ZONE) == "2026-10-22"


def test_instance_id_of_a_key_of_another_kind_is_the_moment_shown() -> None:
    odd = occurrence(series_id="cal_event_2", recurrence_key=">1792594800000")
    assert instance_id(odd, ZONE) == "2026-10-21T09:30:00+02:00"


def test_instance_id_of_a_moved_date_is_its_series_recurrence_id_when_the_server_gives_it() -> None:
    moved = occurrence(
        "Swimming",
        "2026-10-21T18:00:00+02:00",
        "2026-10-21T19:00:00+02:00",
        series_id="cal_event_2",
        # The key is not used when the original start is there.
        recurrence_key="1",
        series_recurrence_id="2026-10-21T15:00:00Z",
    )
    assert instance_id(moved, ZONE) == "2026-10-21T17:00:00+02:00"
    all_day = occurrence(
        "Trip", "2026-10-23", "2026-10-23", all_day=True, series_id="cal_event_2", series_recurrence_id="2026-10-22"
    )
    assert instance_id(all_day, ZONE) == "2026-10-22"
