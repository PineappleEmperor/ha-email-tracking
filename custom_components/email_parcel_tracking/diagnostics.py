"""Diagnostics support for the Email Parcel Tracking integration."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import ParcelTrackingConfigEntry

TO_REDACT = {"tracking_number", "order_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ParcelTrackingConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "shipments": [shipment.to_dict() for shipment in coordinator.data.values()],
        },
        TO_REDACT,
    )
