"""The chore sensors."""

import datetime as dt
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from .common import chore, discovery


async def test_chores_due_today_and_overdue(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    today = hass.states.get("sensor.familyos_chores_due_today")
    assert today.state == "1"
    assert today.attributes["chores"] == ["Take out the bins"]
    assert today.attributes["unit_of_measurement"] == "chores"

    overdue = hass.states.get("sensor.familyos_chores_overdue")
    assert overdue.state == "1"
    assert overdue.attributes["chores"] == ["Water plants"]


async def test_the_sensors_follow_the_date(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client
) -> None:
    client.iter_chores.items[:] = [
        chore("chore_1", "Take out the bins", nextDue="2026-10-21"),
        chore("chore_3", "Vacuum", nextDue="2026-10-24"),
    ]
    freezer.tick(dt.timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.familyos_chores_due_today").state == "1"
    assert hass.states.get("sensor.familyos_chores_overdue").state == "0"


async def test_unavailable_when_chores_are_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client
) -> None:
    client.discover = AsyncMock(return_value=discovery(off=("chores",)))
    freezer.tick(dt.timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.familyos_chores_due_today").state == "unavailable"
