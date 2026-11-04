"""Unit tests for the pure classification/parsing logic."""

from datetime import UTC, date, datetime

from custom_components.email_parcel_tracking import api
from custom_components.email_parcel_tracking.const import (
    STATUS_DELIVERED,
    STATUS_DISPATCHED,
    STATUS_ORDERED,
    STATUS_OUT_FOR_DELIVERY,
)
from custom_components.email_parcel_tracking.models import Shipment

REF = date(2026, 7, 4)


def test_classify_known_and_unknown() -> None:
    """Test classify known and unknown."""
    assert api.classify("shipment-tracking@amazon.co.uk", "Dispatched: X") == (
        "Amazon",
        STATUS_DISPATCHED,
    )
    assert api.classify("no-reply@royalmail.com", "is on its way") == (
        "Royal Mail",
        STATUS_DISPATCHED,
    )
    assert api.classify("friend@example.com", "hi") is None
    assert api.classify("shipment-tracking@amazon.co.uk", "unrelated") is None


def test_sender_address_extraction() -> None:
    """Test sender address extraction."""
    assert api.sender_address("Amazon <shipment-tracking@amazon.co.uk>") == (
        "shipment-tracking@amazon.co.uk"
    )
    assert api.sender_address(None) is None


def test_parse_amazon_dispatch() -> None:
    """Test parse amazon dispatch."""
    parsed = api.parse_email(
        {
            "sender": "shipment-tracking@amazon.co.uk",
            "subject": "Dispatched: Your order",
            "body": "Order 123-4567890-1234567 is on its way",
            "date": "Fri, 04 Jul 2026 09:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.order_number == "123-4567890-1234567"
    assert parsed.shipment.retailer == "Amazon"
    assert parsed.shipment.status == STATUS_DISPATCHED


def test_parse_royal_mail_out_for_delivery_sets_eta_today() -> None:
    """Test parse royal mail out for delivery sets eta today."""
    parsed = api.parse_email(
        {
            "sender": "no-reply@royalmail.com",
            "subject": "Your parcel is due to be delivered today",
            "body": "Tracking AB123456789GB",
            "date": "Fri, 04 Jul 2026 07:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.courier == "Royal Mail"
    assert parsed.shipment.status == STATUS_OUT_FOR_DELIVERY
    assert parsed.shipment.eta == REF
    assert parsed.shipment.tracking_number == "AB123456789GB"


def test_parse_eta_skips_non_month_matches() -> None:
    """Test parse eta skips non month matches."""
    # A tracking number ("...7 is") precedes the real date ("6 July"); the
    # parser must scan past the invalid month, not bail on the first match.
    eta = api.parse_eta("order 1234567 is arriving 6 July", REF, STATUS_DISPATCHED)
    assert eta == date(2026, 7, 6)


def test_parse_dpd_out_for_delivery() -> None:
    """Test parse dpd out for delivery."""
    parsed = api.parse_email(
        {
            "sender": "yourdelivery@dpd.co.uk",
            "subject": "Your parcel will be delivered today between 10:00 and 12:00",
            "body": "Your parcel: 1234 5678 123 123",
            "date": "Fri, 04 Jul 2026 06:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.courier == "DPD"
    assert parsed.shipment.status == STATUS_OUT_FOR_DELIVERY
    assert parsed.shipment.tracking_number == "1234 5678 123 123"


def test_parse_ups_dispatched() -> None:
    """Test parse ups dispatched."""
    parsed = api.parse_email(
        {
            "sender": "mcinfo@ups.com",
            "subject": "UPS Update: Parcel Scheduled for Delivery Tomorrow",
            "body": "Tracking 1Z12345E1512345676 details",
            "date": "Fri, 04 Jul 2026 06:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.courier == "UPS"
    assert parsed.shipment.status == STATUS_DISPATCHED
    assert parsed.shipment.tracking_number == "1Z12345E1512345676"


def test_parse_evri_delivered() -> None:
    """Test parse evri delivered."""
    parsed = api.parse_email(
        {
            "sender": "do-not-reply@evri.com",
            "subject": "Evri has successfully delivered your parcel",
            "body": "https://www.evri.com/track/parcel/H01ABC1234567890",
            "date": "Fri, 04 Jul 2026 06:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.courier == "Evri"
    assert parsed.shipment.status == STATUS_DELIVERED
    assert parsed.shipment.tracking_number == "H01ABC1234567890"


def test_parse_tubby_confirmation_sets_order_and_retailer() -> None:
    """Test parse tubby confirmation sets order and retailer."""
    parsed = api.parse_email(
        {
            "sender": "info@tubbytoms.com",
            "subject": "Order #12345 received",
            "body": "Thanks for your order",
            "date": "Wed, 01 Jul 2026 09:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.retailer == "Tubby Toms"
    assert parsed.shipment.order_number == "TubbyT-12345"
    assert parsed.shipment.tracking_number is None
    assert parsed.shipment.status == STATUS_ORDERED


def test_parse_royalmail_extracts_retailer_mention() -> None:
    """Test parse royalmail extracts retailer mention."""
    parsed = api.parse_email(
        {
            "sender": "no-reply@royalmail.com",
            "subject": "Your Royal Mail parcel from Tubby Toms Ltd. is on its way",
            "body": "Tracking AB123456789GB",
            "date": "Fri, 04 Jul 2026 08:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.courier == "Royal Mail"
    assert parsed.shipment.tracking_number == "AB123456789GB"
    assert parsed.retailer_name == "Tubby Toms Ltd."


def test_parse_rave_infers_shipper_from_postage() -> None:
    """Test parse rave infers shipper from postage."""
    parsed = api.parse_email(
        {
            "sender": "info@ravecoffee.co.uk",
            "subject": "A shipment from order #778 is on the way",
            "body": "Shipping: Royal Mail",
            "date": "Fri, 04 Jul 2026 08:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.retailer == "Rave"
    assert parsed.shipment.order_number == "778"
    assert parsed.shipment.courier == "Royal Mail"  # inferred


def test_parse_non_parcel_returns_none() -> None:
    """Test parse non parcel returns none."""
    assert (
        api.parse_email({"sender": "a@b.com", "subject": "hi", "body": ""}, REF) is None
    )


def test_parse_without_identifier_returns_none() -> None:
    """Test parse without identifier returns none."""
    # Known sender/subject but no order or tracking number -> untrackable.
    assert (
        api.parse_email(
            {
                "sender": "shipment-tracking@amazon.co.uk",
                "subject": "Dispatched: Your order",
                "body": "no identifiers here",
            },
            REF,
        )
        is None
    )


def test_carrier_label_prefers_courier() -> None:
    """Test carrier label prefers courier."""
    assert Shipment(retailer="Tubby Toms").carrier_label == "Tubby Toms"
    assert (
        Shipment(retailer="Tubby Toms", courier="Royal Mail").carrier_label
        == "Royal Mail"
    )
    assert Shipment().carrier_label is None


def test_merge_fills_ids_and_parties_and_advances_status() -> None:
    """Test merge fills ids and parties and advances status."""
    base = Shipment(
        uid="a",
        order_number="O1",
        retailer="Tubby Toms",
        status=STATUS_ORDERED,
        updated=datetime(2026, 7, 1, tzinfo=UTC),
    )
    base.merge(
        Shipment(
            tracking_number="AB123456789GB",
            courier="Royal Mail",
            status=STATUS_DISPATCHED,
            updated=datetime(2026, 7, 4, tzinfo=UTC),
        )
    )
    assert base.uid == "a"  # identity preserved
    assert base.order_number == "O1"
    assert base.tracking_number == "AB123456789GB"
    assert base.retailer == "Tubby Toms"
    assert base.courier == "Royal Mail"
    assert base.status == STATUS_DISPATCHED
    assert base.updated == datetime(2026, 7, 4, tzinfo=UTC)


def test_parse_dhl_generic_tracking() -> None:
    """Test parse dhl generic tracking."""
    # DHL has no dedicated pattern; the keyword-anchored generic finds the id.
    parsed = api.parse_email(
        {
            "sender": "NoReply.ODD@dhl.com",
            "subject": "Your Shipment Is On Its Way",
            "body": "Waybill No. 1234567890 for your parcel",
            "date": "Fri, 04 Jul 2026 09:00:00 +0100",
        },
        REF,
    )
    assert parsed is not None
    assert parsed.shipment.courier == "DHL"
    assert parsed.shipment.status == STATUS_DISPATCHED
    assert parsed.shipment.tracking_number == "1234567890"


def test_generic_tracking_requires_a_keyword() -> None:
    """Test generic tracking requires a keyword."""
    # An id with no tracking keyword must NOT be mistaken for the parcel id
    # (the old unanchored generic grabbed URL/campaign junk).
    shipment = api.parse_email(
        {
            "sender": "NoReply.ODD@dhl.com",
            "subject": "Your Shipment Is On Its Way",
            "body": "reference AB1234567890 here",
            "date": "Fri, 04 Jul 2026 09:00:00 +0100",
        },
        REF,
    )
    assert shipment is None


def test_parse_eta_rolls_inferred_past_year_forward() -> None:
    """Test parse eta rolls inferred past year forward."""
    # "2 January" seen on 30 December is next year, not a past date.
    eta = api.parse_eta("arriving 2 January", date(2026, 12, 30), STATUS_DISPATCHED)
    assert eta == date(2027, 1, 2)


def test_merge_keeps_newer_timestamp_only() -> None:
    """Test merge keeps newer timestamp only."""
    newer = datetime(2026, 7, 4, tzinfo=UTC)
    s = Shipment(uid="a", status=STATUS_DISPATCHED, updated=newer)
    s.merge(Shipment(updated=datetime(2026, 7, 1, tzinfo=UTC)))
    assert s.updated == newer


def test_shipment_roundtrip_includes_uid_and_dual_ids() -> None:
    """Test shipment roundtrip includes uid and dual ids."""
    s = Shipment(
        uid="u1",
        order_number="O1",
        tracking_number="T1",
        retailer="Amazon",
        courier=None,
        status=STATUS_DELIVERED,
        eta=date(2026, 7, 6),
        updated=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert Shipment.from_dict(s.to_dict()) == s
