"""End-to-end parse+link test over redacted e-mail fixtures."""

from homeassistant.util import dt as dt_util

from custom_components.email_parcel_tracking.api import parse_email
from custom_components.email_parcel_tracking.linking import find_match

from .fixtures_loader import load_flow


def test_tubby_royalmail_flow_links_to_one_parcel() -> None:
    """Test tubby royalmail flow links to one parcel."""
    emails = load_flow("tubby_royalmail")
    ref = dt_util.now().date()
    shipments = {}
    for email in emails:
        parsed = parse_email(email, ref)
        assert parsed is not None
        uid = find_match(shipments.values(), parsed.shipment, parsed.retailer_name)
        if uid:
            shipments[uid].merge(parsed.shipment)
        else:
            parsed.shipment.uid = f"u{len(shipments)}"
            shipments[parsed.shipment.uid] = parsed.shipment
    assert len(shipments) == 1
    only = next(iter(shipments.values()))
    assert only.order_number == "TubbyT-12345"
    assert only.tracking_number == "AB123456789GB"
    assert only.courier == "Royal Mail"
