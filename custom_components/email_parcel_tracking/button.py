"""Button platform for the Email Parcel Tracking integration."""

from typing import override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ParcelTrackingConfigEntry, ParcelTrackingCoordinator
from .entity import ParcelTrackingEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParcelTrackingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the rescan button."""
    async_add_entities([ParcelRescanButton(entry.runtime_data)])


class ParcelRescanButton(ParcelTrackingEntity, ButtonEntity):
    """Trigger an immediate inbox rescan."""

    _attr_translation_key = "rescan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ParcelTrackingCoordinator) -> None:
        """Initialize the rescan button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_rescan"

    @override
    async def async_press(self) -> None:
        """Rescan the inbox now."""
        await self.coordinator.async_rescan()
