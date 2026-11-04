"""Tests for the rescan service errors and the email-ha repair issue."""

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
)

from custom_components.email_parcel_tracking.const import (
    DOMAIN,
    EMAIL_DOMAIN,
    SERVICE_QUERY_EMAILS,
)
from custom_components.email_parcel_tracking.services import SERVICE_RESCAN

_ISSUE = "email_ha_missing"


@pytest.fixture
def ignore_translations_for_mock_domains() -> list[str]:
    """The query_emails stand-in plays Email HA, whose translations are not loaded."""
    return [EMAIL_DOMAIN]


def _register(hass: HomeAssistant) -> dict[str, Any]:
    """Register a controllable query_emails stand-in."""
    mock_integration(hass, MockModule(EMAIL_DOMAIN))
    state: dict[str, Any] = {"fail": False, "emails": []}

    async def _handler(call: ServiceCall) -> dict[str, Any]:
        if state["fail"]:
            raise HomeAssistantError(
                translation_domain=EMAIL_DOMAIN, translation_key="query_failed"
            )
        return {"emails": state["emails"]}

    hass.services.async_register(
        EMAIL_DOMAIN,
        SERVICE_QUERY_EMAILS,
        _handler,
        supports_response=SupportsResponse.ONLY,
    )
    return state


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_rescan_raises_when_query_fails(hass: HomeAssistant) -> None:
    """A failing rescan surfaces a HomeAssistantError, not a raw UpdateFailed."""
    state = _register(hass)
    await _setup(hass)
    state["fail"] = True
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_RESCAN, {}, blocking=True)


async def test_rescan_without_entries_raises(hass: HomeAssistant) -> None:
    """Rescanning with no loaded entry raises a validation error."""
    _register(hass)
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, SERVICE_RESCAN, {}, blocking=True)


async def test_repair_issue_raised_when_email_ha_missing(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Setup without email-ha retries and raises a repair issue."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert issue_registry.async_get_issue(DOMAIN, _ISSUE) is not None


async def test_repair_issue_absent_when_email_ha_present(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """A healthy setup leaves no repair issue."""
    _register(hass)
    await _setup(hass)
    assert issue_registry.async_get_issue(DOMAIN, _ISSUE) is None
