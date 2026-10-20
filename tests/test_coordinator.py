"""The coordinator: what it reads when, and how it fails."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from familyos import AuthenticationError, ConnectionError, CursorExpired, FamilyOSError, RateLimited
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from .common import changes, discovery, make_entry

READS = ("iter_occurrences", "iter_shopping_lists", "iter_shopping_items", "iter_tasks", "iter_chores")


def _calls(client: MagicMock) -> dict[str, int]:
    return {name: getattr(client, name).calls for name in READS}


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry) -> None:
    freezer.tick(entry.runtime_data.update_interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_first_refresh_reads_everything_once(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    assert entry.state is ConfigEntryState.LOADED
    assert _calls(client) == dict.fromkeys(READS, 1)
    data = entry.runtime_data.data
    assert [o.title for o in data.occurrences] == ["Dentist", "Swimming", "Trip"]
    assert data.today == dt.date(2026, 10, 20)
    assert data.features == {"calendar", "shopping", "tasks", "chores", "board"}


async def test_nothing_changed_reads_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    await _poll(hass, freezer, entry)
    await _poll(hass, freezer, entry)
    assert _calls(client) == dict.fromkeys(READS, 1)
    assert client.changes.await_args_list[-1].args == (1,)


async def test_only_what_changed_is_read_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.changes = AsyncMock(return_value=changes(("chores", "chore_1"), cursor=2))
    await _poll(hass, freezer, entry)
    calls = _calls(client)
    assert calls["iter_chores"] == 2
    assert calls["iter_occurrences"] == calls["iter_tasks"] == calls["iter_shopping_lists"] == 1

    client.changes = AsyncMock(return_value=changes(("lists", "task_1"), ("calendar", "cal_event_1"), cursor=3))
    await _poll(hass, freezer, entry)
    calls = _calls(client)
    assert calls["iter_chores"] == 2
    assert calls["iter_occurrences"] == calls["iter_tasks"] == calls["iter_shopping_lists"] == 2
    assert client.changes.await_args_list[-1].args == (2,)


async def test_follows_more_changes_at_once(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.changes = AsyncMock(
        side_effect=[changes(("chores", "c"), cursor=5, more=True), changes(("board", "b"), cursor=9)]
    )
    await _poll(hass, freezer, entry)
    assert [c.args for c in client.changes.await_args_list] == [(1,), (5,)]
    assert entry.runtime_data._cursor == 9
    assert _calls(client)["iter_chores"] == 2


async def test_expired_cursor_reads_everything_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.changes = AsyncMock(side_effect=[CursorExpired("gone", status=410), changes(cursor=40)])
    await _poll(hass, freezer, entry)
    assert _calls(client) == dict.fromkeys(READS, 2)
    assert entry.runtime_data._cursor == 40


async def test_a_new_day_reads_the_date_bound_lists(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    freezer.tick(dt.timedelta(days=1))
    await _poll(hass, freezer, entry)
    calls = _calls(client)
    assert calls["iter_occurrences"] == calls["iter_chores"] == 2
    assert calls["iter_tasks"] == 1
    assert entry.runtime_data.data.today == dt.date(2026, 10, 21)


async def test_rate_limit_backs_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    coordinator = entry.runtime_data
    client.discover = AsyncMock(side_effect=RateLimited("slow down", retry_after=120, status=429))
    await _poll(hass, freezer, entry)
    assert not coordinator.last_update_success
    assert client.discover.await_count == 1
    assert hass.states.get("sensor.familyos_chores_overdue").state == "unavailable"

    # The usual 60 seconds are not enough: FamilyOS asked for 120.
    client.discover = AsyncMock(return_value=discovery())
    await _poll(hass, freezer, entry)
    assert client.discover.await_count == 0

    freezer.tick(dt.timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.last_update_success
    assert hass.states.get("sensor.familyos_chores_overdue").state == "1"


@pytest.mark.parametrize("error", [ConnectionError("down"), FamilyOSError("odd", status=500)])
async def test_unreachable_makes_entities_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock, error: Exception
) -> None:
    client.discover = AsyncMock(side_effect=error)
    await _poll(hass, freezer, entry)
    assert not entry.runtime_data.last_update_success
    assert hass.states.get("calendar.familyos_calendar").state == "unavailable"
    assert entry.state is ConfigEntryState.LOADED


async def test_key_refused_starts_reauth(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.discover = AsyncMock(side_effect=AuthenticationError("no", status=401))
    await _poll(hass, freezer, entry)
    flows = hass.config_entries.flow.async_progress_by_handler("familyos")
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_first_refresh_failures(hass: HomeAssistant, client: MagicMock) -> None:
    client.discover = AsyncMock(side_effect=ConnectionError("down"))
    unreachable = make_entry()
    unreachable.add_to_hass(hass)
    await hass.config_entries.async_setup(unreachable.entry_id)
    assert unreachable.state is ConfigEntryState.SETUP_RETRY

    client.discover = AsyncMock(side_effect=AuthenticationError("no", status=401))
    refused = make_entry()
    refused.add_to_hass(hass)
    await hass.config_entries.async_setup(refused.entry_id)
    assert refused.state is ConfigEntryState.SETUP_ERROR
    assert hass.config_entries.flow.async_progress_by_handler("familyos")


async def test_switched_off_feature_is_unavailable_and_comes_back(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.discover = AsyncMock(return_value=discovery(off=("chores",)))
    await _poll(hass, freezer, entry)
    assert hass.states.get("sensor.familyos_chores_overdue").state == "unavailable"
    assert hass.states.get("todo.familyos_tasks").state == "1"
    assert entry.runtime_data.data.chores == []

    client.discover = AsyncMock(return_value=discovery())
    await _poll(hass, freezer, entry)
    assert hass.states.get("sensor.familyos_chores_overdue").state == "1"


async def test_role_without_lists_hides_them(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.discover = AsyncMock(return_value=discovery(operations=["calendar.listOccurrences", "chores.listChores"]))
    await _poll(hass, freezer, entry)
    assert hass.states.get("todo.familyos_tasks").state == "unavailable"
    assert hass.states.get("todo.familyos_shopping_groceries").state == "unavailable"
    assert hass.states.get("calendar.familyos_calendar").state != "unavailable"
    assert entry.runtime_data.data.shopping_lists == []


async def test_rrule_is_kept_until_the_event_changes(entry: MockConfigEntry, client: MagicMock) -> None:
    coordinator = entry.runtime_data
    client.get_event = AsyncMock(return_value=MagicMock(rrule=None, recurrence=None))
    assert await coordinator.async_rrule("cal_event_9") is None
    assert await coordinator.async_rrule("cal_event_9") is None
    assert client.get_event.await_count == 1
    client.get_event = AsyncMock(side_effect=FamilyOSError("gone", status=404))
    assert await coordinator.async_rrule("cal_event_10") is None
    with pytest.raises(UpdateFailed):
        raise UpdateFailed("kept for the import")
