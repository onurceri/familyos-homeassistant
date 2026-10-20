"""The FamilyOS integration: a family's calendar, shopping lists, tasks and chores in Home Assistant."""

import datetime as dt

from familyos import FamilyOS
from homeassistant.const import CONF_API_KEY, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ACT_FOR, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import FamilyOSConfigEntry, FamilyOSCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FamilyOSConfigEntry) -> bool:
    """Connect to FamilyOS and set up the entities."""
    client = FamilyOS(
        entry.data[CONF_URL],
        entry.data[CONF_API_KEY],
        session=async_get_clientsession(hass),
        on_behalf_of=entry.options.get(CONF_ACT_FOR) or None,
    )
    interval = dt.timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = FamilyOSCoordinator(hass, entry, client, interval)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_changed))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FamilyOSConfigEntry) -> bool:
    """Unload the entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_changed(hass: HomeAssistant, entry: FamilyOSConfigEntry) -> None:
    """A new interval or person takes a fresh start."""
    await hass.config_entries.async_reload(entry.entry_id)
