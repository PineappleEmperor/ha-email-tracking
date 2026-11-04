"""Services for the Email Parcel Tracking integration."""

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN

SERVICE_RESCAN = "rescan"


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent across config entries)."""
    if hass.services.has_service(DOMAIN, SERVICE_RESCAN):
        return

    async def _handle_rescan(call: ServiceCall) -> None:
        """Re-scan the inbox for every loaded config entry."""
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_loaded"
            )
        for entry in entries:
            try:
                await entry.runtime_data.async_rescan()
            except UpdateFailed as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="rescan_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

    hass.services.async_register(DOMAIN, SERVICE_RESCAN, _handle_rescan)
