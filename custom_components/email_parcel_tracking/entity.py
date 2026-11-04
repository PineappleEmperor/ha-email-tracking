"""Shared base entity for the Email Parcel Tracking integration."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ParcelTrackingCoordinator


class ParcelTrackingEntity(CoordinatorEntity[ParcelTrackingCoordinator]):
    """Base entity wiring the coordinator and entity naming."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ParcelTrackingCoordinator) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self._entry_id = coordinator.config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Email Parcel Tracking",
            manufacturer="Email Parcel Tracking",
            model="Mailbox parcel tracker",
            entry_type=DeviceEntryType.SERVICE,
        )
