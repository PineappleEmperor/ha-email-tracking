"""The Email Parcel Tracking integration."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import AnyDeviceEntry
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import ParcelTrackingConfigEntry, ParcelTrackingCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# Config-entry-only integration — no YAML configuration keys.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-global services (once per process)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ParcelTrackingConfigEntry
) -> bool:
    """Set up Email Parcel Tracking from a config entry."""
    coordinator = ParcelTrackingCoordinator(hass, entry)
    await coordinator.async_prepare()
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ParcelTrackingConfigEntry
) -> bool:
    """Unload a config entry."""
    # The coordinator, built with config_entry=entry, registers its own shutdown.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ParcelTrackingConfigEntry, device_entry: AnyDeviceEntry
) -> bool:
    """Allow removing only a stale/foreign device row, never the live one."""
    return not any(
        domain == DOMAIN and ident == entry.entry_id
        for domain, ident in device_entry.identifiers
    )
