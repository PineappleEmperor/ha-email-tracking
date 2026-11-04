"""Constants for the Email Parcel Tracking integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "email_parcel_tracking"

# The integration we source e-mails from (email-ha).
EMAIL_DOMAIN: Final = "email_imap"
EVENT_NEW_EMAIL: Final = "email_imap_new_email"
SERVICE_QUERY_EMAILS: Final = "query_emails"

# Config / options keys
CONF_FOLDER: Final = "folder"
CONF_LOOKBACK_DAYS: Final = "lookback_days"
CONF_KEEP_DELIVERED_DAYS: Final = "keep_delivered_days"

DEFAULT_FOLDER: Final = "INBOX"
DEFAULT_LOOKBACK_DAYS: Final = 30
DEFAULT_KEEP_DELIVERED_DAYS: Final = 3

# Storage
STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}.shipments"

# --- Delivery statuses -----------------------------------------------------
STATUS_ORDERED: Final = "Ordered"
STATUS_DISPATCHED: Final = "Dispatched"
STATUS_OUT_FOR_DELIVERY: Final = "Out for delivery"
STATUS_DELIVERED: Final = "Delivered"
STATUS_EXCEPTION: Final = "Exception"

STATUSES: Final = [
    STATUS_ORDERED,
    STATUS_DISPATCHED,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_DELIVERED,
    STATUS_EXCEPTION,
]

# Progress rank: a merge only advances status (higher wins); Exception is final.
STATUS_RANK: Final[dict[str, int]] = {
    STATUS_ORDERED: 0,
    STATUS_DISPATCHED: 1,
    STATUS_OUT_FOR_DELIVERY: 2,
    STATUS_DELIVERED: 3,
    STATUS_EXCEPTION: 4,
}
TERMINAL_STATUSES: Final = frozenset({STATUS_DELIVERED, STATUS_EXCEPTION})

# --- E-mail classification -------------------------------------------------
# Grouped sender addresses share a subject-keyword -> status map. Extend by
# adding a new address group and its subject map below.
# Subject substrings are matched in insertion order (first hit wins), scoped to
# the sender addresses they are paired with. Ported from prior-art parcel parsers.
_AMAZON_SUBJECTS: Final[dict[str, str]] = {
    "Your Amazon order has encountered an issue": STATUS_EXCEPTION,
    "Delivered:": STATUS_DELIVERED,
    "Out for delivery:": STATUS_OUT_FOR_DELIVERY,
    "Dispatched:": STATUS_DISPATCHED,
    "Ordered:": STATUS_ORDERED,
}
_ROYAL_MAIL_SUBJECTS: Final[dict[str, str]] = {
    "has encountered an issue": STATUS_EXCEPTION,
    "has been delivered": STATUS_DELIVERED,
    "is due to be delivered today": STATUS_OUT_FOR_DELIVERY,
    "is on its way": STATUS_DISPATCHED,
}
_DHL_SUBJECTS: Final[dict[str, str]] = {
    "Your Shipment Has Been Delivered": STATUS_DELIVERED,
    "Your Delivery Is Today": STATUS_OUT_FOR_DELIVERY,
    "Your Shipment Is On Its Way": STATUS_DISPATCHED,
}
_DPD_SUBJECTS: Final[dict[str, str]] = {
    "will be delivered today between": STATUS_OUT_FOR_DELIVERY,
    "We're expecting your": STATUS_ORDERED,
}
_DX_SUBJECTS: Final[dict[str, str]] = {
    "Delivered Exactly": STATUS_DELIVERED,
    "Out for delivery today": STATUS_OUT_FOR_DELIVERY,
    "We are expecting a delivery for you": STATUS_DISPATCHED,
}
_EVRI_SUBJECTS: Final[dict[str, str]] = {
    "has successfully delivered your": STATUS_DELIVERED,
    "We've delivered your": STATUS_DELIVERED,
    "parcel is now with your local Evri courier": STATUS_OUT_FOR_DELIVERY,
    "We've got your": STATUS_DISPATCHED,
}
_FEDEX_SUBJECTS: Final[dict[str, str]] = {
    "will be delivered today": STATUS_OUT_FOR_DELIVERY,
    "Change your delivery from": STATUS_DISPATCHED,
    "Delivered": STATUS_DELIVERED,
}
_UPS_SUBJECTS: Final[dict[str, str]] = {
    "was delivered": STATUS_DELIVERED,
    "Scheduled for Delivery Today": STATUS_OUT_FOR_DELIVERY,
    "Scheduled for Delivery Tomorrow": STATUS_DISPATCHED,
}
_TUBBY_SUBJECTS: Final[dict[str, str]] = {
    "Order #": STATUS_ORDERED,
}
_RAVE_SUBJECTS: Final[dict[str, str]] = {
    "is on the way": STATUS_DISPATCHED,
    "confirmed": STATUS_ORDERED,
}

# (label, sender addresses, subject -> status map)
_CARRIERS: Final[tuple[tuple[str, tuple[str, ...], dict[str, str]], ...]] = (
    (
        "Amazon",
        (
            "auto-confirm@amazon.co.uk",
            "shipment-tracking@amazon.co.uk",
            "order-update@amazon.co.uk",
        ),
        _AMAZON_SUBJECTS,
    ),
    ("Royal Mail", ("no-reply@royalmail.com",), _ROYAL_MAIL_SUBJECTS),
    ("DHL", ("noreply.odd@dhl.com", "notifications@dhlecommerce.co.uk"), _DHL_SUBJECTS),
    (
        "DPD",
        (
            "yourorder@dpd.co.uk",
            "yourdelivery@dpd.co.uk",
            "yourdelivery@dpdlocal.co.uk",
        ),
        _DPD_SUBJECTS,
    ),
    ("DX", ("esupport.prealerts@thedx.co.uk",), _DX_SUBJECTS),
    ("Evri", ("do-not-reply@evri.com",), _EVRI_SUBJECTS),
    ("FedEx", ("noreply@fedex.com",), _FEDEX_SUBJECTS),
    ("UPS", ("mcinfo@ups.com",), _UPS_SUBJECTS),
    ("Tubby Toms", ("info@tubbytoms.com",), _TUBBY_SUBJECTS),
    ("Rave", ("info@ravecoffee.co.uk",), _RAVE_SUBJECTS),
)

# address -> (retailer/courier label, subject -> status map)
SENDER_RULES: Final[dict[str, tuple[str, dict[str, str]]]] = {
    addr.lower(): (label, subjects)
    for label, addresses, subjects in _CARRIERS
    for addr in addresses
}

# Retailer labels (get retailer= set); everything else is a courier.
RETAILERS: Final = frozenset({"Amazon", "Tubby Toms", "Rave"})


def _slug(label: str) -> str:
    """snake_case a handler label without importing HA."""
    return "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")


HANDLER_LABELS: Final = tuple(dict.fromkeys(label for label, *_ in _CARRIERS))
HANDLER_SLUGS: Final = {label: _slug(label) for label in HANDLER_LABELS}

LINK_ETA_WINDOW: Final = timedelta(days=3)
LINK_ORDER_WINDOW: Final = timedelta(days=14)

# IMAP OR-search across every known parcel sender, for the startup scan.
KNOWN_SENDERS: Final = tuple(SENDER_RULES)
