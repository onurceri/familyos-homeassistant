"""The services: post_note, edit_note, remove_note and complete_chore."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from familyos import ChoreCompleted
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.familyos.const import DOMAIN

from .common import applied, chore, discovery, drafted, make_entry


async def test_post_note(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    answer = await hass.services.async_call(
        DOMAIN, "post_note", {"text": "Back at six", "pinned": True}, blocking=True, return_response=True
    )
    client.create_note.assert_awaited_once_with("Back at six", pinned=True)
    assert answer == {"status": "applied", "id": "board_note_1"}


async def test_post_note_waiting_for_approval(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.create_note = AsyncMock(return_value=drafted("draft_5"))
    answer = await hass.services.async_call(
        DOMAIN, "post_note", {"text": "Back at six"}, blocking=True, return_response=True
    )
    assert answer == {"status": "drafted", "draft_id": "draft_5"}
    # The suggestion is counted at once, not at the next poll.
    assert client.iter_drafts.calls == 2
    assert hass.data["persistent_notification"]["familyos_draft_draft_5"]["message"] == (
        "Waiting for approval in FamilyOS: Back at six"
    )


async def test_edit_note(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    answer = await hass.services.async_call(
        DOMAIN,
        "edit_note",
        {"note": "board_note_1", "text": "Back at seven", "ends_on": "2026-10-25"},
        blocking=True,
        return_response=True,
    )
    client.patch_note.assert_awaited_once_with("board_note_1", text="Back at seven", ends_on=dt.date(2026, 10, 25))
    assert answer == {"status": "applied", "id": "board_note_1"}


async def test_edit_note_paper_only_and_waiting_for_approval(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.patch_note = AsyncMock(return_value=drafted("draft_6"))
    answer = await hass.services.async_call(
        DOMAIN, "edit_note", {"note": "board_note_1", "paper": "note-2"}, blocking=True, return_response=True
    )
    client.patch_note.assert_awaited_once_with("board_note_1", paper="note-2")
    assert answer == {"status": "drafted", "draft_id": "draft_6"}
    assert hass.data["persistent_notification"]["familyos_draft_draft_6"]["message"] == (
        "Waiting for approval in FamilyOS: board_note_1"
    )


async def test_edit_note_needs_something_to_change(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    with pytest.raises(ServiceValidationError, match="Say what to change"):
        await hass.services.async_call(DOMAIN, "edit_note", {"note": "board_note_1"}, blocking=True)
    client.patch_note.assert_not_awaited()


async def test_remove_note(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    answer = await hass.services.async_call(
        DOMAIN, "remove_note", {"note": "board_note_1"}, blocking=True, return_response=True
    )
    client.delete_note.assert_awaited_once_with("board_note_1")
    assert answer == {"status": "applied", "id": "board_note_1"}


async def test_note_services_are_refused_without_the_board(hass: HomeAssistant, client: MagicMock) -> None:
    client.discover = AsyncMock(return_value=discovery(off=("board",)))
    config = make_entry()
    config.add_to_hass(hass)
    await hass.config_entries.async_setup(config.entry_id)
    await hass.async_block_till_done()
    for service, data in (("edit_note", {"note": "n", "text": "x"}), ("remove_note", {"note": "n"})):
        with pytest.raises(ServiceValidationError, match="switched off"):
            await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_complete_chore_by_title_for_a_person(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    answer = await hass.services.async_call(
        DOMAIN,
        "complete_chore",
        {"chore": "  water PLANTS ", "done_by": "member_leo"},
        blocking=True,
        return_response=True,
    )
    # The overdue date it is due, not today's.
    client.complete_chore.assert_awaited_once_with("chore_2", dt.date(2026, 10, 17), done_by="member_leo")
    assert answer == {"status": "applied", "id": "chore_2", "reason": None}


async def test_complete_chore_by_id_and_date(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.complete_chore = AsyncMock(
        return_value=applied(ChoreCompleted(chore=chore(), completion=MagicMock(), reason="already_done"))
    )
    answer = await hass.services.async_call(
        DOMAIN,
        "complete_chore",
        {"chore": "chore_1", "due_date": "2026-10-19", "done_by": "member_leo"},
        blocking=True,
        return_response=True,
    )
    client.complete_chore.assert_awaited_once_with("chore_1", dt.date(2026, 10, 19), done_by="member_leo")
    assert answer["reason"] == "already_done"


async def test_complete_chore_needs_to_know_who(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    with pytest.raises(ServiceValidationError, match="say who did the chore"):
        await hass.services.async_call(DOMAIN, "complete_chore", {"chore": "Vacuum"}, blocking=True)

    # An app that acts for a member needs no name.
    client.on_behalf_of = "member_leo"
    await hass.services.async_call(DOMAIN, "complete_chore", {"chore": "Vacuum"}, blocking=True)
    client.complete_chore.assert_awaited_once_with("chore_3", dt.date(2026, 10, 24), done_by=None)


async def test_complete_chore_waiting_for_approval(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.complete_chore = AsyncMock(return_value=drafted("draft_7"))
    answer = await hass.services.async_call(
        DOMAIN, "complete_chore", {"chore": "Vacuum", "done_by": "member_leo"}, blocking=True, return_response=True
    )
    assert answer == {"status": "drafted", "draft_id": "draft_7"}
    assert hass.data["persistent_notification"]["familyos_draft_draft_7"]["message"] == (
        "Waiting for approval in FamilyOS: Vacuum"
    )


async def test_complete_chore_unknown_or_without_date(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    with pytest.raises(ServiceValidationError, match='No chore matches "Mow"'):
        await hass.services.async_call(DOMAIN, "complete_chore", {"chore": "Mow", "done_by": "m"}, blocking=True)
    client.iter_chores.items[:] = [chore("chore_9", "Once", nextDue=None, recurrence=None)]
    entry.runtime_data._cursor = None
    await entry.runtime_data.async_refresh()
    with pytest.raises(ServiceValidationError, match="no due date"):
        await hass.services.async_call(DOMAIN, "complete_chore", {"chore": "Once", "done_by": "m"}, blocking=True)


async def test_services_need_the_feature(hass: HomeAssistant, client: MagicMock) -> None:
    client.discover = AsyncMock(return_value=discovery(off=("board", "chores")))
    config = make_entry()
    config.add_to_hass(hass)
    await hass.config_entries.async_setup(config.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="switched off"):
        await hass.services.async_call(DOMAIN, "post_note", {"text": "x"}, blocking=True)
    with pytest.raises(ServiceValidationError, match="switched off"):
        await hass.services.async_call(DOMAIN, "complete_chore", {"chore": "x"}, blocking=True)


async def test_which_familyos(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    with pytest.raises(ServiceValidationError, match="no FamilyOS connection"):
        await hass.services.async_call(DOMAIN, "post_note", {"text": "x", "config_entry_id": "nope"}, blocking=True)

    second = MockConfigEntry(
        domain=DOMAIN, unique_id="http://other:3000", data={"url": "http://other:3000", "api_key": "k"}
    )
    second.add_to_hass(hass)
    await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    assert second.state is ConfigEntryState.LOADED
    with pytest.raises(ServiceValidationError, match="More than one"):
        await hass.services.async_call(DOMAIN, "post_note", {"text": "x"}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "post_note", {"text": "x", "config_entry_id": second.entry_id}, blocking=True
    )


async def test_a_refused_key_during_a_write_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    from familyos import AuthenticationError

    client.create_note = AsyncMock(side_effect=AuthenticationError("no", status=401))
    with pytest.raises(HomeAssistantError, match="no longer accepts"):
        await hass.services.async_call(DOMAIN, "post_note", {"text": "x"}, blocking=True)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_a_paused_app_during_a_write_does_not_start_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    from familyos import AuthenticationError

    client.create_note = AsyncMock(side_effect=AuthenticationError("paused", status=401, reason="paused"))
    with pytest.raises(HomeAssistantError, match="paused in FamilyOS"):
        await hass.services.async_call(DOMAIN, "post_note", {"text": "x"}, blocking=True)
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_unreachable_during_a_write(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    from familyos import ConnectionError

    client.create_note = AsyncMock(side_effect=ConnectionError("down"))
    with pytest.raises(HomeAssistantError, match="cannot be reached"):
        await hass.services.async_call(DOMAIN, "post_note", {"text": "x"}, blocking=True)
