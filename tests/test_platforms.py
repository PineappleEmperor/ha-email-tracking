"""Behaviour tests for the calendar, button, rescan service, and sensors."""

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.email_parcel_tracking.const import (
    DOMAIN,
    EMAIL_DOMAIN,
    EVENT_NEW_EMAIL,
    SERVICE_QUERY_EMAILS,
)
from custom_components.email_parcel_tracking.services import SERVICE_RESCAN

from .helpers import RM_OUT_FOR_DELIVERY, setup_entry

TUBBY_CONFIRM = {
    "uid": 1,
    "sender": "info@tubbytoms.com",
    "subject": "Order #12345 received",
    "body": "thanks",
    "date": "Wed, 01 Jul 2026 09:00:00 +0100",
}
RM_DISPATCH_LINKED = {
    "uid": 2,
    "sender": "no-reply@royalmail.com",
    "subject": "Your Royal Mail parcel from Tubby Toms Ltd. is on its way",
    "body": "Tracking AB123456789GB. Arriving tomorrow.",
    "date": "Fri, 03 Jul 2026 09:00:00 +0100",
}
DPD_OFD_EMAIL = {
    "uid": 5,
    "sender": "yourdelivery@dpd.co.uk",
    "subject": "Your parcel will be delivered today between 10am and 12pm",
    "body": "Tracking 1234 5678 901 234",
    "date": "Fri, 04 Jul 2026 08:00:00 +0100",
}


def register(hass: HomeAssistant) -> dict[str, Any]:
    """Register a query_emails stand-in that branches on the search criteria."""
    state: dict[str, Any] = {"startup": [], "by_uid": {}}

    async def _handler(call: ServiceCall) -> dict[str, Any]:
        criteria = call.data.get("search_criteria", "")
        if criteria.startswith("UID"):
            return {"emails": state["by_uid"].get(criteria.split()[1], [])}
        return {"emails": state["startup"]}

    hass.services.async_register(
        EMAIL_DOMAIN,
        SERVICE_QUERY_EMAILS,
        _handler,
        supports_response=SupportsResponse.ONLY,
    )
    return state


async def _setup(
    hass: HomeAssistant, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _rm_out_for_delivery_today() -> dict[str, Any]:
    """Build a Royal Mail out-for-delivery e-mail dated "now" (any test day)."""
    now = dt_util.now()
    return {
        "uid": 2,
        "sender": "no-reply@royalmail.com",
        "subject": "Your parcel is due to be delivered today",
        "body": "Tracking AB123456789GB",
        "date": now.strftime("%a, %d %b %Y %H:%M:%S %z"),
    }


async def test_calendar_surfaces_active_delivery(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A parcel due today produces an active all-day calendar event."""
    entry = await setup_entry(hass, [_rm_out_for_delivery_today()])
    cal_id = entity_registry.async_get_entity_id(
        "calendar", DOMAIN, f"{entry.entry_id}_deliveries"
    )
    assert cal_id is not None
    assert hass.states.get(cal_id).state == "on"


async def test_rescan_button_press(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Pressing the rescan button records a timestamp without error."""
    entry = await setup_entry(hass, [RM_OUT_FOR_DELIVERY])
    button_id = entity_registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_rescan"
    )
    assert button_id is not None

    await hass.services.async_call(
        "button", "press", {"entity_id": button_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(button_id).state not in ("unknown", "unavailable")


async def test_rescan_service_rescans_all_entries(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """The rescan service re-queries and keeps the shipment set current."""
    entry = await setup_entry(hass, [RM_OUT_FOR_DELIVERY])
    await hass.services.async_call(DOMAIN, SERVICE_RESCAN, {}, blocking=True)
    await hass.async_block_till_done()
    nd_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_next_delivery"
    )
    assert hass.states.get(nd_id).attributes["active_count"] == 1


async def test_handler_sensor_next_eta_and_grouping(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A Tubby Toms confirmation + Royal Mail dispatch link under Royal Mail."""
    state = register(hass)
    state["startup"] = [TUBBY_CONFIRM, RM_DISPATCH_LINKED]
    entry = await _setup(hass)
    rm = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_handler_royal_mail"
    )
    assert rm and hass.states.get(rm).state != "unknown"

    tt = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_handler_tubby_toms"
    )
    assert entity_registry.async_get(tt).disabled_by is not None


async def test_total_next_delivery_sensor(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """The total sensor reports one active parcel with today's ETA."""
    entry = await setup_entry(hass, [RM_OUT_FOR_DELIVERY])
    next_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_next_delivery"
    )
    st = hass.states.get(next_id)
    assert st.attributes["active_count"] == 1


async def test_empty_handler_disabled_then_auto_enabled(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A handler with no startup parcels enables once one arrives via push."""
    state = register(hass)
    state["by_uid"]["5"] = [DPD_OFD_EMAIL]
    entry = await _setup(hass)
    dpd = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_handler_dpd"
    )
    assert (
        entity_registry.async_get(dpd).disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )

    hass.bus.async_fire(EVENT_NEW_EMAIL, {"uid": 5})
    await hass.async_block_till_done()

    assert entity_registry.async_get(dpd).disabled_by is None


async def test_per_parcel_sensor_disabled_by_default(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Per-parcel sensors are opt-in — disabled by default in the registry."""
    entry = await setup_entry(hass, [RM_OUT_FOR_DELIVERY])
    uid = next(iter(entry.runtime_data.data))
    pid = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_parcel_{uid}"
    )
    assert (
        entity_registry.async_get(pid).disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )
