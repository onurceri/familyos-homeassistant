"""The base of the FamilyOS entities."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FamilyOSConfigEntry, FamilyOSCoordinator


class FamilyOSEntity(CoordinatorEntity[FamilyOSCoordinator]):
    """An entity of the family's device. It is unavailable when FamilyOS cannot be reached or does not offer
    what it shows."""

    _attr_has_entity_name = True
    feature: str

    def __init__(self, coordinator: FamilyOSCoordinator, entry: FamilyOSConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FamilyOS",
            manufacturer="FamilyOS",
            model="Family",
            sw_version=coordinator.data.discovery.family_os if coordinator.data else None,
            configuration_url=str(entry.data["url"]),
        )

    @property
    def available(self) -> bool:
        """Whether FamilyOS answers and offers this."""
        return self.coordinator.has(self.feature)
