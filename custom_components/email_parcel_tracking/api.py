"""Pure e-mail classification and parsing — no Home Assistant imports.

Kept dependency-free (stdlib + local models) so the parsing logic is
unit-testable without a running Home Assistant instance.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
import logging
import re
from typing import Any

from .const import RETAILERS, SENDER_RULES, STATUS_OUT_FOR_DELIVERY
from .models import Shipment

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedEmail:
    """A parsed parcel e-mail: a partial shipment plus any retailer mention."""

    shipment: Shipment
    retailer_name: str | None = None


# Per-label order-number extraction: label -> (regex, "{n}" output template).
_ORDER_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "Amazon": (re.compile(r"\b\d{3}-\d{7}-\d{7}\b"), "{n}"),
    "Tubby Toms": (re.compile(r"Order\s*#\s*(\d{4,6})"), "TubbyT-{n}"),
    "Rave": (re.compile(r"#\s*(\d{2,})"), "{n}"),
}

# Per-label retailer-mention extraction from the subject line (couriers only).
_RETAILER_MENTION_RE = {
    "Royal Mail": re.compile(
        r"Your Royal Mail parcel from (?P<name>.+?) is "
        r"(?:on its way|due to be delivered)",
        re.IGNORECASE,
    ),
    "Evri": re.compile(r"(?:We've got your|Your) (?P<name>.+?) parcel", re.IGNORECASE),
}

# Rave ships via multiple couriers; the actual carrier is only named in the
# postage line, not the sender/subject.
_RAVE_SHIPPER_RE = re.compile(r"Royal Mail|SmartConsign", re.IGNORECASE)

# Courier-specific tracking-number formats (ported from prior-art parsers).
# Tried by carrier label first; the generic pattern is the fallback.
_TRACKING_PATTERNS: dict[str, re.Pattern[str]] = {
    "Royal Mail": re.compile(r"\b[A-Z]{2}\d{9}GB\b"),
    "UPS": re.compile(r"\b(?:1Z[A-Z0-9]{6}\d{10}|\d[A-Z]\d{2}[A-Z]{2}\d{12})\b"),
    "DPD": re.compile(r"\b\d{4}\s\d{4}\s\d{3}\s\d{3}\b"),
    "Evri": re.compile(r"\b[A-Z]\d{2}[A-Z0-9]{3}\d{10}\b"),
}
# Generic fallback: an id run must follow a tracking keyword — an unanchored
# scan matches URL/campaign junk in HTML bodies and yields unstable ids.
_GENERIC_TRACKING_RE = re.compile(
    r"(?:tracking|consignment|waybill|parcel)(?:\s*(?:no\.?|number|:|#))?\s*"
    r"((?=[A-Z0-9]*\d)[A-Z0-9]{8,24})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(\d{4}))?")

_MONTHS = {
    name.lower(): index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}


def sender_address(raw: str | None) -> str | None:
    """Extract the bare e-mail address from a From header value."""
    if not raw:
        return None
    return parseaddr(raw)[1].lower() or None


def classify(sender: str | None, subject: str | None) -> tuple[str, str] | None:
    """Return ``(label, status)`` for a known parcel e-mail, else ``None``."""
    addr = sender_address(sender)
    if addr is None or subject is None:
        return None
    rule = SENDER_RULES.get(addr)
    if rule is None:
        return None
    label, subject_map = rule
    for keyword, status in subject_map.items():
        if keyword in subject:
            return label, status
    return None


def parse_eta(text: str, ref: date, status: str | None) -> date | None:
    """Best-effort delivery date from e-mail text, relative to its send date."""
    if status == STATUS_OUT_FOR_DELIVERY:
        return ref
    lowered = text.lower()
    if "tomorrow" in lowered:
        return ref + timedelta(days=1)
    if "today" in lowered:
        return ref
    for match in _DATE_RE.finditer(text):
        day, month_name, year = match.groups()
        month = _MONTHS.get(month_name.lower())
        if month is None:
            continue
        try:
            resolved = date(int(year) if year else ref.year, month, int(day))
        except ValueError:
            continue
        # An inferred (year-less) date that lands in the past is next year's.
        if year is None and resolved < ref:
            resolved = resolved.replace(year=resolved.year + 1)
        return resolved
    return None


def parse_email(email: Mapping[str, Any], ref: date) -> ParsedEmail | None:
    """Turn one ``query_emails`` result into a ParsedEmail, or ``None``."""
    # ``ref`` is the current date (from HA's clock): it resolves relative dates
    # and stands in when the e-mail carries no parseable date.
    result = classify(email.get("sender"), email.get("subject"))
    if result is None:
        return None
    label, status = result

    subject = email.get("subject") or ""
    body = email.get("body") or email.get("preview") or ""
    haystack = f"{subject}\n{body}"

    is_retailer = label in RETAILERS
    order_number = _find_order_number(label, haystack)
    tracking_number = _find_tracking(label, haystack, body)

    if order_number is None and tracking_number is None:
        # Known parcel sender but no extractable id — surface it so a carrier
        # whose format changed (and now silently drops) is discoverable.
        _LOGGER.debug("No trackable id in %s e-mail: %s", label, subject)
        return None

    when = _email_date(email.get("date"), ref)
    eta = parse_eta(haystack, when.date(), status)
    courier = None if is_retailer else label
    if is_retailer:
        courier = _infer_shipper(label, body)  # None unless Rave postage present

    shipment = Shipment(
        order_number=order_number,
        tracking_number=tracking_number,
        retailer=label if is_retailer else None,
        courier=courier,
        status=status,
        eta=eta,
        updated=when,
    )
    retailer_name = _retailer_mention(label, subject)
    return ParsedEmail(shipment=shipment, retailer_name=retailer_name)


def _find_order_number(label: str, haystack: str) -> str | None:
    """Extract and format the per-retailer order number, if any."""
    rule = _ORDER_PATTERNS.get(label)
    if rule is None:
        return None
    pattern, template = rule
    match = pattern.search(haystack)
    if match is None:
        return None
    value = match.group(1) if match.groups() else match.group(0)
    return template.format(n=value)


def _retailer_mention(label: str, subject: str) -> str | None:
    """Extract the retailer name a courier subject mentions, if any."""
    pattern = _RETAILER_MENTION_RE.get(label)
    match = pattern.search(subject) if pattern else None
    return match.group("name").strip() if match else None


def _infer_shipper(label: str, body: str) -> str | None:
    """Infer the actual courier from a Rave postage line, if present."""
    if label != "Rave":
        return None
    match = _RAVE_SHIPPER_RE.search(body)
    if match is None:
        return None
    return "DX" if match.group(0).lower().startswith("smart") else "Royal Mail"


def _find_tracking(label: str, haystack: str, body: str) -> str | None:
    """Find a tracking number using the courier pattern, else the generic one."""
    pattern = _TRACKING_PATTERNS.get(label)
    if pattern is not None:
        match = pattern.search(haystack)
        if match:
            return match.group(0)
    generic = _GENERIC_TRACKING_RE.search(body)
    return generic.group(1).upper() if generic else None


def _email_date(raw: str | None, ref: date) -> datetime:
    """Parse the e-mail Date header as tz-aware; fall back to ``ref`` (UTC)."""
    fallback = datetime.combine(ref, datetime.min.time(), tzinfo=UTC)
    if not raw:
        return fallback
    try:
        parsed = parsedate_to_datetime(raw)
    except TypeError, ValueError:
        return fallback
    # Keep the offset rather than dropping it — a naive strip mis-dates
    # near-midnight e-mails and breaks aware/naive comparisons downstream.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
