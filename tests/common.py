"""Builders for the FamilyOS client's answers, and a fake client."""

import datetime as dt
from collections.abc import AsyncIterator, Iterable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from familyos import (
    Applied,
    BoardNote,
    Changes,
    Chore,
    ChoreCompleted,
    Discovery,
    Drafted,
    DraftSummary,
    Event,
    FamilyOS,
    Occurrence,
    ShoppingItem,
    ShoppingList,
    Task,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.familyos.const import DOMAIN

URL = "http://famos.test:3000"
KEY = "famos_test_key"
ZONE = "Europe/Amsterdam"
NOW = dt.datetime(2026, 10, 20, 8, 0, tzinfo=dt.UTC)  # 10:00 in Amsterdam
GROCERIES = "shop_list_1"
OFFSET = "+02:00"

ALL_OPERATIONS = [
    "calendar.listOccurrences",
    "calendar.createEvent",
    "calendar.patchEvent",
    "calendar.deleteEvent",
    "lists.listShoppingLists",
    "lists.listShoppingItems",
    "lists.addShoppingItems",
    "lists.listTasks",
    "lists.addTask",
    "chores.listChores",
    "chores.completeChore",
    "board.listNotes",
    "board.createNote",
]
# What a FamilyOS 0.4 key may do: it lists reading the suggestions too.
OPERATIONS_04 = [*ALL_OPERATIONS, "core.listDrafts"]


def discovery(*, off: tuple[str, ...] = (), operations: Iterable[str] = ALL_OPERATIONS) -> Discovery:
    """What FamilyOS says about itself; ``off`` switches extensions off."""
    ids = ["calendar", "lists", "chores", "board"]
    return Discovery.from_dict(
        {
            "api": "v1",
            "familyOS": "0.3.0",
            "timeZone": ZONE,
            "language": "en",
            "caller": {"app": {"id": "app_1", "name": "Home Assistant", "mode": "apply"}, "memberId": None},
            "extensions": [{"id": i, "version": "0.3.0", "enabled": i not in off} for i in ids],
            "operations": [
                {"name": name, "method": "get", "path": "/x", "summary": "x", "outcome": "read"}
                for name in operations
                if name.split(".")[0] not in off
            ],
        }
    )


def occurrence(
    title: str = "Dentist",
    start: str = "2026-10-21T09:30:00+02:00",
    end: str = "2026-10-21T10:15:00+02:00",
    *,
    event_id: str = "cal_event_1",
    recurring: bool = False,
    all_day: bool = False,
    recurrence_id: str | None = None,
    series_id: str | None = None,
    recurrence_key: str | None = None,
    series_recurrence_id: str | None = None,
    **extra: Any,
) -> Occurrence:
    return Occurrence.from_dict(
        {
            "eventId": event_id,
            "recurrenceId": recurrence_id or start,
            "title": title,
            "allDay": all_day,
            "start": start,
            "end": end,
            "memberIds": [],
            "location": extra.get("location"),
            "recurring": recurring,
            "notes": extra.get("notes"),
            "source": None,
            "editable": True,
            "tags": [],
            "seriesId": series_id,
            "recurrenceKey": recurrence_key,
            "seriesRecurrenceId": series_recurrence_id,
        }
    )


def event(**extra: Any) -> Event:
    fields: dict[str, Any] = {
        "id": "cal_event_1",
        "version": 3,
        "title": "Gym",
        "allDay": False,
        "start": "2026-10-22T07:00:00+02:00",
        "end": "2026-10-22T08:00:00+02:00",
        "date": "2026-10-22",
        "endDate": None,
        "startTime": "07:00",
        "endTime": "08:00",
        "memberIds": [],
        "location": None,
        "notes": None,
        "recurrence": None,
        "rrule": None,
        "reminder": 0,
        "tags": [],
    }
    fields.update(extra)
    return Event.from_dict(fields)


def shopping_list(list_id: str = GROCERIES, name: str = "Groceries") -> ShoppingList:
    return ShoppingList.from_dict(
        {"id": list_id, "version": 0, "name": name, "isDefault": list_id == GROCERIES, "openCount": 1}
    )


def shopping_item(item_id: str = "shop_item_1", title: str = "Milk", *, done: bool = False) -> ShoppingItem:
    return ShoppingItem.from_dict(
        {
            "id": item_id,
            "version": 0,
            "listId": GROCERIES,
            "title": title,
            "quantity": None,
            "category": "other",
            "done": done,
            "doneAt": None,
            "addedBy": None,
        }
    )


def task(task_id: str = "task_1", title: str = "Pay the school fee", **extra: Any) -> Task:
    fields: dict[str, Any] = {
        "id": task_id,
        "version": 1,
        "title": title,
        "notes": None,
        "assigneeId": None,
        "dueDate": None,
        "dueTime": None,
        "due": None,
        "recurrence": None,
        "rrule": None,
        "done": False,
        "doneAt": None,
        "doneBy": None,
    }
    fields.update(extra)
    return Task.from_dict(fields)


def chore(chore_id: str = "chore_1", title: str = "Take out the bins", **extra: Any) -> Chore:
    fields: dict[str, Any] = {
        "id": chore_id,
        "version": 0,
        "title": title,
        "notes": None,
        "recurrence": {"freq": "daily", "interval": 1},
        "startDate": "2026-10-01",
        "nextDue": "2026-10-20",
        "overdue": False,
        "rotation": "fixed",
        "assigneeId": None,
        "assigneeIds": [],
        "lastDone": None,
        "createdAt": "2026-10-01T10:00:00+02:00",
        "updatedAt": "2026-10-01T10:00:00+02:00",
    }
    fields.update(extra)
    return Chore.from_dict(fields)


def note(text: str = "Back at six") -> BoardNote:
    return BoardNote.from_dict(
        {
            "id": "board_note_1",
            "version": 0,
            "text": text,
            "paper": "note-1",
            "pinned": False,
            "endsAt": None,
            "endsOn": None,
            "hasPhoto": False,
            "createdBy": None,
            "createdAt": "2026-10-20T10:00:00+02:00",
            "updatedAt": "2026-10-20T10:00:00+02:00",
            "seenBy": [],
        }
    )


def draft_summary(
    draft_id: str = "draft_1", title: str = "Add a note", subject: str | None = "Back at six"
) -> DraftSummary:
    return DraftSummary.from_dict(
        {
            "id": draft_id,
            "status": "waiting",
            "extension": "board",
            "title": title,
            "subject": subject,
            "proposedAt": "2026-10-20T09:00:00+02:00",
            "proposedBy": "Home Assistant",
            "canDecide": False,
        }
    )


def applied(result: Any) -> Applied[Any]:
    return Applied(result=result, time_zone=ZONE)


def drafted(draft_id: str = "draft_1") -> Drafted:
    return Drafted(draft_id=draft_id, time_zone=ZONE)


def changes(*items: tuple[str, ...], cursor: int = 1, more: bool = False) -> Changes:
    return Changes.from_dict(
        {
            "changes": [
                {
                    "seq": index,
                    "at": "2026-10-20T10:00:00+02:00",
                    "extension": extension,
                    "entity": entity[0] if entity else "x",
                    "id": entity_id,
                    "op": "upsert",
                }
                for index, (extension, entity_id, *entity) in enumerate(items, 1)
            ],
            "cursor": cursor,
            "more": more,
            "timeZone": ZONE,
        }
    )


class Stream:
    """An ``iter_*`` method that can be called many times and counts its calls."""

    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        self.calls += 1
        return self._run()

    async def _run(self) -> AsyncIterator[Any]:
        for item in list(self.items):
            yield item


def fake_client() -> MagicMock:
    """A FamilyOS client whose reads give a small family and whose writes are applied."""
    client = MagicMock(spec=FamilyOS)
    client.on_behalf_of = None
    client.discover = AsyncMock(return_value=discovery())
    client.changes = AsyncMock(return_value=changes(cursor=1))
    client.iter_occurrences = Stream(
        [
            occurrence("Dentist", recurring=False),
            occurrence(
                "Swimming",
                "2026-10-20T17:00:00+02:00",
                "2026-10-20T18:00:00+02:00",
                event_id="cal_event_2",
                recurring=True,
            ),
            occurrence("Trip", "2026-10-22", "2026-10-23", event_id="cal_event_3", all_day=True),
        ]
    )
    client.iter_shopping_lists = Stream([shopping_list()])
    client.iter_shopping_items = Stream([shopping_item(), shopping_item("shop_item_2", "Eggs", done=True)])
    client.iter_tasks = Stream(
        [
            task("task_1", "Pay the school fee", dueDate="2026-10-25", due="2026-10-25", notes="Bring cash"),
            task("task_2", "Water the plants", done=True),
        ]
    )
    client.iter_drafts = Stream([])
    client.iter_chores = Stream(
        [
            chore("chore_1", "Take out the bins"),
            chore("chore_2", "Water plants", nextDue="2026-10-17", overdue=True),
            chore("chore_3", "Vacuum", nextDue="2026-10-24"),
        ]
    )
    client.get_event = AsyncMock(return_value=event())
    for name, result in {
        "create_event": event(),
        "patch_event": event(),
        "delete_event": MagicMock(),
        "add_shopping_items": MagicMock(),
        "patch_shopping_item": shopping_item(),
        "complete_shopping_item": shopping_item(done=True),
        "uncheck_shopping_item": shopping_item(),
        "delete_shopping_item": MagicMock(),
        "add_task": task(),
        "patch_task": task(),
        "complete_task": task(done=True),
        "reopen_task": task(),
        "delete_task": MagicMock(),
        "create_note": note(),
        "patch_note": note("Back at seven"),
        "delete_note": MagicMock(),
    }.items():
        setattr(client, name, AsyncMock(return_value=applied(result)))
    client.complete_chore = AsyncMock(
        return_value=applied(ChoreCompleted(chore=chore(), completion=MagicMock(), reason=None))
    )
    return client


def make_entry(**options: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="FamilyOS (famos.test:3000)",
        unique_id=URL,
        data={"url": URL, "api_key": KEY},
        options=options,
    )
