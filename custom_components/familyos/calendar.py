"""The family calendar."""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from familyos import Occurrence
from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, FEATURE_CALENDAR
from .coordinator import FamilyOSConfigEntry, FamilyOSCoordinator
from .entity import FamilyOSEntity
from .rules import recurrence_from_rrule, same_repeat

PARALLEL_UPDATES = 0

_THIS_AND_FUTURE = "THIS_AND_FUTURE"


async def async_setup_entry(
    hass: HomeAssistant, entry: FamilyOSConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """One calendar for the family."""
    async_add_entities([FamilyCalendar(entry.runtime_data, entry)])


def _plain_moment(value: dt.datetime | dt.date, zone: ZoneInfo) -> dt.datetime | dt.date:
    return value.astimezone(zone) if isinstance(value, dt.datetime) else value


def to_calendar_event(occurrence: Occurrence, zone: ZoneInfo, rrule: str | None = None) -> CalendarEvent:
    """One date of an event as Home Assistant shows it.

    FamilyOS ends an all-day event on its last day; Home Assistant ends it the day after.
    """
    start = _plain_moment(occurrence.start, zone)
    end = _plain_moment(occurrence.end, zone)
    if occurrence.all_day and isinstance(end, dt.date) and not isinstance(end, dt.datetime):
        end = end + dt.timedelta(days=1)
    return CalendarEvent(
        start=start,
        end=end,
        summary=occurrence.title,
        description=occurrence.notes,
        location=occurrence.location,
        uid=occurrence.event_id,
        # Only a date of a repeating series is named by its place in the series. A date that was moved is an
        # event of its own in FamilyOS and is changed as one.
        recurrence_id=occurrence.recurrence_id.isoformat() if occurrence.recurring else None,
        rrule=rrule,
    )


class FamilyCalendar(FamilyOSEntity, CalendarEntity):
    """The family's events, repeating ones expanded. It can add, change and delete them."""

    feature = FEATURE_CALENDAR
    _attr_translation_key = "family"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, coordinator: FamilyOSCoordinator, entry: FamilyOSConfigEntry) -> None:
        super().__init__(coordinator, entry, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        """The event that is on now, or else the next one."""
        data = self.coordinator.data
        if data is None:
            return None
        now = dt_util.now()
        coming = [
            event
            for event in (to_calendar_event(occurrence, data.time_zone) for occurrence in data.occurrences)
            if event.end_datetime_local > now
        ]
        coming.sort(key=lambda event: (event.start_datetime_local, event.end_datetime_local))
        return coming[0] if coming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: dt.datetime, end_date: dt.datetime
    ) -> list[CalendarEvent]:
        """The events that touch the window."""
        zone = self.coordinator.time_zone
        first = start_date.astimezone(zone).date()
        last = (end_date.astimezone(zone) - dt.timedelta(microseconds=1)).date()
        events: list[CalendarEvent] = []
        async for occurrence in self.coordinator.client.iter_occurrences(first, max(first, last), limit=500):
            rrule = await self.coordinator.async_rrule(occurrence.event_id) if occurrence.recurring else None
            event = to_calendar_event(occurrence, zone, rrule)
            if event.end_datetime_local > start_date and event.start_datetime_local < end_date:
                events.append(event)
        return events

    # --- writing ------------------------------------------------------------------------------------------

    def _when(self, start: dt.datetime | dt.date, end: dt.datetime | dt.date | None) -> dict[str, Any]:
        """FamilyOS' fields for a start and an end (an all-day end is the day after its last day)."""
        zone = self.coordinator.time_zone
        if not isinstance(start, dt.datetime):
            last = (end - dt.timedelta(days=1)) if isinstance(end, dt.date) and end > start else start
            return {
                "all_day": True,
                "date": start,
                "end_date": last if last > start else None,
                "start_time": None,
                "end_time": None,
            }
        begin = start.astimezone(zone)
        finish = end.astimezone(zone) if isinstance(end, dt.datetime) else begin
        return {
            "all_day": False,
            "date": begin.date(),
            "end_date": finish.date() if finish.date() != begin.date() else None,
            "start_time": begin.time().replace(second=0, microsecond=0, tzinfo=None),
            "end_time": finish.time().replace(second=0, microsecond=0, tzinfo=None),
        }

    async def async_create_event(self, **kwargs: Any) -> None:
        """Add an event."""
        fields = self._when(kwargs["dtstart"], kwargs.get("dtend"))
        recurrence = None
        if kwargs.get("rrule"):
            try:
                recurrence = recurrence_from_rrule(kwargs["rrule"])
            except ValueError as err:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="repeat_unsupported") from err
        title: str = kwargs["summary"]
        await self.coordinator.async_write(
            self.coordinator.client.create_event(
                title,
                fields.pop("date"),
                location=kwargs.get("location"),
                notes=kwargs.get("description"),
                recurrence=recurrence,
                **fields,
            ),
            subject=title,
        )

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Change an event, or one date of a repeating one."""
        if recurrence_range == _THIS_AND_FUTURE:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="following_unsupported")
        client = self.coordinator.client
        current = await client.get_event(uid)
        if event.get("rrule") and not same_repeat(event["rrule"], current.recurrence):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="repeat_change_unsupported")
        changes: dict[str, Any] = {}
        if "summary" in event:
            changes["title"] = event["summary"]
        if "description" in event:
            changes["notes"] = event["description"] or None
        if "location" in event:
            changes["location"] = event["location"] or None
        if "dtstart" in event:
            fields = self._when(event["dtstart"], event.get("dtend"))
            if fields["all_day"]:
                del fields["start_time"]
            if recurrence_id is None:
                # Fields that already have the value are left out: a change of the date of a whole series
                # would otherwise look to FamilyOS like moving it.
                already = {
                    "all_day": current.all_day,
                    "date": current.date,
                    "end_date": current.end_date,
                    "start_time": current.start_time,
                    "end_time": current.end_time,
                }
                fields = {name: value for name, value in fields.items() if already[name] != value}
            changes.update(fields)
        subject = str(event.get("summary") or current.title)
        await self.coordinator.async_write(
            client.patch_event(uid, occurrence=recurrence_id, if_match=current.version, **changes), subject=subject
        )

    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        """Delete an event, or one date of a repeating one."""
        if recurrence_range == _THIS_AND_FUTURE:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="following_unsupported")
        known = self.coordinator.data.occurrences if self.coordinator.data else []
        subject = next((o.title for o in known if o.event_id == uid), uid)
        await self.coordinator.async_write(
            self.coordinator.client.delete_event(uid, occurrence=recurrence_id), subject=subject
        )
