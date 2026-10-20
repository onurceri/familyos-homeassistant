"""Shared fixtures: a fake FamilyOS client and the integration set up with it."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import NOW, fake_client, make_entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from this repository."""


@pytest.fixture(autouse=True)
def freeze(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """The tests run at 10:00 on 20 October 2026 in Amsterdam."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def client() -> Generator[MagicMock]:
    """The fake client that every part of the integration gets."""
    fake = fake_client()
    with (
        patch("custom_components.familyos.FamilyOS", return_value=fake),
        patch("custom_components.familyos.config_flow.FamilyOS", return_value=fake),
    ):
        yield fake


@pytest.fixture
async def entry(hass: HomeAssistant, client: MagicMock) -> MockConfigEntry:
    """The integration, set up, in a home that keeps the family's clock."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    config = make_entry()
    config.add_to_hass(hass)
    await hass.config_entries.async_setup(config.entry_id)
    await hass.async_block_till_done()
    return config
