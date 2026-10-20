"""The calendar entity: reading, adding, changing and deleting events (and one date of a series)."""

import datetime as dt
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from familyos import ForbiddenError, Recurrence
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator, WebSocketGenerator

from .common import changes, drafted, event, occurrence

CALENDAR = "calendar.familyos_calendar"


async def _events(hass_client: ClientSessionGenerator, start: str, end: str) -> list[dict[str, Any]]:
    http = await hass_client()
    response = await http.get(f"/api/calendars/{CALENDAR}?start={start}&end={end}")
    assert response.status == 200
    return cast(list[dict[str, Any]], await response.json())


async def test_state_is_the_event_on_now(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    state = hass.states.get(CALENDAR)
    # 10:00 in Amsterdam: nothing is on, the dentist comes tomorrow morning.
    assert state is not None
    assert state.state == "off"
    assert state.attributes["message"] == "Swimming"
    assert state.attributes["start_time"] == "2026-10-20 17:00:00"


async def test_get_events(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.get_event = AsyncMock(return_value=event(recurrence={"freq": "weekly", "interval": 1, "byDay": ["MO"]}))
    found = await _events(hass_client, "2026-10-20T00:00:00Z", "2026-10-30T00:00:00Z")
    by_title = {e["summary"]: e for e in found}
    assert set(by_title) == {"Dentist", "Swimming", "Trip"}

    swimming = by_title["Swimming"]
    assert swimming["uid"] == "cal_event_2"
    assert swimming["recurrence_id"] == "2026-10-20T17:00:00+02:00"
    assert swimming["rrule"] == "FREQ=WEEKLY;BYDAY=MO"
    assert by_title["Dentist"]["recurrence_id"] is None
    # FamilyOS ends an all-day event on its last day, Home Assistant the day after.
    assert by_title["Trip"]["start"] == {"date": "2026-10-22"}
    assert by_title["Trip"]["end"] == {"date": "2026-10-24"}
    assert by_title["Dentist"]["start"] == {"dateTime": "2026-10-21T09:30:00+02:00"}

    args = client.iter_occurrences.calls
    assert args == 2  # once for the state, once for this window


async def test_window_in_the_family_zone(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.iter_occurrences.items[:] = [
        occurrence("Late call", "2026-10-21T23:30:00+02:00", "2026-10-22T00:30:00+02:00")
    ]
    # 22:30 UTC on the 21st is 00:30 on the 22nd in Amsterdam; the event overlaps it.
    found = await _events(hass_client, "2026-10-21T22:00:00Z", "2026-10-21T23:00:00Z")
    assert [e["summary"] for e in found] == ["Late call"]
    found = await _events(hass_client, "2026-10-22T05:00:00Z", "2026-10-22T06:00:00Z")
    assert found == []


async def test_create_timed_event(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": CALENDAR,
            "summary": "Piano",
            "start_date_time": "2026-10-22 16:00:00",
            "end_date_time": "2026-10-22 17:00:00",
            "location": "Music school",
            "description": "Bring books",
        },
        blocking=True,
    )
    client.create_event.assert_awaited_once()
    args, kwargs = client.create_event.await_args
    assert args == ("Piano", dt.date(2026, 10, 22))
    assert kwargs == {
        "location": "Music school",
        "notes": "Bring books",
        "recurrence": None,
        "all_day": False,
        "end_date": None,
        "start_time": dt.time(16, 0),
        "end_time": dt.time(17, 0),
    }


async def test_create_all_day_event_and_series(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    await hass.services.async_call(
        "calendar",
        "create_event",
        {"entity_id": CALENDAR, "summary": "Holiday", "start_date": "2026-10-22", "end_date": "2026-10-25"},
        blocking=True,
    )
    _, kwargs = client.create_event.await_args
    assert kwargs["all_day"] is True
    assert kwargs["end_date"] == dt.date(2026, 10, 24)
    assert kwargs["start_time"] is None and kwargs["end_time"] is None

    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(
        {
            "type": "calendar/event/create",
            "entity_id": CALENDAR,
            "event": {
                "summary": "Gym",
                "dtstart": "2026-10-22 07:00:00",
                "dtend": "2026-10-22 08:00:00",
                "rrule": "FREQ=WEEKLY;BYDAY=MO,WE",
            },
        }
    )
    assert (await ws.receive_json())["success"]
    _, kwargs = client.create_event.await_args
    assert kwargs["recurrence"] == Recurrence(freq="weekly", interval=1, by_day=["MO", "WE"], until=None)

    await ws.send_json_auto_id(
        {
            "type": "calendar/event/create",
            "entity_id": CALENDAR,
            "event": {
                "summary": "Gym",
                "dtstart": "2026-10-22 07:00:00",
                "dtend": "2026-10-22 08:00:00",
                "rrule": "FREQ=YEARLY",
            },
        }
    )
    assert not (await ws.receive_json())["success"]


async def _update(ws: object, uid: str, event: dict[str, object], **extra: object) -> dict[str, object]:
    await ws.send_json_auto_id(  # type: ignore[attr-defined]
        {"type": "calendar/event/update", "entity_id": CALENDAR, "uid": uid, "event": event, **extra}
    )
    return await ws.receive_json()  # type: ignore[no-any-return, attr-defined]


async def test_update_whole_event_sends_only_what_changed(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    client.get_event = AsyncMock(
        return_value=event(recurrence={"freq": "weekly", "interval": 1, "byDay": ["MO"]}, version=7)
    )
    ws = await hass_ws_client(hass)
    answer = await _update(
        ws,
        "cal_event_1",
        {
            "summary": "Gym!",
            "dtstart": "2026-10-22 07:00:00",
            "dtend": "2026-10-22 08:00:00",
            "location": "",
            "rrule": "FREQ=WEEKLY;BYDAY=MO",
        },
    )
    assert answer["success"]
    client.patch_event.assert_awaited_once_with("cal_event_1", occurrence=None, if_match=7, title="Gym!", location=None)


async def test_update_time_and_all_day(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    ws = await hass_ws_client(hass)
    assert (
        await _update(
            ws, "cal_event_1", {"summary": "Gym", "dtstart": "2026-10-22 09:00:00", "dtend": "2026-10-23 08:00:00"}
        )
    )["success"]
    _, kwargs = client.patch_event.await_args
    assert kwargs["start_time"] == dt.time(9, 0)
    assert kwargs["end_date"] == dt.date(2026, 10, 23)
    assert "all_day" not in kwargs and "date" not in kwargs

    assert (await _update(ws, "cal_event_1", {"summary": "Gym", "dtstart": "2026-10-22", "dtend": "2026-10-23"}))[
        "success"
    ]
    _, kwargs = client.patch_event.await_args
    assert kwargs["all_day"] is True
    assert kwargs["end_time"] is None and "start_time" not in kwargs


async def test_update_one_date_of_a_series(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    client.get_event = AsyncMock(return_value=event(recurrence={"freq": "daily", "interval": 1}, version=2))
    ws = await hass_ws_client(hass)
    answer = await _update(
        ws,
        "cal_event_2",
        {"summary": "Swimming late", "dtstart": "2026-10-21 18:00:00", "dtend": "2026-10-21 19:00:00"},
        recurrence_id="2026-10-21T17:00:00+02:00",
        recurrence_range="",
    )
    assert answer["success"]
    _, kwargs = client.patch_event.await_args
    assert kwargs["occurrence"] == "2026-10-21T17:00:00+02:00"
    # A date that moves needs all of its fields, even the ones the series already has.
    assert kwargs["date"] == dt.date(2026, 10, 21)
    assert kwargs["start_time"] == dt.time(18, 0)
    assert kwargs["end_time"] == dt.time(19, 0)
    assert kwargs["title"] == "Swimming late"


async def test_update_refuses_what_family_os_cannot_do_from_here(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    client.get_event = AsyncMock(return_value=event(recurrence={"freq": "daily", "interval": 1}))
    ws = await hass_ws_client(hass)
    changed_rule = await _update(
        ws,
        "cal_event_1",
        {"summary": "x", "dtstart": "2026-10-22 07:00:00", "dtend": "2026-10-22 08:00:00", "rrule": "FREQ=WEEKLY"},
    )
    assert not changed_rule["success"]
    assert "how an event repeats" in changed_rule["error"]["message"]

    following = await _update(
        ws,
        "cal_event_1",
        {"summary": "x", "dtstart": "2026-10-22 07:00:00", "dtend": "2026-10-22 08:00:00"},
        recurrence_id="2026-10-21",
        recurrence_range="THIS_AND_FUTURE",
    )
    assert not following["success"]
    assert "this and following" in following["error"]["message"]
    client.patch_event.assert_not_awaited()


async def test_delete_event_and_one_date(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id({"type": "calendar/event/delete", "entity_id": CALENDAR, "uid": "cal_event_1"})
    assert (await ws.receive_json())["success"]
    client.delete_event.assert_awaited_with("cal_event_1", occurrence=None)

    await ws.send_json_auto_id(
        {
            "type": "calendar/event/delete",
            "entity_id": CALENDAR,
            "uid": "cal_event_2",
            "recurrence_id": "2026-10-21T17:00:00+02:00",
            "recurrence_range": "",
        }
    )
    assert (await ws.receive_json())["success"]
    client.delete_event.assert_awaited_with("cal_event_2", occurrence="2026-10-21T17:00:00+02:00")

    await ws.send_json_auto_id(
        {
            "type": "calendar/event/delete",
            "entity_id": CALENDAR,
            "uid": "cal_event_2",
            "recurrence_id": "2026-10-21T17:00:00+02:00",
            "recurrence_range": "THIS_AND_FUTURE",
        }
    )
    assert not (await ws.receive_json())["success"]


async def test_drafted_event_waits_for_approval(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.create_event = AsyncMock(return_value=drafted("draft_9"))
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": CALENDAR,
            "summary": "Piano",
            "start_date_time": "2026-10-22 16:00:00",
            "end_date_time": "2026-10-22 17:00:00",
        },
        blocking=True,
    )
    notices = hass.data["persistent_notification"]
    assert notices["familyos_draft_draft_9"]["message"] == "Waiting for approval in FamilyOS: Piano"


async def test_write_errors_are_told(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.create_event = AsyncMock(side_effect=ForbiddenError("no calendar for you", status=403, reason="capability"))
    with pytest.raises(HomeAssistantError, match="does not allow"):
        await hass.services.async_call(
            "calendar",
            "create_event",
            {
                "entity_id": CALENDAR,
                "summary": "x",
                "start_date_time": "2026-10-22 16:00:00",
                "end_date_time": "2026-10-22 17:00:00",
            },
            blocking=True,
        )


# 17:00 on the 21st in Amsterdam, in epoch milliseconds: when the moved date was first due.
MOVED_KEY = "2026-10-21T17:00:00+02:00"
MOVED_MS = "1792594800000"


def _moved_date(client: MagicMock) -> None:
    """Swimming on the 21st was moved to 18:00 and is an event of its own, cal_event_9."""
    client.iter_occurrences.items.append(
        occurrence(
            "Swimming",
            "2026-10-21T18:00:00+02:00",
            "2026-10-21T19:00:00+02:00",
            event_id="cal_event_9",
            # FamilyOS names a moved date by its new moment; the one it was due is the key.
            recurrence_id="2026-10-21T18:00:00+02:00",
            recurrence_key=MOVED_MS,
            series_id="cal_event_2",
        )
    )


async def test_a_moved_date_shows_as_an_instance_of_its_series(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    _moved_date(client)
    client.get_event = AsyncMock(return_value=event(recurrence={"freq": "daily", "interval": 1}))
    found = await _events(hass_client, "2026-10-21T00:00:00Z", "2026-10-22T00:00:00Z")
    moved = next(e for e in found if e["start"] == {"dateTime": "2026-10-21T18:00:00+02:00"})
    assert moved["uid"] == "cal_event_2"
    assert moved["recurrence_id"] == MOVED_KEY
    assert moved["rrule"] == "FREQ=DAILY"
    # The rule is the series', read once.
    client.get_event.assert_awaited_once_with("cal_event_2")


async def test_a_moved_date_is_changed_as_the_event_it_is_in_family_os(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    _moved_date(client)
    client.changes = AsyncMock(return_value=changes(("calendar", "cal_event_9"), cursor=2))
    await entry.runtime_data.async_refresh()
    client.get_event = AsyncMock(return_value=event(id="cal_event_9", version=4, date="2026-10-21"))
    ws = await hass_ws_client(hass)
    answer = await _update(
        ws,
        "cal_event_2",
        {"summary": "Swimming (late)", "dtstart": "2026-10-21 18:30:00", "dtend": "2026-10-21 19:30:00"},
        recurrence_id=MOVED_KEY,
        recurrence_range="",
    )
    assert answer["success"]
    client.get_event.assert_awaited_with("cal_event_9")
    args, kwargs = client.patch_event.await_args
    assert args == ("cal_event_9",)
    assert kwargs["occurrence"] is None
    assert kwargs["if_match"] == 4
    assert kwargs["title"] == "Swimming (late)"
    assert kwargs["start_time"] == dt.time(18, 30)


async def test_a_moved_date_is_deleted_as_the_event_it_is_in_family_os(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, hass_ws_client: WebSocketGenerator
) -> None:
    _moved_date(client)
    client.changes = AsyncMock(return_value=changes(("calendar", "cal_event_9"), cursor=2))
    await entry.runtime_data.async_refresh()
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(
        {
            "type": "calendar/event/delete",
            "entity_id": CALENDAR,
            "uid": "cal_event_2",
            "recurrence_id": MOVED_KEY,
            "recurrence_range": "",
        }
    )
    assert (await ws.receive_json())["success"]
    client.delete_event.assert_awaited_with("cal_event_9", occurrence=None)
