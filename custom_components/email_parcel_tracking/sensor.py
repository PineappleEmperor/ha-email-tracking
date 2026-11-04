"""Sensor platform for the Email Parcel Tracking integration."""

from datetime import datetime
from typing import Any, override

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HANDLER_LABELS, HANDLER_SLUGS, STATUSES, TERMINAL_STATUSES
from .coordinator import ParcelTrackingConfigEntry, ParcelTrackingCoordinator
from .entity import ParcelTrackingEntity
from .models import Shipment

PARALLEL_UPDATES = 0


def _active(shipments: list[Shipment], label: str | None = None) -> list[Shipment]:
    """Return non-terminal shipments, optionally filtered to one handler."""
    items = [s for s in shipments if s.status not in TERMINAL_STATUSES]
    if label is not None:
        items = [s for s in items if s.carrier_label == label]
    today = dt_util.utcnow().date()
    return sorted(items, key=lambda s: (s.eta is None, s.eta or today))


def _eta_ts(shipment: Shipment | None) -> datetime | None:
    """Return the shipment ETA as a local-midnight timestamp, if any."""
    if shipment is None or shipment.eta is None:
        return None
    return dt_util.start_of_local_day(shipment.eta)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParcelTrackingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the total, per-handler, and opt-in per-parcel sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [ParcelNextDeliverySensor(coordinator)]
    entities += [ParcelHandlerSensor(coordinator, label) for label in HANDLER_LABELS]
    async_add_entities(entities)

    tracked: set[str] = set()

    @callback
    def _sync() -> None:
        """Add newly-seen per-parcel sensors and auto-enable active handlers."""
        new = [uid for uid in coordinator.data if uid not in tracked]
        if new:
            tracked.update(new)
            async_add_entities(ParcelSensor(coordinator, uid, tracked) for uid in new)
        reg = er.async_get(hass)
        for label in HANDLER_LABELS:
            if not _active(list(coordinator.data.values()), label):
                continue
            eid = reg.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_handler_{HANDLER_SLUGS[label]}"
            )
            if eid is None:
                continue
            row = reg.async_get(eid)
            if row and row.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                reg.async_update_entity(eid, disabled_by=None)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class ParcelNextDeliverySensor(ParcelTrackingEntity, SensorEntity):
    """The soonest active delivery across every handler."""

    _attr_translation_key = "next_delivery"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ParcelTrackingCoordinator) -> None:
        """Initialize the total next-delivery sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_next_delivery"

    @property
    @override
    def native_value(self) -> datetime | None:
        """ETA of the soonest active parcel, if any."""
        active = _active(list(self.coordinator.data.values()))
        return _eta_ts(active[0]) if active else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Counts and details of every active parcel, grouped by carrier."""
        items = list(self.coordinator.data.values())
        active = _active(items)
        by_carrier: dict[str, int] = {}
        for s in active:
            key = s.carrier_label or "unknown"
            by_carrier[key] = by_carrier.get(key, 0) + 1
        return {
            "active_count": len(active),
            "next_carrier": active[0].carrier_label if active else None,
            "by_carrier": by_carrier,
            "parcels": [s.to_dict() for s in active],
        }


class ParcelHandlerSensor(ParcelTrackingEntity, SensorEntity):
    """The soonest active delivery for a single carrier/retailer handler."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ParcelTrackingCoordinator, label: str) -> None:
        """Initialize the handler sensor; disabled by default until active."""
        super().__init__(coordinator)
        self._label = label
        self._attr_translation_key = HANDLER_SLUGS[label]
        self._attr_unique_id = f"{self._entry_id}_handler_{HANDLER_SLUGS[label]}"
        self._attr_entity_registry_enabled_default = bool(
            _active(list(coordinator.data.values()), label)
        )

    @property
    @override
    def native_value(self) -> datetime | None:
        """ETA of the soonest active parcel for this handler, if any."""
        active = _active(list(self.coordinator.data.values()), self._label)
        return _eta_ts(active[0]) if active else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details of every active parcel for this handler."""
        active = _active(list(self.coordinator.data.values()), self._label)
        return {
            "active_count": len(active),
            "current": active[0].to_dict() if active else None,
            "parcels": [s.to_dict() for s in active],
        }


class ParcelSensor(ParcelTrackingEntity, SensorEntity):
    """A single tracked parcel; opt-in, disabled by default."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: ParcelTrackingCoordinator, uid: str, tracked: set[str]
    ) -> None:
        """Initialize a per-parcel sensor."""
        super().__init__(coordinator)
        self._uid = uid
        self._tracked = tracked
        self._removing = False
        self._attr_unique_id = f"{self._entry_id}_parcel_{uid}"

    @property
    @override
    def available(self) -> bool:
        """Available while the parcel is still tracked."""
        return super().available and self._uid in self.coordinator.data

    @property
    @override
    def name(self) -> str:
        """Human label: carrier plus the order/tracking identifier."""
        shipment = self.coordinator.data.get(self._uid)
        label = (shipment.carrier_label if shipment else None) or "Parcel"
        ident = (
            (shipment.order_number or shipment.tracking_number) if shipment else None
        ) or self._uid
        return f"{label} {ident}"

    @property
    @override
    def native_value(self) -> str | None:
        """Current delivery status."""
        shipment = self.coordinator.data.get(self._uid)
        return shipment.status if shipment else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Parcel details."""
        shipment = self.coordinator.data.get(self._uid)
        return shipment.to_dict() if shipment else {}

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Remove the entity once its parcel is pruned."""
        if self._uid not in self.coordinator.data:
            if not self._removing:
                self._removing = True
                self._tracked.discard(self._uid)
                self.hass.async_create_task(self.async_remove(force_remove=True))
            return
        super()._handle_coordinator_update()
