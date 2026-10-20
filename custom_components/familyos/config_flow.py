"""Add FamilyOS: its address and an app key, checked by asking FamilyOS who we are."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import probatio as vol
from familyos import AuthenticationError, Discovery, FamilyOS, FamilyOSError, ForbiddenError
from familyos import ConnectionError as FamilyOSConnectionError
from familyos import TimeoutError as FamilyOSTimeoutError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACT_FOR,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import FamilyOSConfigEntry

_API_PATH = "/api/public/v1"


def normalize_url(value: str) -> str:
    """The address as one stable text: scheme and host in lower case, no trailing slash, no API path."""
    text = value.strip()
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    path = parts.path.rstrip("/").removesuffix(_API_PATH).rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


class CannotConnect(Exception):
    """FamilyOS did not answer."""


class InvalidAuth(Exception):
    """FamilyOS refused the key."""


class Unsupported(Exception):
    """The address is not a FamilyOS with the public API."""


async def _discover(hass: Any, url: str, key: str, on_behalf_of: str | None = None) -> Discovery:
    client = FamilyOS(url, key, session=async_get_clientsession(hass), on_behalf_of=on_behalf_of)
    try:
        found = await client.discover()
    except AuthenticationError as err:
        raise InvalidAuth from err
    except (FamilyOSConnectionError, FamilyOSTimeoutError) as err:
        raise CannotConnect from err
    except ForbiddenError:
        raise
    except FamilyOSError as err:
        LOGGER.debug("FamilyOS at %s answered unexpectedly: %s", url, err)
        raise Unsupported from err
    if found.api != "v1":
        raise Unsupported
    return found


class FamilyOSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the address and the key."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The address and the key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            key = user_input[CONF_API_KEY].strip()
            try:
                await _discover(self.hass, url, key)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Unsupported, ForbiddenError:
                errors["base"] = "unsupported"
            except Exception:
                LOGGER.exception("Unexpected error while checking FamilyOS")
                errors["base"] = "unknown"
            else:
                # FamilyOS names no family, so the address is what tells one from another.
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"FamilyOS ({urlsplit(url).netloc})",
                    data={CONF_URL: url, CONF_API_KEY: key},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, "")): str,
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The key was refused: ask for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A new key for the same FamilyOS."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            try:
                await _discover(self.hass, entry.data[CONF_URL], key)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Unsupported, ForbiddenError:
                errors["base"] = "unsupported"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: key})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: FamilyOSConfigEntry) -> OptionsFlow:
        """The options: how often to ask, and whom to act for."""
        return FamilyOSOptionsFlow()


class FamilyOSOptionsFlow(OptionsFlow):
    """How often to ask FamilyOS, and the member to act for."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and check the options."""
        errors: dict[str, str] = {}
        entry = self.config_entry
        if user_input is not None:
            member = (user_input.get(CONF_ACT_FOR) or "").strip()
            try:
                # FamilyOS refuses a person the app may not act for; better to hear it now than at every poll.
                await _discover(self.hass, entry.data[CONF_URL], entry.data[CONF_API_KEY], member or None)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except ForbiddenError, Unsupported:
                errors[CONF_ACT_FOR] = "act_for_refused"
            else:
                return self.async_create_entry(
                    data={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL], CONF_ACT_FOR: member}
                )
        current = user_input or entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                    vol.Optional(CONF_ACT_FOR, default=current.get(CONF_ACT_FOR, "")): str,
                }
            ),
            errors=errors,
        )
