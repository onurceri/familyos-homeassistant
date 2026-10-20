"""The config flow: add, reauth and options."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from familyos import AuthenticationError, ConnectionError, FamilyOSError, ForbiddenError, TimeoutError
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.familyos.config_flow import normalize_url
from custom_components.familyos.const import DOMAIN

from .common import KEY, URL, discovery, make_entry


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


async def test_add(hass: HomeAssistant, client: MagicMock) -> None:
    flow = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow, {"url": URL + "/", "api_key": f" {KEY} "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "FamilyOS (famos.test:3000)"
    assert result["data"] == {"url": URL, "api_key": KEY}
    assert result["result"].unique_id == URL
    assert result["result"].state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AuthenticationError("no", status=401), "invalid_auth"),
        (ConnectionError("down"), "cannot_connect"),
        (TimeoutError("slow"), "cannot_connect"),
        (FamilyOSError("odd", status=500), "unsupported"),
        (ForbiddenError("no", status=403), "unsupported"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_errors_then_recovery(hass: HomeAssistant, client: MagicMock, error: Exception, reason: str) -> None:
    flow = await _start(hass)
    client.discover = AsyncMock(side_effect=error)
    result = await hass.config_entries.flow.async_configure(flow, {"url": URL, "api_key": KEY})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}

    client.discover = AsyncMock(return_value=discovery())
    result = await hass.config_entries.flow.async_configure(flow, {"url": URL, "api_key": KEY})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_other_api_version_is_refused(hass: HomeAssistant, client: MagicMock) -> None:
    flow = await _start(hass)
    found = discovery()
    object.__setattr__(found, "api", "v2")
    client.discover = AsyncMock(return_value=found)
    result = await hass.config_entries.flow.async_configure(flow, {"url": URL, "api_key": KEY})
    assert result["errors"] == {"base": "unsupported"}


async def test_same_address_twice(hass: HomeAssistant, client: MagicMock) -> None:
    make_entry().add_to_hass(hass)
    flow = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow, {"url": "HTTP://Famos.test:3000/api/public/v1", "api_key": KEY}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("typed", "normal"),
    [
        ("famos.test:3000", "http://famos.test:3000"),
        ("https://Family.Example.com/", "https://family.example.com"),
        ("https://x.org/family/api/public/v1/", "https://x.org/family"),
    ],
)
def test_normalize_url(typed: str, normal: str) -> None:
    assert normalize_url(typed) == normal


async def test_reauth(hass: HomeAssistant, client: MagicMock) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    client.discover = AsyncMock(side_effect=AuthenticationError("no", status=401))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "famos_old"})
    assert result["errors"] == {"base": "invalid_auth"}

    client.discover = AsyncMock(side_effect=ConnectionError("down"))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "famos_new"})
    assert result["errors"] == {"base": "cannot_connect"}

    client.discover = AsyncMock(return_value=discovery())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "famos_new"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "famos_new"
    assert entry.data["url"] == URL


async def test_options(hass: HomeAssistant, client: MagicMock) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    client.discover = AsyncMock(side_effect=ForbiddenError("on_behalf", status=403, reason="on_behalf"))
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30, "act_for": "member_stranger"}
    )
    assert result["errors"] == {"act_for": "act_for_refused"}

    client.discover = AsyncMock(return_value=discovery())
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30, "act_for": " member_leo "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"scan_interval": 30, "act_for": "member_leo"}
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval.total_seconds() == 30


async def test_options_cannot_connect(hass: HomeAssistant, client: MagicMock) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    client.discover = AsyncMock(side_effect=ConnectionError("down"))
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 60})
    assert result["errors"] == {"base": "cannot_connect"}
    client.discover = AsyncMock(side_effect=AuthenticationError("no", status=401))
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 60})
    assert result["errors"] == {"base": "invalid_auth"}
