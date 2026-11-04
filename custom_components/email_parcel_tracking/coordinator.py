"""Data coordinator for the Email Parcel Tracking integration."""

from collections.abc import Mapping
from datetime import datetime, timedelta
import logging
from typing import Any, cast, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceNotFound,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .api import ParsedEmail, parse_email
from .const import (
    CONF_FOLDER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_LOOKBACK_DAYS,
    DEFAULT_FOLDER,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    DOMAIN,
    EMAIL_DOMAIN,
    EVENT_NEW_EMAIL,
    KNOWN_SENDERS,
    SERVICE_QUERY_EMAILS,
    STORAGE_KEY,
    STORAGE_VERSION,
    TERMINAL_STATUSES,
)
from .linking import find_match
from .models import Shipment

_LOGGER = logging.getLogger(__name__)

_MAX_RESULTS = 50
_ISSUE_EMAIL_HA_MISSING = "email_ha_missing"

type ParcelTrackingConfigEntry = ConfigEntry[ParcelTrackingCoordinator]


# Push model: subscribes to ``email_imap_new_email`` and updates on each new
# e-mail. ``_async_update_data`` runs the one-off startup inbox scan via the
# ``email_imap.query_emails`` service.
class ParcelTrackingCoordinator(DataUpdateCoordinator[dict[str, Shipment]]):
    """Aggregate parcel e-mails into a set of tracked shipments."""

    config_entry: ParcelTrackingConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ParcelTrackingConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=None,
        )
        self._store: Store[list[dict[str, str | None]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._shipments: dict[str, Shipment] = {}

    @property
    def folder(self) -> str:
        """The IMAP folder to scan."""
        return str(self.config_entry.options.get(CONF_FOLDER, DEFAULT_FOLDER))

    @property
    def lookback_days(self) -> int:
        """How far back the startup scan reaches."""
        return int(
            self.config_entry.options.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS)
        )

    @property
    def keep_delivered_days(self) -> int:
        """How long a delivered/exception parcel is retained."""
        return int(
            self.config_entry.options.get(
                CONF_KEEP_DELIVERED_DAYS, DEFAULT_KEEP_DELIVERED_DAYS
            )
        )

    async def async_prepare(self) -> None:
        """Load persisted shipments and subscribe to new-email events."""
        self._shipments = {}
        for item in await self._store.async_load() or []:
            shipment = Shipment.from_dict(item)
            if not shipment.uid:
                shipment.uid = ulid_now()
            self._shipments[shipment.uid] = shipment
        self.config_entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_NEW_EMAIL, self._handle_new_email)
        )

    @override
    async def _async_update_data(self) -> dict[str, Shipment]:
        """Perform the startup inbox scan for known parcel senders."""
        if not self.hass.services.has_service(EMAIL_DOMAIN, SERVICE_QUERY_EMAILS):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                _ISSUE_EMAIL_HA_MISSING,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=_ISSUE_EMAIL_HA_MISSING,
            )
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN, translation_key="email_ha_unavailable"
            )
        ir.async_delete_issue(self.hass, DOMAIN, _ISSUE_EMAIL_HA_MISSING)
        emails = await self._query(self._startup_criteria())
        self._ingest(emails)
        self._prune()
        await self._persist()
        return dict(self._shipments)

    async def async_rescan(self) -> None:
        """Re-scan the inbox on demand and push the result."""
        emails = await self._query(self._startup_criteria())
        self._ingest(emails)
        self._prune()
        await self._persist()
        self.async_set_updated_data(dict(self._shipments))

    @callback
    def _handle_new_email(self, event: Event) -> None:
        """React to a pushed new-email event from email-ha."""
        self.hass.async_create_task(self._ingest_uid(event.data))

    async def _ingest_uid(self, data: Mapping[str, Any]) -> None:
        """Fetch the full body for one pushed e-mail and ingest it."""
        uid = data.get("uid")
        if uid is None:
            return
        try:
            emails = await self._query(f"UID {uid}")
        except UpdateFailed as err:
            # A pushed event fires once — a dropped fetch loses this parcel
            # until the next rescan, so surface it rather than hiding at debug.
            _LOGGER.warning("Could not fetch pushed e-mail %s: %s", uid, err)
            return
        if self._ingest(emails):
            self._prune()
            await self._persist()
            self.async_set_updated_data(dict(self._shipments))

    def _startup_criteria(self) -> str:
        """IMAP criteria: any known sender within the lookback window."""
        since = (dt_util.now() - timedelta(days=self.lookback_days)).strftime(
            "%d-%b-%Y"
        )
        return f"SINCE {since} {_or_from(KNOWN_SENDERS)}"

    async def _query(self, criteria: str) -> list[dict[str, Any]]:
        """Call ``email_imap.query_emails`` and return the e-mail list."""
        payload: dict[str, Any] = {
            "folder": self.folder,
            "search_criteria": criteria,
            "max_results": _MAX_RESULTS,
            "include_full_body": True,
        }
        try:
            response = await self.hass.services.async_call(
                EMAIL_DOMAIN,
                SERVICE_QUERY_EMAILS,
                payload,
                blocking=True,
                return_response=True,
            )
        except (ServiceNotFound, HomeAssistantError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="query_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if response is None:
            return []
        emails = response.get("emails")
        if not isinstance(emails, list):
            # A present-but-malformed response is an upstream contract change,
            # not an empty inbox — don't silently treat it as "no parcels".
            _LOGGER.warning(
                "Unexpected query_emails response; no 'emails' list present"
            )
            return []
        # query_emails returns an untyped JSON list of e-mail objects.
        return cast("list[dict[str, Any]]", emails)

    def _ingest(self, emails: list[dict[str, Any]]) -> bool:
        """Parse and link e-mails into the shipment set; return if changed."""
        # Oldest-first, so a retailer confirmation is always ingested before a
        # courier e-mail from later in the same batch; otherwise a courier
        # e-mail processed first finds no confirmation to link against and
        # creates a duplicate parcel.
        ref = dt_util.now().date()
        parsed = [
            p for p in (parse_email(email, ref) for email in emails) if p is not None
        ]
        parsed.sort(key=_by_email_date)
        changed = False
        for item in parsed:
            uid = find_match(
                self._shipments.values(), item.shipment, item.retailer_name
            )
            if uid is not None:
                self._shipments[uid].merge(item.shipment)
            else:
                new_uid = ulid_now()
                item.shipment.uid = new_uid
                self._shipments[new_uid] = item.shipment
            changed = True
        return changed

    def _prune(self) -> None:
        """Drop delivered/exception parcels past the retention window."""
        cutoff = dt_util.now() - timedelta(days=self.keep_delivered_days)
        stale = [
            uid
            for uid, shipment in self._shipments.items()
            if shipment.status in TERMINAL_STATUSES
            and shipment.updated is not None
            and shipment.updated < cutoff
        ]
        for uid in stale:
            del self._shipments[uid]

    async def _persist(self) -> None:
        """Save the current shipment set to the Store."""
        await self._store.async_save(
            [shipment.to_dict() for shipment in self._shipments.values()]
        )


def _by_email_date(item: ParsedEmail) -> datetime:
    """Sort key: the e-mail date, always set on ``shipment.updated``."""
    assert item.shipment.updated is not None
    return item.shipment.updated


def _or_from(addresses: tuple[str, ...]) -> str:
    """Build a nested IMAP ``OR FROM`` expression across all addresses."""
    criteria = [f'FROM "{addr}"' for addr in addresses]
    expression = criteria[0]
    for term in criteria[1:]:
        expression = f"OR {term} {expression}"
    return expression
