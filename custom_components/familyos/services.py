"""The services: put a note on the board, change or remove it, and complete a chore."""

import datetime as dt
from typing import Any

import probatio as vol
from familyos import Applied, Drafted
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, FEATURE_BOARD, FEATURE_CHORES
from .coordinator import FamilyOSConfigEntry, FamilyOSCoordinator

ATTR_ENTRY = "config_entry_id"

POST_NOTE_SCHEMA = vol.Schema(
    {
        vol.Required("text"): vol.All(cv.string, vol.Length(min=1, max=2000)),
        vol.Optional("pinned"): cv.boolean,
        vol.Optional(ATTR_ENTRY): cv.string,
    }
)
EDIT_NOTE_SCHEMA = vol.Schema(
    {
        vol.Required("note"): cv.string,
        vol.Optional("text"): vol.All(cv.string, vol.Length(min=1, max=2000)),
        vol.Optional("paper"): cv.string,
        vol.Optional("ends_on"): cv.date,
        vol.Optional(ATTR_ENTRY): cv.string,
    }
)
REMOVE_NOTE_SCHEMA = vol.Schema({vol.Required("note"): cv.string, vol.Optional(ATTR_ENTRY): cv.string})
COMPLETE_CHORE_SCHEMA = vol.Schema(
    {
        vol.Required("chore"): cv.string,
        vol.Optional("due_date"): cv.date,
        vol.Optional("done_by"): cv.string,
        vol.Optional(ATTR_ENTRY): cv.string,
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> FamilyOSCoordinator:
    """The FamilyOS the call is for: the one named, or the only one."""
    entries: list[FamilyOSConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and (call.data.get(ATTR_ENTRY) in (None, entry.entry_id))
    ]
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_such_entry")
    if len(entries) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="several_entries")
    return entries[0].runtime_data


def _answer(outcome: Applied[Any] | Drafted, result_id: str | None) -> dict[str, Any]:
    if isinstance(outcome, Drafted):
        return {"status": "drafted", "draft_id": outcome.draft_id}
    return {"status": "applied", "id": result_id}


async def _post_note(call: ServiceCall) -> dict[str, Any]:
    coordinator = _coordinator(call.hass, call)
    if not coordinator.has(FEATURE_BOARD):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="feature_unavailable")
    text: str = call.data["text"]
    outcome = await coordinator.async_write(
        coordinator.client.create_note(text, pinned=call.data.get("pinned")), subject=text
    )
    return _answer(outcome, outcome.result.id if isinstance(outcome, Applied) else None)


async def _edit_note(call: ServiceCall) -> dict[str, Any]:
    coordinator = _coordinator(call.hass, call)
    if not coordinator.has(FEATURE_BOARD):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="feature_unavailable")
    note: str = call.data["note"]
    changes = {name: call.data[name] for name in ("text", "paper", "ends_on") if name in call.data}
    if not changes:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_change")
    outcome = await coordinator.async_write(
        coordinator.client.patch_note(note, **changes), subject=call.data.get("text", note)
    )
    return _answer(outcome, note)


async def _remove_note(call: ServiceCall) -> dict[str, Any]:
    coordinator = _coordinator(call.hass, call)
    if not coordinator.has(FEATURE_BOARD):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="feature_unavailable")
    note: str = call.data["note"]
    outcome = await coordinator.async_write(coordinator.client.delete_note(note), subject=note)
    return _answer(outcome, note)


async def _complete_chore(call: ServiceCall) -> dict[str, Any]:
    coordinator = _coordinator(call.hass, call)
    if not coordinator.has(FEATURE_CHORES) or coordinator.data is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="feature_unavailable")
    wanted: str = call.data["chore"]
    chore = next(
        (c for c in coordinator.data.chores if c.id == wanted or c.title.casefold() == wanted.strip().casefold()),
        None,
    )
    if chore is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_such_chore", translation_placeholders={"chore": wanted}
        )
    due: dt.date | None = call.data.get("due_date") or chore.next_due
    if due is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="chore_not_due", translation_placeholders={"chore": chore.title}
        )
    if not call.data.get("done_by") and not coordinator.client.on_behalf_of:
        # An app is nobody; FamilyOS needs to be told whose chore it was.
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="chore_needs_person")
    outcome = await coordinator.async_write(
        coordinator.client.complete_chore(chore.id, due, done_by=call.data.get("done_by")), subject=chore.title
    )
    if isinstance(outcome, Applied):
        # Not an error: somebody else got there first, or the date was already past; say what happened.
        return {"status": "applied", "id": chore.id, "reason": outcome.result.reason}
    return _answer(outcome, None)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services (once, for all connected FamilyOS)."""
    hass.services.async_register(
        DOMAIN, "post_note", _post_note, schema=POST_NOTE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "edit_note", _edit_note, schema=EDIT_NOTE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "remove_note", _remove_note, schema=REMOVE_NOTE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN,
        "complete_chore",
        _complete_chore,
        schema=COMPLETE_CHORE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
