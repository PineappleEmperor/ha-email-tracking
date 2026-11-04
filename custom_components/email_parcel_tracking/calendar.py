"""Calendar platform for the Email Parcel Tracking integration."""

from datetime import datetime, timedelta
from typing import override

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import TERMINAL_STATUSES
from .coordinator import ParcelTrackingConfigEntry, ParcelTrackingCoordinator
from .entity import ParcelTrackingEntity
from .models import Shipment

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParcelTrackingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the delivery calendar."""
    async_add_entities([ParcelCalendar(entry.runtime_data)])


class ParcelCalendar(ParcelTrackingEntity, CalendarEntity):
    """Expose parcel delivery ETAs as all-day calendar events."""

    _attr_translation_key = "deliveries"

    def __init__(self, coordinator: ParcelTrackingCoordinator) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_deliveries"

    @property
    @override
    def event(self) -> CalendarEvent | None:
        """The soonest delivery that has not fully passed, if any."""
        today = dt_util.now().date()
        upcoming = sorted(
            (evt for evt in self._events() if evt.end > today),
            key=lambda evt: evt.start,
        )
        return upcoming[0] if upcoming else None

    @override
    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return delivery events within the requested window."""
        start = start_date.date()
        end = end_date.date()
        return [event for event in self._events() if start <= event.start < end]

    def _events(self) -> list[CalendarEvent]:
        """Build a calendar event per active parcel with a known ETA."""
        return [
            self._to_event(shipment)
            for shipment in self.coordinator.data.values()
            if shipment.eta is not None and shipment.status not in TERMINAL_STATUSES
        ]

    def _to_event(self, shipment: Shipment) -> CalendarEvent:
        """Convert a shipment into an all-day calendar event."""
        assert shipment.eta is not None
        label = shipment.carrier_label or "Parcel"
        ident = shipment.order_number or shipment.tracking_number or shipment.uid
        return CalendarEvent(
            start=shipment.eta,
            end=shipment.eta + timedelta(days=1),
            summary=f"{label} parcel — {shipment.status}",
            description=f"Order {ident}",
            uid=f"{self._entry_id}_{shipment.uid}",
        )
