"""The to-do lists: shopping lists and tasks."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from familyos import ConflictError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from .common import GROCERIES, drafted, shopping_list, task

SHOPPING = "todo.familyos_shopping_groceries"
TASKS = "todo.familyos_tasks"


async def _items(hass: HomeAssistant, entity: str) -> list[dict[str, str]]:
    answer = await hass.services.async_call(
        "todo", "get_items", {"entity_id": entity}, blocking=True, return_response=True
    )
    return answer[entity]["items"]  # type: ignore[no-any-return]


async def test_shopping_items_keep_their_ids(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert hass.states.get(SHOPPING).state == "1"
    assert await _items(hass, SHOPPING) == [
        {"summary": "Milk", "uid": "shop_item_1", "status": "needs_action"},
        {"summary": "Eggs", "uid": "shop_item_2", "status": "completed"},
    ]


async def test_shopping_add_rename_tick_untick_delete(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await hass.services.async_call("todo", "add_item", {"entity_id": SHOPPING, "item": "Bread"}, blocking=True)
    client.add_shopping_items.assert_awaited_once_with(GROCERIES, ["Bread"])

    await hass.services.async_call(
        "todo", "update_item", {"entity_id": SHOPPING, "item": "shop_item_1", "rename": "Oat milk"}, blocking=True
    )
    client.patch_shopping_item.assert_awaited_once_with("shop_item_1", title="Oat milk")
    client.complete_shopping_item.assert_not_awaited()

    await hass.services.async_call(
        "todo", "update_item", {"entity_id": SHOPPING, "item": "shop_item_1", "status": "completed"}, blocking=True
    )
    client.complete_shopping_item.assert_awaited_once_with("shop_item_1")

    await hass.services.async_call(
        "todo", "update_item", {"entity_id": SHOPPING, "item": "shop_item_2", "status": "needs_action"}, blocking=True
    )
    client.uncheck_shopping_item.assert_awaited_once_with("shop_item_2")

    await hass.services.async_call(
        "todo", "remove_item", {"entity_id": SHOPPING, "item": ["shop_item_1", "shop_item_2"]}, blocking=True
    )
    assert [c.args for c in client.delete_shopping_item.await_args_list] == [("shop_item_1",), ("shop_item_2",)]


async def test_a_change_that_waits_for_approval_changes_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.add_shopping_items = AsyncMock(return_value=drafted("draft_1"))
    client.complete_shopping_item = AsyncMock(return_value=drafted("draft_2"))
    await hass.services.async_call("todo", "add_item", {"entity_id": SHOPPING, "item": "Bread"}, blocking=True)
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": SHOPPING, "item": "shop_item_1", "status": "completed"}, blocking=True
    )
    assert [i["summary"] for i in await _items(hass, SHOPPING)] == ["Milk", "Eggs"]
    assert (await _items(hass, SHOPPING))[0]["status"] == "needs_action"
    notices = hass.data["persistent_notification"]
    assert notices["familyos_draft_draft_1"]["message"] == "Waiting for approval in FamilyOS: Bread"
    assert notices["familyos_draft_draft_2"]["message"] == "Waiting for approval in FamilyOS: Milk"
    assert notices["familyos_draft_draft_2"]["title"] == "FamilyOS"


async def test_a_conflict_refreshes_and_is_told(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.complete_shopping_item = AsyncMock(side_effect=ConflictError("not in a state that allows it", status=409))
    reads = client.iter_shopping_lists.calls
    with pytest.raises(HomeAssistantError, match="could not do this"):
        await hass.services.async_call(
            "todo", "update_item", {"entity_id": SHOPPING, "item": "shop_item_1", "status": "completed"}, blocking=True
        )
    assert client.iter_shopping_lists.calls == reads  # nothing changed, nothing to read again
    await hass.async_block_till_done()


async def test_an_item_that_is_gone_is_not_an_error(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    entity = hass.data["todo"].get_entity(SHOPPING)
    await entity.async_update_todo_item(MagicMock(uid="shop_item_404", summary="x"))
    client.patch_shopping_item.assert_not_awaited()


async def test_a_new_shopping_list_gets_an_entity(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.iter_shopping_lists.items.append(shopping_list("shop_list_2", "Hardware"))
    client.changes = AsyncMock(
        return_value=MagicMock(changes=[MagicMock(extension="lists", id="shop_list_2")], cursor=2, more=False)
    )
    freezer.tick(dt.timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("todo.familyos_shopping_hardware") is not None

    client.iter_shopping_lists.items.pop()
    client.changes = AsyncMock(
        return_value=MagicMock(changes=[MagicMock(extension="lists", id="shop_list_2")], cursor=3, more=False)
    )
    freezer.tick(dt.timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("todo.familyos_shopping_hardware").state == "unavailable"


async def test_tasks_show_due_dates_and_notes(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    items = await _items(hass, TASKS)
    assert items[0] == {
        "summary": "Pay the school fee",
        "uid": "task_1",
        "status": "needs_action",
        "due": "2026-10-25",
        "description": "Bring cash",
    }
    assert items[1]["status"] == "completed"


async def test_tasks_with_a_time_show_it_on_the_family_clock(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    client.iter_tasks.items[:] = [
        task("task_3", "Call", dueDate="2026-10-25", dueTime="09:30", due="2026-10-25T09:30:00+01:00")
    ]
    client.changes = AsyncMock(
        return_value=MagicMock(changes=[MagicMock(extension="lists", id="t")], cursor=2, more=False)
    )
    await entry.runtime_data.async_refresh()
    assert (await _items(hass, TASKS))[0]["due"] == "2026-10-25T09:30:00+01:00"


async def test_task_add(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": TASKS, "item": "Book the vet", "due_date": "2026-10-28", "description": "Rex"},
        blocking=True,
    )
    client.add_task.assert_awaited_once_with("Book the vet", notes="Rex", due_date=dt.date(2026, 10, 28), due_time=None)

    await hass.services.async_call(
        "todo", "add_item", {"entity_id": TASKS, "item": "Call", "due_datetime": "2026-10-28 09:30:00"}, blocking=True
    )
    _, kwargs = client.add_task.await_args
    assert kwargs["due_date"] == dt.date(2026, 10, 28)
    assert kwargs["due_time"] == dt.time(9, 30)
    assert kwargs["notes"] is None


async def test_task_update(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": TASKS,
            "item": "task_1",
            "rename": "Pay the fee",
            "due_date": "2026-10-26",
            "description": "",
        },
        blocking=True,
    )
    client.patch_task.assert_awaited_once_with(
        "task_1", title="Pay the fee", notes=None, due_date=dt.date(2026, 10, 26), due_time=None
    )

    await hass.services.async_call(
        "todo", "update_item", {"entity_id": TASKS, "item": "task_1", "status": "completed"}, blocking=True
    )
    client.complete_task.assert_awaited_once_with("task_1", due_date=None)
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": TASKS, "item": "task_2", "status": "needs_action"}, blocking=True
    )
    client.reopen_task.assert_awaited_once_with("task_2")

    await hass.services.async_call("todo", "remove_item", {"entity_id": TASKS, "item": ["task_1"]}, blocking=True)
    client.delete_task.assert_awaited_once_with("task_1")


async def test_completing_a_repeating_task_names_the_date(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.iter_tasks.items[:] = [
        task("task_4", "Bins", dueDate="2026-10-21", due="2026-10-21", recurrence={"freq": "weekly", "interval": 1})
    ]
    await entry.runtime_data.async_refresh()
    # The change log has nothing new; read the tasks again through a full refresh.
    entry.runtime_data._cursor = None
    await entry.runtime_data.async_refresh()
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": TASKS, "item": "task_4", "status": "completed"}, blocking=True
    )
    client.complete_task.assert_awaited_once_with("task_4", due_date=dt.date(2026, 10, 21))
