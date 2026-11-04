"""Diagnostics redaction test."""

from homeassistant.core import HomeAssistant

from custom_components.email_parcel_tracking.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import RM_OUT_FOR_DELIVERY, setup_entry

# Amazon dispatch e-mail carrying both an order number and a tracking number.
_AMAZON_DISPATCH_WITH_TRACKING = {
    "uid": 9,
    "sender": "shipment-tracking@amazon.co.uk",
    "subject": "Dispatched: Your order",
    "date": "Fri, 04 Jul 2026 09:00:00 +0100",
    "body": "Order 123-4567890-1234567 is on its way, tracking number TRACK12345678",
}


async def test_diagnostics_redacts_tracking_number(hass: HomeAssistant) -> None:
    """The tracking number is redacted; non-secret fields are preserved."""
    entry = await setup_entry(hass, [RM_OUT_FOR_DELIVERY])
    result = await async_get_config_entry_diagnostics(hass, entry)

    shipments = result["shipments"]
    assert shipments
    assert shipments[0]["tracking_number"] == "**REDACTED**"
    assert shipments[0]["status"] == "Out for delivery"
    assert "entry" in result


async def test_diagnostics_redacts_order_number(hass: HomeAssistant) -> None:
    """The order number is redacted alongside the tracking number."""
    entry = await setup_entry(hass, [_AMAZON_DISPATCH_WITH_TRACKING])
    result = await async_get_config_entry_diagnostics(hass, entry)

    shipments = result["shipments"]
    assert shipments
    assert shipments[0]["order_number"] == "**REDACTED**"
    assert shipments[0]["tracking_number"] == "**REDACTED**"
    assert shipments[0]["status"] == "Dispatched"
