"""The coordinator: keeps one copy of the family's data and asks FamilyOS only for what changed."""

import asyncio
import datetime as dt
from collections.abc import Awaitable
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from familyos import (
    Applied,
    AuthenticationError,
    Chore,
    ConflictError,
    CursorExpired,
    Discovery,
    Drafted,
    DraftSummary,
    FamilyOS,
    FamilyOSError,
    ForbiddenError,
    NotFoundError,
    Occurrence,
    RateLimited,
    ShoppingItem,
    ShoppingList,
    Task,
)
from familyos import ConnectionError as FamilyOSConnectionError
from familyos import TimeoutError as FamilyOSTimeoutError
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_WINDOW,
    FEATURE_BOARD,
    FEATURE_CALENDAR,
    FEATURE_CHORES,
    FEATURE_DRAFTS,
    FEATURE_SHOPPING,
    FEATURE_TASKS,
    LOGGER,
)
from .rules import instance_id, rrule_from_recurrence

type FamilyOSConfigEntry = ConfigEntry[FamilyOSCoordinator]

# Which operation a key must be allowed to call for each feature of the integration.
_FEATURE_OPERATIONS = {
    FEATURE_CALENDAR: "calendar.listOccurrences",
    FEATURE_SHOPPING: "lists.listShoppingLists",
    FEATURE_TASKS: "lists.listTasks",
    FEATURE_CHORES: "chores.listChores",
    FEATURE_BOARD: "board.createNote",
}
_LIST_DRAFTS = "core.listDrafts"
# Stands in the touched set for a change of a suggestion (whichever extension it belongs to).
_DRAFT_CHANGE = "draft"
# Which part of FamilyOS' change log a feature is kept up to date from.
_FEATURE_EXTENSIONS = {
    FEATURE_CALENDAR: "calendar",
    FEATURE_SHOPPING: "lists",
    FEATURE_TASKS: "lists",
    FEATURE_CHORES: "chores",
}


@dataclass
class FamilyData:
    """What the integration knows about the family right now."""

    discovery: Discovery
    time_zone: ZoneInfo
    today: dt.date
    features: frozenset[str]
    occurrences: list[Occurrence] = field(default_factory=list)
    shopping_lists: list[ShoppingList] = field(default_factory=list)
    shopping_items: dict[str, list[ShoppingItem]] = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)
    chores: list[Chore] = field(default_factory=list)
    drafts: list[DraftSummary] = field(default_factory=list)


class FamilyOSCoordinator(DataUpdateCoordinator[FamilyData]):
    """Polls FamilyOS: its change log tells what to read again, and every read is an ETag read."""

    config_entry: FamilyOSConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FamilyOSConfigEntry,
        client: FamilyOS,
        interval: dt.timedelta,
    ) -> None:
        super().__init__(hass, LOGGER, config_entry=entry, name=DOMAIN, update_interval=interval)
        self.client = client
        self._cursor: int | None = None
        self._rrules: dict[str, str | None] = {}
        self._drafts_refused: frozenset[str] | None = None

    # --- refreshing ---------------------------------------------------------------------------------------

    async def _async_update_data(self) -> FamilyData:
        try:
            return await self._refresh()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("FamilyOS no longer accepts the key") from err
        except RateLimited as err:
            raise UpdateFailed("FamilyOS asked us to slow down", retry_after=err.retry_after) from err
        except (FamilyOSConnectionError, FamilyOSTimeoutError) as err:
            raise UpdateFailed(f"Cannot reach FamilyOS: {err}") from err
        except FamilyOSError as err:
            raise UpdateFailed(f"FamilyOS answered with an error: {err}") from err

    async def _refresh(self) -> FamilyData:
        discovery = await self.client.discover()
        zone = ZoneInfo(discovery.time_zone)
        today = dt.datetime.now(zone).date()
        features = frozenset(
            feature
            for feature, operation in _FEATURE_OPERATIONS.items()
            if discovery.can(operation) and discovery.enabled(operation.split(".")[0])
        )
        # FamilyOS 0.4 lists reading the suggestions among a key's operations. Older ones do not, so there it is
        # tried, and not tried again until what the key may do changes.
        operations = frozenset(operation.name for operation in discovery.operations)
        drafts_listed = discovery.can(_LIST_DRAFTS)
        if drafts_listed or self._drafts_refused != operations:
            features |= {FEATURE_DRAFTS}
        previous = self.data

        stale: set[str] = set()
        if previous is None or self._cursor is None:
            stale = set(features)
            self._cursor = (await self.client.changes()).cursor
        else:
            try:
                touched = await self._changes_since(self._cursor)
            except CursorExpired:
                LOGGER.debug("The change log no longer reaches back far enough; reading everything again")
                self._rrules.clear()
                self._cursor = (await self.client.changes()).cursor
                touched = {"calendar", "lists", "chores", _DRAFT_CHANGE}
            stale = {feature for feature in features if _FEATURE_EXTENSIONS.get(feature) in touched}
            if drafts_listed:
                # FamilyOS 0.4 tells of a suggestion that comes, changes or goes in its change log. One also ends
                # by itself when a day passes, so the date moving on reads them again too.
                if _DRAFT_CHANGE in touched or today != previous.today:
                    stale |= {FEATURE_DRAFTS}
            else:
                # Older servers do not tell, so the suggestions are asked for at every poll. The answer is an
                # ETag read: a 304 when nothing moved.
                stale |= {FEATURE_DRAFTS} & features
            if today != previous.today:
                # What is due today, what is overdue and what the calendar shows move with the date.
                stale |= {FEATURE_CALENDAR, FEATURE_CHORES} & features
            # A feature that has just become available has nothing to show yet.
            stale |= features - previous.features

        data = FamilyData(
            discovery=discovery,
            time_zone=zone,
            today=today,
            features=features,
            occurrences=previous.occurrences if previous else [],
            shopping_lists=previous.shopping_lists if previous else [],
            shopping_items=previous.shopping_items if previous else {},
            tasks=previous.tasks if previous else [],
            chores=previous.chores if previous else [],
            drafts=previous.drafts if previous else [],
        )
        # What went away is forgotten, so a switched-off feature shows nothing stale when it comes back.
        if FEATURE_CALENDAR not in features:
            data.occurrences = []
        if FEATURE_SHOPPING not in features:
            data.shopping_lists, data.shopping_items = [], {}
        if FEATURE_TASKS not in features:
            data.tasks = []
        if FEATURE_CHORES not in features:
            data.chores = []
        if FEATURE_DRAFTS not in features:
            data.drafts = []

        if FEATURE_CALENDAR in stale:
            data.occurrences = [
                occurrence async for occurrence in self.client.iter_occurrences(today, today + EVENT_WINDOW, limit=500)
            ]
        if FEATURE_SHOPPING in stale:
            data.shopping_lists = [item async for item in self.client.iter_shopping_lists()]
            lists = await asyncio.gather(*(self._shopping_items(shopping.id) for shopping in data.shopping_lists))
            data.shopping_items = {
                shopping.id: items for shopping, items in zip(data.shopping_lists, lists, strict=True)
            }
        if FEATURE_TASKS in stale:
            data.tasks = [task async for task in self.client.iter_tasks()]
        if FEATURE_CHORES in stale:
            data.chores = [chore async for chore in self.client.iter_chores()]
        if FEATURE_DRAFTS in stale:
            try:
                data.drafts = [draft async for draft in self.client.iter_drafts("waiting")]
            except ForbiddenError, NotFoundError:
                # The role may not propose, so it may not read the suggestions either (or this FamilyOS is
                # too old to list them).
                data.drafts = []
                data.features = features - {FEATURE_DRAFTS}
                self._drafts_refused = operations
        return data

    async def _shopping_items(self, list_id: str) -> list[ShoppingItem]:
        return [item async for item in self.client.iter_shopping_items(list_id)]

    async def _changes_since(self, cursor: int) -> set[str]:
        """The parts of FamilyOS that changed since the cursor; moves the cursor on."""
        touched: set[str] = set()
        while True:
            answer = await self.client.changes(cursor)
            for change in answer.changes:
                touched.add(change.extension)
                if change.entity == "draft":
                    touched.add(_DRAFT_CHANGE)
                if change.extension == "calendar":
                    self._rrules.pop(change.id, None)
            cursor = self._cursor = answer.cursor
            if not answer.more:
                return touched

    # --- what the entities ask for ------------------------------------------------------------------------

    def has(self, feature: str) -> bool:
        """Whether the feature is on and the app's role may use it."""
        return self.last_update_success and self.data is not None and feature in self.data.features

    @property
    def time_zone(self) -> ZoneInfo:
        """The family's time zone (until the first refresh, the server's)."""
        return self.data.time_zone if self.data else ZoneInfo(str(dt_util.get_default_time_zone()))

    async def async_rrule(self, event_id: str) -> str | None:
        """The repeat rule of an event, kept until the event changes (Home Assistant needs it to treat an
        occurrence as part of a series)."""
        if event_id not in self._rrules:
            try:
                event = await self.client.get_event(event_id)
            except FamilyOSError:
                return None
            self._rrules[event_id] = event.rrule or (
                rrule_from_recurrence(event.recurrence) if event.recurrence else None
            )
        return self._rrules[event_id]

    def moved_event_id(self, series_id: str, recurrence_id: str) -> str | None:
        """The FamilyOS event a date moved out of a series became, if it is among the dates read.

        Home Assistant names such a date by its series and its original moment; in FamilyOS it is an event of
        its own and is changed as one.
        """
        known = self.data.occurrences if self.data else []
        return next(
            (o.event_id for o in known if o.series_id == series_id and instance_id(o, self.time_zone) == recurrence_id),
            None,
        )

    # --- writing ------------------------------------------------------------------------------------------

    async def async_write[T](self, answer: Awaitable[Applied[T] | Drafted], subject: str) -> Applied[T] | Drafted:
        """Wait for a write. A change that waits for approval is told to the family and changes nothing here.

        ``subject`` names what was asked for, in the family's own words (a title), for that notice.
        """
        try:
            outcome = await answer
        except AuthenticationError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
        except ForbiddenError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="forbidden", translation_placeholders={"message": str(err)}
            ) from err
        except (FamilyOSConnectionError, FamilyOSTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unreachable", translation_placeholders={"message": str(err)}
            ) from err
        except FamilyOSError as err:
            if isinstance(err, ConflictError):
                # The thing is not what we last saw; show what it is now.
                await self.async_refresh()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"message": str(err)},
            ) from err
        if isinstance(outcome, Drafted):
            await self._async_tell_waiting(outcome, subject)
        # A suggestion changes nothing here, but it is counted among the ones that wait.
        await self.async_refresh()
        return outcome

    async def _async_tell_waiting(self, drafted: Drafted, subject: str) -> None:
        translations = await async_get_translations(self.hass, self.hass.config.language, "exceptions", [DOMAIN])
        template = translations.get(
            f"component.{DOMAIN}.exceptions.waiting_for_approval.message",
            "Waiting for approval in FamilyOS: {subject}",
        )
        message = template.replace("{subject}", subject)
        LOGGER.info("%s (suggestion %s)", message, drafted.draft_id)
        persistent_notification.async_create(
            self.hass,
            message,
            title="FamilyOS",
            notification_id=f"{DOMAIN}_draft_{drafted.draft_id}",
        )
