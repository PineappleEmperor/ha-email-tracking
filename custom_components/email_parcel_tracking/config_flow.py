"""Config and options flow for the Email Parcel Tracking integration."""

from typing import Any, override

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
import probatio

from .const import (
    CONF_FOLDER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_LOOKBACK_DAYS,
    DEFAULT_FOLDER,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    DOMAIN,
)


class ParcelTrackingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup — a single instance, no credentials of its own."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Email Parcel Tracking", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return ParcelTrackingOptionsFlow()


class ParcelTrackingOptionsFlow(OptionsFlowWithReload):
    """Handle scan and retention options; the entry reloads when they change."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = probatio.Schema(
            {
                probatio.Required(
                    CONF_FOLDER,
                    default=options.get(CONF_FOLDER, DEFAULT_FOLDER),
                ): str,
                probatio.Required(
                    CONF_LOOKBACK_DAYS,
                    default=options.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS),
                ): probatio.All(int, probatio.Range(min=1, max=365)),
                probatio.Required(
                    CONF_KEEP_DELIVERED_DAYS,
                    default=options.get(
                        CONF_KEEP_DELIVERED_DAYS, DEFAULT_KEEP_DELIVERED_DAYS
                    ),
                ): probatio.All(int, probatio.Range(min=0, max=90)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
