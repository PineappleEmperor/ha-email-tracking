"""Coordinator behaviour: push path, prune, persistence, merge, linking."""

from datetime import timedelta
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

AMAZON_ORDER = "123-4567890-1234567"


def _email(sender: str, subject: str, body: str, date: str) -> dict[str, Any]:
    return {"uid": 1, "sender": sender, "subject": subject, "body": body, "date": date}


def _amazon(subject: str, date: str) -> dict[str, Any]:
    return _email(
        "shipment-tracking@amazon.co.uk", subject, f"Order {AMAZON_ORDER}", date
    )


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


def _summary_state(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    eid = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_next_delivery"
    )
    assert eid is not None
    return str(hass.states.get(eid).attributes["active_count"])


async def test_push_event_ingests_parcel(hass: HomeAssistant) -> None:
    """A new-email event fetches the UID and creates a parcel."""
    state = register(hass)
    state["by_uid"]["5"] = [
        _amazon("Dispatched: order", "Fri, 04 Jul 2026 09:00:00 +0100")
    ]
    entry = await _setup(hass)
    coord = entry.runtime_data
    assert _summary_state(hass, entry) == "0"

    hass.bus.async_fire(EVENT_NEW_EMAIL, {"uid": 5, "config_entry_id": None})
    await hass.async_block_till_done()

    assert _summary_state(hass, entry) == "1"
    shipments = list(coord.data.values())
    assert len(shipments) == 1
    assert shipments[0].order_number == AMAZON_ORDER


async def test_prune_drops_old_delivered(hass: HomeAssistant) -> None:
    """A delivered parcel older than the retention window is pruned."""
    state = register(hass)
    old = dt_util.now() - timedelta(days=10)
    state["startup"] = [
        _email(
            "order-update@amazon.co.uk",
            "Delivered: order",
            "Order 111-2222222-3333333",
            old.strftime("%a, %d %b %Y %H:%M:%S %z"),
        )
    ]
    entry = await _setup(hass)
    coord = entry.runtime_data
    assert _summary_state(hass, entry) == "0"
    assert coord.data == {}


async def test_persistence_survives_reload(hass: HomeAssistant) -> None:
    """A tracked parcel is restored from the Store after a reload."""
    state = register(hass)
    state["startup"] = [_amazon("Dispatched: order", "Fri, 04 Jul 2026 09:00:00 +0100")]
    entry = await _setup(hass)
    assert _summary_state(hass, entry) == "1"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    # Inbox now empty — the parcel must come back from storage, not the scan.
    state["startup"] = []
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _summary_state(hass, entry) == "1"
    coord = entry.runtime_data
    shipments = list(coord.data.values())
    assert len(shipments) == 1
    assert shipments[0].order_number == AMAZON_ORDER


async def test_merge_dedupes_same_order(hass: HomeAssistant) -> None:
    """Two e-mails for one order yield a single, advanced parcel."""
    state = register(hass)
    state["startup"] = [
        _email(
            "auto-confirm@amazon.co.uk",
            "Ordered: order",
            f"Order {AMAZON_ORDER}",
            "Wed, 02 Jul 2026 09:00:00 +0100",
        ),
        _amazon("Dispatched: order", "Fri, 04 Jul 2026 09:00:00 +0100"),
    ]
    entry = await _setup(hass)
    coord = entry.runtime_data

    shipments = list(coord.data.values())
    assert len(shipments) == 1
    assert shipments[0].order_number == AMAZON_ORDER
    assert shipments[0].status == "Dispatched"


async def test_ingest_links_confirmation_and_courier(hass: HomeAssistant) -> None:
    """A Tubby Toms confirmation then a Royal Mail dispatch → one parcel."""
    state = register(hass)
    state["startup"] = [
        {
            "uid": 1,
            "sender": "info@tubbytoms.com",
            "subject": "Order #12345 received",
            "body": "thanks",
            "date": "Wed, 01 Jul 2026 09:00:00 +0100",
        },
        {
            "uid": 2,
            "sender": "no-reply@royalmail.com",
            "subject": "Your Royal Mail parcel from Tubby Toms Ltd. is on its way",
            "body": "Tracking AB123456789GB",
            "date": "Fri, 03 Jul 2026 09:00:00 +0100",
        },
    ]
    entry = await _setup(hass)
    coord = entry.runtime_data
    # one merged parcel with both ids, courier known
    shipments = list(coord.data.values())
    assert len(shipments) == 1
    assert shipments[0].order_number == "TubbyT-12345"
    assert shipments[0].tracking_number == "AB123456789GB"
    assert shipments[0].courier == "Royal Mail"


async def test_ingest_links_regardless_of_batch_order(hass: HomeAssistant) -> None:
    """Same pair with the courier e-mail listed first still yields one parcel."""
    state = register(hass)
    state["startup"] = [
        {
            "uid": 2,
            "sender": "no-reply@royalmail.com",
            "subject": "Your Royal Mail parcel from Tubby Toms Ltd. is on its way",
            "body": "Tracking AB123456789GB",
            "date": "Fri, 03 Jul 2026 09:00:00 +0100",
        },
        {
            "uid": 1,
            "sender": "info@tubbytoms.com",
            "subject": "Order #12345 received",
            "body": "thanks",
            "date": "Wed, 01 Jul 2026 09:00:00 +0100",
        },
    ]
    entry = await _setup(hass)
    coord = entry.runtime_data
    shipments = list(coord.data.values())
    assert len(shipments) == 1
    assert shipments[0].order_number == "TubbyT-12345"
    assert shipments[0].tracking_number == "AB123456789GB"
    assert shipments[0].courier == "Royal Mail"


async def test_multi_shipment_order_yields_two_parcels(hass: HomeAssistant) -> None:
    """One Amazon order split into two shipments stays two parcels."""
    state = register(hass)
    state["startup"] = [
        _email(
            "shipment-tracking@amazon.co.uk",
            "Dispatched: order",
            f"Order {AMAZON_ORDER} tracking number TRACKAAA11111",
            "Fri, 03 Jul 2026 09:00:00 +0100",
        ),
        _email(
            "shipment-tracking@amazon.co.uk",
            "Dispatched: order",
            f"Order {AMAZON_ORDER} tracking number TRACKBBB22222",
            "Fri, 04 Jul 2026 09:00:00 +0100",
        ),
    ]
    entry = await _setup(hass)
    shipments = list(entry.runtime_data.data.values())
    assert len(shipments) == 2
    assert {s.order_number for s in shipments} == {AMAZON_ORDER}
    assert {s.tracking_number for s in shipments} == {"TRACKAAA11111", "TRACKBBB22222"}
