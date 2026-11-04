"""Setup/unload tests — mock only the email-ha service boundary."""

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.email_parcel_tracking import async_remove_config_entry_device
from custom_components.email_parcel_tracking.const import (
    DOMAIN,
    EMAIL_DOMAIN,
    SERVICE_QUERY_EMAILS,
)

AMAZON_EMAIL = {
    "uid": 1,
    "sender": "shipment-tracking@amazon.co.uk",
    "subject": "Dispatched: Your order",
    "date": "Fri, 04 Jul 2026 09:00:00 +0100",
    "body": "Order 123-4567890-1234567 is on its way",
}


def _register_email_service(hass: HomeAssistant, emails: list[dict[str, Any]]) -> None:
    """Register a stand-in for email_imap.query_emails returning ``emails``."""

    async def _handler(call: ServiceCall) -> dict[str, Any]:
        return {"emails": emails}

    hass.services.async_register(
        EMAIL_DOMAIN,
        SERVICE_QUERY_EMAILS,
        _handler,
        supports_response=SupportsResponse.ONLY,
    )


async def test_setup_entry_loaded_creates_entities(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A real config-entry setup loads and ingests the startup scan."""
    _register_email_service(hass, [AMAZON_EMAIL])
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    summary_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_next_delivery"
    )
    assert summary_id is not None
    assert hass.states.get(summary_id).attributes["active_count"] == 1

    coordinator = entry.runtime_data
    uid = next(iter(coordinator.data))
    parcel_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_parcel_{uid}"
    )
    assert parcel_id is not None
    # Per-parcel sensors are opt-in — disabled by default, so no state.
    assert (
        entity_registry.async_get(parcel_id).disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_setup_retries_without_email_ha(hass: HomeAssistant) -> None:
    """Absent the email_imap service, setup goes to retry (ConfigEntryNotReady)."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(hass: HomeAssistant) -> None:
    """A loaded entry unloads cleanly."""
    _register_email_service(hass, [])
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_device_created_and_entities_linked(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry
) -> None:
    """Setting up an entry registers a device keyed by the entry id."""
    _register_email_service(hass, [AMAZON_EMAIL])
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None


async def test_remove_config_entry_device(hass: HomeAssistant) -> None:
    """Only a stale/foreign device row may be removed, never the live one."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    live = dr.DeviceEntry(
        identifiers={(DOMAIN, entry.entry_id)}, config_entry_id=entry.entry_id
    )
    foreign = dr.DeviceEntry(
        identifiers={(DOMAIN, "other")}, config_entry_id=entry.entry_id
    )
    assert await async_remove_config_entry_device(hass, entry, live) is False
    assert await async_remove_config_entry_device(hass, entry, foreign) is True
