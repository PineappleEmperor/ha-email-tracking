"""Shared test helpers."""

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.email_parcel_tracking.const import (
    DOMAIN,
    EMAIL_DOMAIN,
    SERVICE_QUERY_EMAILS,
)

# Royal Mail, out for delivery today, with a tracking number.
RM_OUT_FOR_DELIVERY = {
    "uid": 2,
    "sender": "no-reply@royalmail.com",
    "subject": "Your parcel is due to be delivered today",
    "date": "Fri, 04 Jul 2026 08:00:00 +0100",
    "body": "Tracking AB123456789GB",
}


def register_email_service(hass: HomeAssistant, emails: list[dict[str, Any]]) -> None:
    """Register a stand-in for email_imap.query_emails returning ``emails``."""

    async def _handler(call: ServiceCall) -> dict[str, Any]:
        return {"emails": emails}

    hass.services.async_register(
        EMAIL_DOMAIN,
        SERVICE_QUERY_EMAILS,
        _handler,
        supports_response=SupportsResponse.ONLY,
    )


async def setup_entry(
    hass: HomeAssistant, emails: list[dict[str, Any]]
) -> MockConfigEntry:
    """Register the mocked boundary and load a config entry."""
    register_email_service(hass, emails)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
