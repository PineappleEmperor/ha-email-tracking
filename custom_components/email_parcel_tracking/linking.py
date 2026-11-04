"""Pure retailer→courier parcel linking — no Home Assistant imports."""

from collections.abc import Iterable
from datetime import timedelta
import re

from .const import LINK_ETA_WINDOW, LINK_ORDER_WINDOW
from .models import Shipment

_SUFFIX_RE = re.compile(r"\b(ltd|limited|inc|co)\b", re.IGNORECASE)


def normalize_retailer(name: str | None) -> str | None:
    """Lowercase, drop company suffixes/punctuation for name comparison."""
    if not name:
        return None
    cleaned = _SUFFIX_RE.sub(" ", name)
    cleaned = re.sub(r"[^a-z0-9 ]", " ", cleaned.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def find_match(
    shipments: Iterable[Shipment],
    incoming: Shipment,
    retailer_name: str | None,
) -> str | None:
    """Return the uid of the shipment ``incoming`` belongs to, or None."""
    items = list(shipments)

    if incoming.order_number is not None:
        for s in items:
            if s.order_number != incoming.order_number:
                continue
            # Same order but a different, already-known tracking number is a
            # separate parcel in a multi-shipment order — keep scanning for a
            # tracking-compatible match rather than collapsing the two.
            if (
                incoming.tracking_number is not None
                and s.tracking_number is not None
                and incoming.tracking_number != s.tracking_number
            ):
                continue
            return s.uid

    if incoming.tracking_number is not None:
        for s in items:
            if s.tracking_number == incoming.tracking_number:
                return s.uid

    # Fuzzy retailer→courier stitching applies only to an order-less courier
    # e-mail; anything carrying its own order number is a new/known order.
    if incoming.order_number is not None or incoming.tracking_number is None:
        return None
    target = normalize_retailer(incoming.retailer or retailer_name)
    if target is None:
        return None
    candidates = [
        s
        for s in items
        if s.tracking_number is None
        and normalize_retailer(s.retailer) == target
        and _within_window(s, incoming)
    ]
    return candidates[0].uid if len(candidates) == 1 else None


def _within_window(confirmation: Shipment, courier: Shipment) -> bool:
    if confirmation.eta is not None and courier.eta is not None:
        return abs(confirmation.eta - courier.eta) <= LINK_ETA_WINDOW
    if confirmation.updated is not None and courier.updated is not None:
        delta = courier.updated - confirmation.updated
        return timedelta(0) <= delta <= LINK_ORDER_WINDOW
    return False
