"""Tests for the pure retailer-to-courier linking module."""

from datetime import UTC, date, datetime

from custom_components.email_parcel_tracking.linking import (
    find_match,
    normalize_retailer,
)
from custom_components.email_parcel_tracking.models import Shipment


def _conf(uid, retailer, eta=None, updated=None):
    return Shipment(
        uid=uid,
        order_number=f"{retailer}-1",
        retailer=retailer,
        status="Ordered",
        eta=eta,
        updated=updated,
    )


def test_normalize_strips_suffixes() -> None:
    """Test normalize strips suffixes."""
    assert normalize_retailer("Tubby Toms Ltd.") == "tubby toms"
    assert normalize_retailer("RAVE Limited") == "rave"
    assert normalize_retailer(None) is None


def test_match_on_order_number() -> None:
    """Test match on order number."""
    existing = [_conf("a", "Tubby Toms")]
    incoming = Shipment(order_number="Tubby Toms-1", retailer="Tubby Toms")
    assert find_match(existing, incoming, None) == "a"


def test_match_on_tracking_number() -> None:
    """Test match on tracking number."""
    existing = [
        Shipment(uid="a", tracking_number="AB123456789GB", courier="Royal Mail")
    ]
    incoming = Shipment(tracking_number="AB123456789GB", courier="Royal Mail")
    assert find_match(existing, incoming, None) == "a"


def test_fuzzy_link_on_name_and_eta_window() -> None:
    """Test fuzzy link on name and eta window."""
    existing = [_conf("a", "Tubby Toms", eta=date(2026, 7, 6))]
    incoming = Shipment(
        tracking_number="AB123456789GB", courier="Royal Mail", eta=date(2026, 7, 7)
    )
    assert find_match(existing, incoming, "Tubby Toms Ltd.") == "a"


def test_no_link_when_eta_outside_window() -> None:
    """Test no link when eta outside window."""
    existing = [_conf("a", "Tubby Toms", eta=date(2026, 7, 6))]
    incoming = Shipment(
        tracking_number="T", courier="Royal Mail", eta=date(2026, 7, 20)
    )
    assert find_match(existing, incoming, "Tubby Toms Ltd.") is None


def test_no_link_when_two_candidates() -> None:
    """Test no link when two candidates."""
    existing = [
        _conf("a", "Tubby Toms", eta=date(2026, 7, 6)),
        _conf("b", "Tubby Toms", eta=date(2026, 7, 6)),
    ]
    incoming = Shipment(tracking_number="T", courier="Royal Mail", eta=date(2026, 7, 6))
    assert find_match(existing, incoming, "Tubby Toms Ltd.") is None


def test_fuzzy_link_recency_when_confirmation_has_no_eta() -> None:
    """Test fuzzy link recency when confirmation has no eta."""
    existing = [_conf("a", "Tubby Toms", updated=datetime(2026, 7, 1, tzinfo=UTC))]
    incoming = Shipment(
        tracking_number="T",
        courier="Royal Mail",
        updated=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert find_match(existing, incoming, "Tubby Toms Ltd.") == "a"


def test_no_link_when_confirmation_postdates_courier() -> None:
    """Test no link when confirmation postdates courier."""
    existing = [_conf("a", "Tubby Toms", updated=datetime(2026, 7, 20, tzinfo=UTC))]
    incoming = Shipment(
        tracking_number="T",
        courier="Royal Mail",
        updated=datetime(2026, 7, 10, tzinfo=UTC),
    )
    assert find_match(existing, incoming, "Tubby Toms Ltd.") is None


def test_multi_shipment_same_order_different_tracking_does_not_merge() -> None:
    """Test multi shipment same order different tracking does not merge."""
    # An order with two shipments (same order_number, different tracking) must
    # stay two parcels — the second must not collapse into the first.
    existing = [
        Shipment(uid="a", order_number="O1", tracking_number="T1", retailer="Amazon")
    ]
    incoming = Shipment(order_number="O1", tracking_number="T2", retailer="Amazon")
    assert find_match(existing, incoming, None) is None


def test_order_match_merges_status_update_without_tracking() -> None:
    """Test order match merges status update without tracking."""
    existing = [Shipment(uid="a", order_number="O1", tracking_number="T1")]
    incoming = Shipment(order_number="O1", status="Delivered")
    assert find_match(existing, incoming, None) == "a"


def test_order_match_fills_tracking_when_existing_has_none() -> None:
    """Test order match fills tracking when existing has none."""
    existing = [Shipment(uid="a", order_number="O1")]
    incoming = Shipment(order_number="O1", tracking_number="T1")
    assert find_match(existing, incoming, None) == "a"


def test_order_and_same_tracking_merges() -> None:
    """Test order and same tracking merges."""
    existing = [Shipment(uid="a", order_number="O1", tracking_number="T1")]
    incoming = Shipment(order_number="O1", tracking_number="T1", status="Delivered")
    assert find_match(existing, incoming, None) == "a"


def test_second_shipment_of_order_matches_its_own_tracking() -> None:
    """Test second shipment of order matches its own tracking."""
    # After a split, a later update for the second tracking finds parcel b, not a.
    existing = [
        Shipment(uid="a", order_number="O1", tracking_number="T1"),
        Shipment(uid="b", order_number="O1", tracking_number="T2"),
    ]
    incoming = Shipment(order_number="O1", tracking_number="T2", status="Delivered")
    assert find_match(existing, incoming, None) == "b"
