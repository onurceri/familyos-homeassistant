"""To-do lists: one for each shopping list of the family, and one for tasks."""

import datetime as dt
from typing import Any

from familyos import ShoppingItem, ShoppingList, Task
from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import FEATURE_SHOPPING, FEATURE_TASKS
from .coordinator import FamilyOSConfigEntry, FamilyOSCoordinator
from .entity import FamilyOSEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: FamilyOSConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """The tasks list, and a list for every shopping list (also ones made later)."""
    coordinator = entry.runtime_data
    async_add_entities([TasksTodo(coordinator, entry)])

    known: set[str] = set()

    @callback
    def add_new_lists() -> None:
        if coordinator.data is None:
            return
        fresh = [shopping for shopping in coordinator.data.shopping_lists if shopping.id not in known]
        known.update(shopping.id for shopping in fresh)
        if fresh:
            async_add_entities(ShoppingTodo(coordinator, entry, shopping) for shopping in fresh)

    add_new_lists()
    entry.async_on_unload(coordinator.async_add_listener(add_new_lists))


class ShoppingTodo(FamilyOSEntity, TodoListEntity):
    """One shopping list. Ticking an item off here ticks it off in FamilyOS."""

    feature = FEATURE_SHOPPING
    _attr_translation_key = "shopping"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: FamilyOSCoordinator, entry: FamilyOSConfigEntry, shopping: ShoppingList) -> None:
        super().__init__(coordinator, entry, f"shopping_{shopping.id}")
        self._list_id = shopping.id
        self._attr_translation_placeholders = {"list": shopping.name}

    def _items(self) -> list[ShoppingItem]:
        return self.coordinator.data.shopping_items.get(self._list_id, []) if self.coordinator.data else []

    @property
    def available(self) -> bool:
        """Whether FamilyOS answers, offers shopping and still has this list."""
        data = self.coordinator.data
        return super().available and data is not None and any(s.id == self._list_id for s in data.shopping_lists)

    @property
    def todo_items(self) -> list[TodoItem]:
        """The items of the list."""
        return [
            TodoItem(
                uid=item.id,
                summary=item.title,
                status=TodoItemStatus.COMPLETED if item.done else TodoItemStatus.NEEDS_ACTION,
            )
            for item in self._items()
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item to the list."""
        title = item.summary or ""
        await self.coordinator.async_write(
            self.coordinator.client.add_shopping_items(self._list_id, [title]), subject=title
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Rename an item, tick it off or put it back."""
        client = self.coordinator.client
        current = next((i for i in self._items() if i.id == item.uid), None)
        if current is None or item.uid is None:
            await self.coordinator.async_refresh()
            return
        if item.summary and item.summary != current.title:
            await self.coordinator.async_write(client.patch_shopping_item(item.uid, title=item.summary), item.summary)
        wanted_done = item.status == TodoItemStatus.COMPLETED
        if wanted_done != current.done:
            call = client.complete_shopping_item if wanted_done else client.uncheck_shopping_item
            await self.coordinator.async_write(call(item.uid), item.summary or current.title)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Take items off the list."""
        for uid in uids:
            title = next((i.title for i in self._items() if i.id == uid), uid)
            await self.coordinator.async_write(self.coordinator.client.delete_shopping_item(uid), subject=title)


def _due(task: Task, zone: Any) -> dt.date | dt.datetime | None:
    if task.due is None:
        return None
    return task.due.astimezone(zone) if isinstance(task.due, dt.datetime) else task.due


class TasksTodo(FamilyOSEntity, TodoListEntity):
    """The family's tasks, with a due date and notes."""

    feature = FEATURE_TASKS
    _attr_translation_key = "tasks"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator: FamilyOSCoordinator, entry: FamilyOSConfigEntry) -> None:
        super().__init__(coordinator, entry, "tasks")

    def _tasks(self) -> list[Task]:
        return self.coordinator.data.tasks if self.coordinator.data else []

    @property
    def todo_items(self) -> list[TodoItem]:
        """The tasks."""
        zone = self.coordinator.time_zone
        return [
            TodoItem(
                uid=task.id,
                summary=task.title,
                status=TodoItemStatus.COMPLETED if task.done else TodoItemStatus.NEEDS_ACTION,
                due=_due(task, zone),
                description=task.notes,
            )
            for task in self._tasks()
        ]

    def _due_fields(self, due: dt.date | dt.datetime | None) -> dict[str, Any]:
        """FamilyOS' due date and time for a due (the clock is the family's own)."""
        if isinstance(due, dt.datetime):
            local = due.astimezone(self.coordinator.time_zone)
            return {"due_date": local.date(), "due_time": local.time().replace(second=0, microsecond=0, tzinfo=None)}
        return {"due_date": due, "due_time": None}

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a task."""
        title = item.summary or ""
        fields = self._due_fields(item.due)
        await self.coordinator.async_write(
            self.coordinator.client.add_task(title, notes=item.description or None, **fields), subject=title
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Change a task: its words, its due date, whether it is done."""
        client = self.coordinator.client
        current = next((t for t in self._tasks() if t.id == item.uid), None)
        if current is None or item.uid is None:
            await self.coordinator.async_refresh()
            return
        zone = self.coordinator.time_zone
        changes: dict[str, Any] = {}
        if item.summary and item.summary != current.title:
            changes["title"] = item.summary
        if (item.description or None) != (current.notes or None):
            changes["notes"] = item.description or None
        if item.due != _due(current, zone):
            changes.update(self._due_fields(item.due))
        subject = item.summary or current.title
        if changes:
            await self.coordinator.async_write(client.patch_task(item.uid, **changes), subject)
        wanted_done = item.status == TodoItemStatus.COMPLETED
        if wanted_done != current.done:
            if wanted_done:
                # A repeating task is done for the date it is due; the next date comes up by itself.
                call = client.complete_task(item.uid, due_date=current.due_date if current.recurrence else None)
            else:
                call = client.reopen_task(item.uid)
            await self.coordinator.async_write(call, subject)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete tasks."""
        for uid in uids:
            title = next((t.title for t in self._tasks() if t.id == uid), uid)
            await self.coordinator.async_write(self.coordinator.client.delete_task(uid), subject=title)
