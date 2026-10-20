"""Sensors: the chores due today, the chores overdue and the suggestions that wait for a person."""

from collections.abc import Callable
from dataclasses import dataclass

from familyos import Chore
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import FEATURE_CHORES, FEATURE_DRAFTS
from .coordinator import FamilyData, FamilyOSConfigEntry, FamilyOSCoordinator
from .entity import FamilyOSEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ChoreSensorDescription(SensorEntityDescription):
    """A count of chores picked by a rule."""

    pick: Callable[[FamilyData], list[Chore]]


def _due_today(data: FamilyData) -> list[Chore]:
    return [chore for chore in data.chores if chore.next_due == data.today and not chore.overdue]


def _overdue(data: FamilyData) -> list[Chore]:
    return [chore for chore in data.chores if chore.overdue]


SENSORS = (
    ChoreSensorDescription(
        key="chores_due_today",
        translation_key="chores_due_today",
        state_class=SensorStateClass.MEASUREMENT,
        pick=_due_today,
    ),
    ChoreSensorDescription(
        key="chores_overdue",
        translation_key="chores_overdue",
        state_class=SensorStateClass.MEASUREMENT,
        pick=_overdue,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: FamilyOSConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """One sensor for each rule, and one for the waiting suggestions."""
    coordinator = entry.runtime_data
    async_add_entities(ChoreSensor(coordinator, entry, description) for description in SENSORS)
    async_add_entities([WaitingSensor(coordinator, entry)])


class ChoreSensor(FamilyOSEntity, SensorEntity):
    """How many chores are due today (or late). The titles are in the attributes."""

    feature = FEATURE_CHORES
    entity_description: ChoreSensorDescription

    def __init__(
        self, coordinator: FamilyOSCoordinator, entry: FamilyOSConfigEntry, description: ChoreSensorDescription
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def _chores(self) -> list[Chore]:
        return self.entity_description.pick(self.coordinator.data) if self.coordinator.data else []

    @property
    def native_value(self) -> int:
        """The number of chores."""
        return len(self._chores)

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        """Which chores."""
        return {"chores": [chore.title for chore in self._chores]}


class WaitingSensor(FamilyOSEntity, SensorEntity):
    """How many suggestions wait for a person to approve them in FamilyOS. What they are about is in the
    attributes. It is unavailable when the app's role may not propose."""

    feature = FEATURE_DRAFTS
    _attr_translation_key = "waiting_for_approval"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FamilyOSCoordinator, entry: FamilyOSConfigEntry) -> None:
        super().__init__(coordinator, entry, "waiting_for_approval")

    @property
    def native_value(self) -> int:
        """The number of suggestions."""
        return len(self.coordinator.data.drafts) if self.coordinator.data else 0

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        """What each is about: its subject, or what it suggests when it has none."""
        drafts = self.coordinator.data.drafts if self.coordinator.data else []
        return {"suggestions": [draft.subject or draft.title for draft in drafts]}
