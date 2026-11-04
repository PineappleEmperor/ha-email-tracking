"""Tests for vendor senders and handler-label constants."""

from datetime import timedelta

from custom_components.email_parcel_tracking import const


def test_handler_labels_include_retailers_and_couriers() -> None:
    """Test handler labels include retailers and couriers."""
    for label in (
        "Amazon",
        "Tubby Toms",
        "Rave",
        "Royal Mail",
        "DHL",
        "DPD",
        "DX",
        "Evri",
        "FedEx",
        "UPS",
    ):
        assert label in const.HANDLER_LABELS
    assert len(const.HANDLER_LABELS) == len(set(const.HANDLER_LABELS))


def test_handler_slugs_are_snake_case() -> None:
    """Test handler slugs are snake case."""
    assert const.HANDLER_SLUGS["Royal Mail"] == "royal_mail"
    assert const.HANDLER_SLUGS["Tubby Toms"] == "tubby_toms"


def test_retailers_set() -> None:
    """Test retailers set."""
    assert frozenset({"Amazon", "Tubby Toms", "Rave"}) == const.RETAILERS


def test_link_windows() -> None:
    """Test link windows."""
    assert timedelta(days=3) == const.LINK_ETA_WINDOW
    assert timedelta(days=14) == const.LINK_ORDER_WINDOW
