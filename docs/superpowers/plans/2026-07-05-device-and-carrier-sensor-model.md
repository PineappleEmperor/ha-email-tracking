# Device + Carrier-Sensor Model with Retailer→Courier Linking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure entities into a device-grouped, per-handler sensor model and model each parcel as a retailer→courier lifecycle with fuzzy linking.

**Architecture:** One config entry → one device grouping a fixed set of "handler" sensors (retailers ∪ couriers, state = next ETA), a total next-delivery sensor, opt-in per-parcel sensors, calendar and button. A parcel is one `Shipment` keyed by a synthetic `uid`, carrying both order/tracking ids and both retailer/courier; a pure `linking.find_match` stitches a retailer confirmation to its later courier e-mail by shared id or by normalised retailer-name + ETA window (guarded against ambiguous merges).

**Tech Stack:** Home Assistant 2026.5+ custom integration, Python 3.14, pytest + pytest-homeassistant-custom-component, ruff, pyright.

## Global Constraints

- Target **platinum** quality scale; keep `quality_scale.yaml` honest (`done` only with a proving test).
- `api.py` and `linking.py` are **pure** — stdlib + local `models`/`const` only, no `homeassistant` imports.
- ruff + pyright (standard) clean, no new suppressions: `ruff check .`, `python -m pyright custom_components/`.
- `_attr_has_entity_name = True`; every entity has a stable `unique_id` and `_attr_device_info`.
- Lazy `%` logging, never f-strings in log calls.
- **Repo is not git-initialised yet.** Do not run `git`. Treat each "Commit" step as a checkpoint: the commit message is provided (Conventional Commits, one tight imperative subject) to be applied once `git init` is done.
- Verify HA APIs against developers.home-assistant.io before use.
- HA available in-env for tests; hassfest runnable via `cd /home/juicebox/HA-core && python -m script.hassfest --integration-path <pkg> --action validate`.

## File map

- `custom_components/email_parcel_tracking/const.py` — add vendor senders, `RETAILERS`, `HANDLER_LABELS`, `HANDLER_SLUGS`, `LINK_ETA_WINDOW`, `LINK_ORDER_WINDOW`; remove `CONF_ACCOUNT`.
- `models.py` — `Shipment` restructured (uid + dual ids + retailer&courier), `carrier_label`, `merge`.
- `api.py` — `ParsedEmail` + `parse_email` returning it; per-retailer order-number, retailer-name mention, Rave shipper inference, `_normalize_retailer`.
- `linking.py` — **new** pure module: `find_match`, `normalize_retailer`.
- `coordinator.py` — uid-keyed ingest via `find_match` + ulid; remove account.
- `entity.py` — device_info on base.
- `__init__.py` — `async_remove_config_entry_device`.
- `sensor.py` — total + handler + opt-in per-parcel sensors + auto-enable listener.
- `config_flow.py`, `diagnostics.py`, `strings.json`, `translations/en.json`, `icons.json`, `quality_scale.yaml` — cleanups + new keys.
- `tests/…` — extend; add `tests/fixtures/emails/` + loader.

---

### Task 1: Restructure the `Shipment` model

**Files:**
- Modify: `custom_components/email_parcel_tracking/models.py`
- Test: `tests/test_api.py` (model tests live here already)

**Interfaces:**
- Produces: `Shipment(uid: str = "", order_number, tracking_number, retailer, courier, status, eta, updated)`; `Shipment.carrier_label -> str | None`; `Shipment.merge(other)`; `to_dict`/`from_dict`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api.py — replace the old merge/roundtrip tests with these
def test_carrier_label_prefers_courier():
    assert Shipment(retailer="Tubby Toms").carrier_label == "Tubby Toms"
    assert (
        Shipment(retailer="Tubby Toms", courier="Royal Mail").carrier_label
        == "Royal Mail"
    )
    assert Shipment().carrier_label is None


def test_merge_fills_ids_and_parties_and_advances_status():
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


def test_merge_keeps_newer_timestamp_only():
    newer = datetime(2026, 7, 4, tzinfo=UTC)
    s = Shipment(uid="a", status=STATUS_DISPATCHED, updated=newer)
    s.merge(Shipment(updated=datetime(2026, 7, 1, tzinfo=UTC)))
    assert s.updated == newer


def test_shipment_roundtrip_includes_uid_and_dual_ids():
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
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_api.py -k "carrier_label or merge or roundtrip" -v` → FAIL (unexpected kwargs / attr).

- [ ] **Step 3: Implement**

```python
"""Data models for the Email Parcel Tracking integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .const import STATUS_RANK


@dataclass(slots=True)
class Shipment:
    """One parcel across its lifecycle (retailer confirmation → courier)."""

    uid: str = ""
    order_number: str | None = None
    tracking_number: str | None = None
    retailer: str | None = None
    courier: str | None = None
    status: str | None = None
    eta: date | None = None
    updated: datetime | None = None

    @property
    def carrier_label(self) -> str | None:
        """Current handler: the courier once known, else the retailer."""
        return self.courier or self.retailer

    def to_dict(self) -> dict[str, str | None]:
        return {
            "uid": self.uid,
            "order_number": self.order_number,
            "tracking_number": self.tracking_number,
            "retailer": self.retailer,
            "courier": self.courier,
            "status": self.status,
            "eta": self.eta.isoformat() if self.eta else None,
            "updated": self.updated.isoformat() if self.updated else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | None]) -> Shipment:
        eta = data.get("eta")
        updated = data.get("updated")
        return cls(
            uid=data.get("uid") or "",
            order_number=data.get("order_number"),
            tracking_number=data.get("tracking_number"),
            retailer=data.get("retailer"),
            courier=data.get("courier"),
            status=data.get("status"),
            eta=date.fromisoformat(eta) if eta else None,
            updated=datetime.fromisoformat(updated) if updated else None,
        )

    def merge(self, other: Shipment) -> None:
        """Merge a newer parsed update in place (identity/uid preserved)."""
        for attr in ("order_number", "tracking_number", "retailer", "courier", "eta"):
            value = getattr(other, attr)
            if value is not None:
                setattr(self, attr, value)
        if other.status is not None and self._status_advances(other.status):
            self.status = other.status
        if other.updated is not None and (
            self.updated is None or other.updated > self.updated
        ):
            self.updated = other.updated

    def _status_advances(self, new: str) -> bool:
        if self.status is None:
            return True
        return STATUS_RANK.get(new, -1) >= STATUS_RANK.get(self.status, -1)
```

- [ ] **Step 4: Run to verify pass** — same command → PASS. (Other tests will fail until Task 3 updates `api.py`; that's expected and fixed there.)

- [ ] **Step 5: Commit** — `refactor: model shipment as a retailer-to-courier lifecycle`

---

### Task 2: Constants — vendors, handler labels, link windows; drop CONF_ACCOUNT

**Files:**
- Modify: `custom_components/email_parcel_tracking/const.py`
- Test: `tests/test_const.py` (new)

**Interfaces:**
- Produces: `_CARRIERS` (now incl. Tubby Toms, Rave); `RETAILERS: frozenset`; `HANDLER_LABELS: tuple[str, ...]`; `HANDLER_SLUGS: dict[str, str]`; `LINK_ETA_WINDOW: timedelta`; `LINK_ORDER_WINDOW: timedelta`. `CONF_ACCOUNT` removed.

- [ ] **Step 1: Write failing test**

```python
# tests/test_const.py
from datetime import timedelta

from custom_components.email_parcel_tracking import const


def test_handler_labels_include_retailers_and_couriers():
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


def test_handler_slugs_are_snake_case():
    assert const.HANDLER_SLUGS["Royal Mail"] == "royal_mail"
    assert const.HANDLER_SLUGS["Tubby Toms"] == "tubby_toms"


def test_retailers_set():
    assert const.RETAILERS == frozenset({"Amazon", "Tubby Toms", "Rave"})


def test_link_windows():
    assert const.LINK_ETA_WINDOW == timedelta(days=3)
    assert const.LINK_ORDER_WINDOW == timedelta(days=14)


def test_conf_account_removed():
    assert not hasattr(const, "CONF_ACCOUNT")
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_const.py -v` → FAIL.

- [ ] **Step 3: Implement** — in `const.py`:
  1. Delete the `CONF_ACCOUNT` line.
  2. Add vendor subject maps and extend `_CARRIERS`:

```python
_TUBBY_SUBJECTS: Final[dict[str, str]] = {
    "Order #": STATUS_ORDERED,
}
_RAVE_SUBJECTS: Final[dict[str, str]] = {
    "is on the way": STATUS_DISPATCHED,
    "confirmed": STATUS_ORDERED,
}
```
  Append to `_CARRIERS`:
```python
(("Tubby Toms", ("info@tubbytoms.com",), _TUBBY_SUBJECTS),)
(("Rave", ("info@ravecoffee.co.uk",), _RAVE_SUBJECTS),)
```
  3. Replace `RETAILERS` and add handler/link constants:

```python
RETAILERS: Final = frozenset({"Amazon", "Tubby Toms", "Rave"})


def _slug(label: str) -> str:
    """snake_case a handler label without importing HA."""
    return "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")


HANDLER_LABELS: Final = tuple(dict.fromkeys(label for label, *_ in _CARRIERS))
HANDLER_SLUGS: Final = {label: _slug(label) for label in HANDLER_LABELS}

LINK_ETA_WINDOW: Final = timedelta(days=3)
LINK_ORDER_WINDOW: Final = timedelta(days=14)
```
  4. Add `from datetime import timedelta` at the top of `const.py`.

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_const.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat: add vendor senders and handler-label constants`

---

### Task 3: Parsing — `ParsedEmail`, order numbers, retailer mentions, shipper inference

**Files:**
- Modify: `custom_components/email_parcel_tracking/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Shipment` (Task 1), `const` (Task 2).
- Produces: `@dataclass ParsedEmail(shipment: Shipment, retailer_name: str | None)`; `parse_email(email: Mapping[str, Any], ref: date) -> ParsedEmail | None`; `normalize_retailer(name: str | None) -> str | None` (re-exported from `linking` in Task 4, but the name-extraction lives here).

- [ ] **Step 1: Write failing tests** (add; keep existing carrier/eta tests, update their assertions from `order_id` to `order_number`/`tracking_number`)

```python
def test_parse_tubby_confirmation_sets_order_and_retailer():
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


def test_parse_royalmail_extracts_retailer_mention():
    parsed = api.parse_email(
        {
            "sender": "no-reply@royalmail.com",
            "subject": "Your Royal Mail parcel from Tubby Toms Ltd. is on its way",
            "body": "Tracking AB123456789GB",
            "date": "Fri, 04 Jul 2026 08:00:00 +0100",
        },
        REF,
    )
    assert parsed.shipment.courier == "Royal Mail"
    assert parsed.shipment.tracking_number == "AB123456789GB"
    assert parsed.retailer_name == "Tubby Toms Ltd."


def test_parse_rave_infers_shipper_from_postage():
    parsed = api.parse_email(
        {
            "sender": "info@ravecoffee.co.uk",
            "subject": "A shipment from order #778 is on the way",
            "body": "Shipping: Royal Mail",
            "date": "Fri, 04 Jul 2026 08:00:00 +0100",
        },
        REF,
    )
    assert parsed.shipment.retailer == "Rave"
    assert parsed.shipment.order_number == "778"
    assert parsed.shipment.courier == "Royal Mail"  # inferred
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_api.py -v` → FAIL.

- [ ] **Step 3: Implement** in `api.py`:
  - Add `from dataclasses import dataclass` and:

```python
@dataclass(slots=True)
class ParsedEmail:
    """A parsed parcel e-mail: a partial shipment plus any retailer mention."""

    shipment: Shipment
    retailer_name: str | None = None


_ORDER_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    # label -> (subject/body regex, group-0 template using {n})
    "Amazon": (re.compile(r"\b\d{3}-\d{7}-\d{7}\b"), "{n}"),
    "Tubby Toms": (re.compile(r"Order\s*#\s*(\d{4,6})"), "TubbyT-{n}"),
    "Rave": (re.compile(r"#\s*(\d{2,})"), "{n}"),
}

_RETAILER_MENTION_RE = {
    "Royal Mail": re.compile(
        r"Your Royal Mail parcel from (?P<name>.+?) is (?:on its way|due to be delivered)",
        re.IGNORECASE,
    ),
    "Evri": re.compile(r"(?:We've got your|Your) (?P<name>.+?) parcel", re.IGNORECASE),
}

_RAVE_SHIPPER_RE = re.compile(r"Royal Mail|SmartConsign", re.IGNORECASE)
```
  - Order-number extraction helper:

```python
def _find_order_number(label: str, haystack: str) -> str | None:
    rule = _ORDER_PATTERNS.get(label)
    if rule is None:
        return None
    pattern, template = rule
    match = pattern.search(haystack)
    if match is None:
        return None
    value = match.group(1) if match.groups() else match.group(0)
    return template.format(n=value)
```
  - Retailer-mention + shipper helpers:

```python
def _retailer_mention(label: str, subject: str) -> str | None:
    pattern = _RETAILER_MENTION_RE.get(label)
    match = pattern.search(subject) if pattern else None
    return match.group("name").strip() if match else None


def _infer_shipper(label: str, body: str) -> str | None:
    if label != "Rave":
        return None
    match = _RAVE_SHIPPER_RE.search(body)
    if match is None:
        return None
    return "DX" if match.group(0).lower().startswith("smart") else "Royal Mail"
```
  - Rewrite `parse_email` to return `ParsedEmail`:

```python
def parse_email(email: Mapping[str, Any], ref: date) -> ParsedEmail | None:
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
    return ParsedEmail(
        shipment=shipment, retailer_name=_retailer_mention(label, subject)
    )
```
  - Update imports: `from .const import RETAILERS, SENDER_RULES, STATUS_OUT_FOR_DELIVERY`.

- [ ] **Step 4: Run** — `python -m pytest tests/test_api.py -v` → PASS (also fix the earlier Amazon/RM/DPD/UPS/Evri tests to read `parsed.shipment.order_number`/`.tracking_number` instead of `.order_id`).

- [ ] **Step 5: Commit** — `feat: parse order numbers, retailer mentions, and rave shipper`

---

### Task 4: Linking module

**Files:**
- Create: `custom_components/email_parcel_tracking/linking.py`
- Test: `tests/test_linking.py` (new)

**Interfaces:**
- Consumes: `Shipment` (Task 1), `const.LINK_ETA_WINDOW`/`LINK_ORDER_WINDOW` (Task 2).
- Produces: `normalize_retailer(name: str | None) -> str | None`; `find_match(shipments: Iterable[Shipment], incoming: Shipment, retailer_name: str | None) -> str | None`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_linking.py
from datetime import date, datetime, UTC

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


def test_normalize_strips_suffixes():
    assert normalize_retailer("Tubby Toms Ltd.") == "tubby toms"
    assert normalize_retailer("RAVE Limited") == "rave"
    assert normalize_retailer(None) is None


def test_match_on_order_number():
    existing = [_conf("a", "Tubby Toms")]
    incoming = Shipment(order_number="Tubby Toms-1", retailer="Tubby Toms")
    assert find_match(existing, incoming, None) == "a"


def test_match_on_tracking_number():
    existing = [
        Shipment(uid="a", tracking_number="AB123456789GB", courier="Royal Mail")
    ]
    incoming = Shipment(tracking_number="AB123456789GB", courier="Royal Mail")
    assert find_match(existing, incoming, None) == "a"


def test_fuzzy_link_on_name_and_eta_window():
    existing = [_conf("a", "Tubby Toms", eta=date(2026, 7, 6))]
    incoming = Shipment(
        tracking_number="AB123456789GB", courier="Royal Mail", eta=date(2026, 7, 7)
    )
    assert find_match(existing, incoming, "Tubby Toms Ltd.") == "a"


def test_no_link_when_eta_outside_window():
    existing = [_conf("a", "Tubby Toms", eta=date(2026, 7, 6))]
    incoming = Shipment(
        tracking_number="T", courier="Royal Mail", eta=date(2026, 7, 20)
    )
    assert find_match(existing, incoming, "Tubby Toms Ltd.") is None


def test_no_link_when_two_candidates():
    existing = [
        _conf("a", "Tubby Toms", eta=date(2026, 7, 6)),
        _conf("b", "Tubby Toms", eta=date(2026, 7, 6)),
    ]
    incoming = Shipment(tracking_number="T", courier="Royal Mail", eta=date(2026, 7, 6))
    assert find_match(existing, incoming, "Tubby Toms Ltd.") is None


def test_fuzzy_link_recency_when_confirmation_has_no_eta():
    existing = [_conf("a", "Tubby Toms", updated=datetime(2026, 7, 1, tzinfo=UTC))]
    incoming = Shipment(
        tracking_number="T",
        courier="Royal Mail",
        updated=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert find_match(existing, incoming, "Tubby Toms Ltd.") == "a"
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_linking.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
"""Pure retailer→courier parcel linking — no Home Assistant imports."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .const import LINK_ETA_WINDOW, LINK_ORDER_WINDOW
from .models import Shipment

_SUFFIX_RE = re.compile(r"\b(ltd|ltd\.|limited|inc|inc\.|co|co\.)\b", re.IGNORECASE)


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
            if s.order_number == incoming.order_number:
                return s.uid

    if incoming.tracking_number is not None:
        for s in items:
            if s.tracking_number == incoming.tracking_number:
                return s.uid

    # Fuzzy: a courier e-mail (tracking, no id match) → unlinked confirmation.
    if incoming.tracking_number is None:
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
        return LINK_ORDER_WINDOW >= delta >= -LINK_ORDER_WINDOW
    return False
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_linking.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat: add retailer-to-courier parcel linking`

---

### Task 5: Coordinator — uid-keyed ingest with linking; remove account

**Files:**
- Modify: `custom_components/email_parcel_tracking/coordinator.py`
- Test: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `parse_email`→`ParsedEmail` (Task 3), `find_match` (Task 4), `ulid` from HA.
- Produces: coordinator `data: dict[str, Shipment]` keyed by `uid`; no `account`.

- [ ] **Step 1: Write failing test**

```python
def test_ingest_links_confirmation_and_courier(hass: HomeAssistant):
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
    entry = await _setup(hass)  # existing helper in test_coordinator.py
    coord = entry.runtime_data
    # one merged parcel with both ids, courier known
    shipments = list(coord.data.values())
    assert len(shipments) == 1
    assert shipments[0].order_number == "TubbyT-12345"
    assert shipments[0].tracking_number == "AB123456789GB"
    assert shipments[0].courier == "Royal Mail"
```
(Use the existing `register`/`_setup` helpers in `test_coordinator.py`; ETA-less confirmation links via the 14-day recency window since both dates are within it.)

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_coordinator.py -k link -v` → FAIL.

- [ ] **Step 3: Implement** — in `coordinator.py`:
  - Add `from homeassistant.util import ulid as ulid_util` (import path: `from homeassistant.util.ulid import ulid_now`). Use `ulid_now()`.
  - Rewrite `_ingest`:

```python
def _ingest(self, emails: list[dict[str, Any]]) -> bool:
    ref = dt_util.now().date()
    changed = False
    for email in emails:
        parsed = parse_email(email, ref)
        if parsed is None:
            continue
        uid = find_match(
            self._shipments.values(), parsed.shipment, parsed.retailer_name
        )
        if uid is not None:
            self._shipments[uid].merge(parsed.shipment)
        else:
            new_uid = ulid_now()
            parsed.shipment.uid = new_uid
            self._shipments[new_uid] = parsed.shipment
        changed = True
    return changed
```
  - `async_prepare`: key restored shipments by `uid` (assign one if a legacy row lacks it):

```python
self._shipments = {}
for item in stored or []:
    shipment = Shipment.from_dict(item)
    if not shipment.uid:
        shipment.uid = ulid_now()
    self._shipments[shipment.uid] = shipment
```
  - Remove the `account` property, its use in `_query` payload, and the account filter in `_handle_new_email` (ingest every event).
  - Imports: `from .api import parse_email` stays; add `from .linking import find_match`; drop `CONF_ACCOUNT`.

- [ ] **Step 4: Run** — `python -m pytest tests/test_coordinator.py -v` → PASS (update the existing account-filter test: delete it; update merge/prune/persistence tests to read `uid`-keyed data and `order_number`).

- [ ] **Step 5: Commit** — `feat: key parcels by uid and link on ingest`

---

### Task 6: Device — base device_info + removal handler

**Files:**
- Modify: `custom_components/email_parcel_tracking/entity.py`, `__init__.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Produces: `ParcelTrackingEntity._attr_device_info`; `async_remove_config_entry_device`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_init.py
from homeassistant.helpers import device_registry as dr
from custom_components.email_parcel_tracking import async_remove_config_entry_device


async def test_device_created_and_entities_linked(hass):
    await _register_email_service(hass, [AMAZON_EMAIL])
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None


async def test_remove_config_entry_device(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    live = dr.DeviceEntry(identifiers={(DOMAIN, entry.entry_id)})
    foreign = dr.DeviceEntry(identifiers={(DOMAIN, "other")})
    assert await async_remove_config_entry_device(hass, entry, live) is False
    assert await async_remove_config_entry_device(hass, entry, foreign) is True
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_init.py -k device -v` → FAIL.

- [ ] **Step 3: Implement**
  - `entity.py`:

```python
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

...


class ParcelTrackingEntity(CoordinatorEntity[ParcelTrackingCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ParcelTrackingCoordinator) -> None:
        super().__init__(coordinator)
        self._entry_id = coordinator.config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Email Parcel Tracking",
            manufacturer="Email Parcel Tracking",
            model="Mailbox parcel tracker",
            entry_type=DeviceEntryType.SERVICE,
        )
```
  (import `DOMAIN` from `.const`.)
  - `__init__.py`:

```python
from homeassistant.helpers.device_registry import DeviceEntry


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ParcelTrackingConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow removing only a stale/foreign device row, never the live one."""
    return not any(
        domain == DOMAIN and ident == entry.entry_id
        for domain, ident in device_entry.identifiers
    )
```

- [ ] **Step 4: Run** — `python -m pytest tests/test_init.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat: group entities under one device with a removal handler`

---

### Task 7: Sensors — total, handler, opt-in per-parcel, auto-enable

**Files:**
- Modify: `custom_components/email_parcel_tracking/sensor.py`
- Test: `tests/test_platforms.py`, `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `HANDLER_LABELS`/`HANDLER_SLUGS` (Task 2), `Shipment.carrier_label` (Task 1), device base (Task 6).
- Produces entities: `sensor…_next_delivery`, `sensor…_handler_<slug>` ×N, `sensor…_parcel_<uid>`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_platforms.py
async def test_handler_sensor_next_eta_and_grouping(hass):
    # Tubby Toms confirmation + Royal Mail dispatch (links) → one parcel under Royal Mail
    ...  # setup via register() with the paired flow from Task 5
    ent_reg = er.async_get(hass)
    rm = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_handler_royal_mail"
    )
    assert rm and hass.states.get(rm).state != "unknown"
    # Tubby Toms handler has no *active* parcel now (moved to courier)
    tt = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_handler_tubby_toms"
    )
    assert ent_reg.async_get(tt).disabled_by is not None  # stayed disabled/empty


async def test_total_next_delivery_sensor(hass):
    ...  # one active parcel with eta today
    nd = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_next_delivery"
    )
    st = hass.states.get(nd)
    assert st.attributes["active_count"] == 1


async def test_empty_handler_disabled_then_auto_enabled(hass):
    state = register(hass)
    state["by_uid"]["5"] = [DPD_OFD_EMAIL]
    entry = await _setup(hass)  # startup empty → dpd handler disabled
    ent_reg = er.async_get(hass)
    dpd = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_handler_dpd")
    assert ent_reg.async_get(dpd).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    hass.bus.async_fire(EVENT_NEW_EMAIL, {"uid": 5})
    await hass.async_block_till_done()
    assert ent_reg.async_get(dpd).disabled_by is None  # auto-enabled


async def test_per_parcel_sensor_disabled_by_default(hass):
    ...  # one parcel
    pid = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_parcel_{uid}"
    )
    assert ent_reg.async_get(pid).disabled_by is er.RegistryEntryDisabler.INTEGRATION
```
(Fill the `...` using existing `register`/`_setup` helpers; `DPD_OFD_EMAIL` = the DPD out-for-delivery fixture.)

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_platforms.py -v` → FAIL.

- [ ] **Step 3: Implement** `sensor.py` — full rewrite:

```python
"""Sensor platform for the Email Parcel Tracking integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HANDLER_LABELS, HANDLER_SLUGS, STATUSES, TERMINAL_STATUSES
from .coordinator import ParcelTrackingConfigEntry, ParcelTrackingCoordinator
from .entity import ParcelTrackingEntity
from .models import Shipment

PARALLEL_UPDATES = 0


def _active(shipments: list[Shipment], label: str | None = None) -> list[Shipment]:
    items = [s for s in shipments if s.status not in TERMINAL_STATUSES]
    if label is not None:
        items = [s for s in items if s.carrier_label == label]
    return sorted(
        items, key=lambda s: (s.eta is None, s.eta or dt_util.utcnow().date())
    )


def _eta_ts(shipment: Shipment | None):
    if shipment is None or shipment.eta is None:
        return None
    return dt_util.start_of_local_day(shipment.eta)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParcelTrackingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [ParcelNextDeliverySensor(coordinator)]
    entities += [ParcelHandlerSensor(coordinator, label) for label in HANDLER_LABELS]
    async_add_entities(entities)

    tracked: set[str] = set()

    @callback
    def _sync() -> None:
        # add opt-in per-parcel sensors
        new = [uid for uid in coordinator.data if uid not in tracked]
        if new:
            tracked.update(new)
            async_add_entities(ParcelSensor(coordinator, uid, tracked) for uid in new)
        # auto-enable handlers that now have active parcels
        reg = er.async_get(hass)
        for label in HANDLER_LABELS:
            if not _active(list(coordinator.data.values()), label):
                continue
            eid = reg.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_handler_{HANDLER_SLUGS[label]}"
            )
            row = reg.async_get(eid) if eid else None
            if row and row.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                reg.async_update_entity(eid, disabled_by=None)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class ParcelNextDeliverySensor(ParcelTrackingEntity, SensorEntity):
    _attr_translation_key = "next_delivery"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ParcelTrackingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_next_delivery"

    @property
    def native_value(self):
        active = _active(list(self.coordinator.data.values()))
        return _eta_ts(active[0]) if active else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = list(self.coordinator.data.values())
        active = _active(items)
        by_carrier: dict[str, int] = {}
        for s in active:
            key = s.carrier_label or "unknown"
            by_carrier[key] = by_carrier.get(key, 0) + 1
        return {
            "active_count": len(active),
            "next_carrier": active[0].carrier_label if active else None,
            "by_carrier": by_carrier,
            "parcels": [s.to_dict() for s in active],
        }


class ParcelHandlerSensor(ParcelTrackingEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ParcelTrackingCoordinator, label: str) -> None:
        super().__init__(coordinator)
        self._label = label
        self._attr_translation_key = HANDLER_SLUGS[label]
        self._attr_unique_id = f"{self._entry_id}_handler_{HANDLER_SLUGS[label]}"
        self._attr_entity_registry_enabled_default = bool(
            _active(list(coordinator.data.values()), label)
        )

    @property
    def native_value(self):
        active = _active(list(self.coordinator.data.values()), self._label)
        return _eta_ts(active[0]) if active else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        active = _active(list(self.coordinator.data.values()), self._label)
        return {
            "active_count": len(active),
            "current": active[0].to_dict() if active else None,
            "parcels": [s.to_dict() for s in active],
        }


class ParcelSensor(ParcelTrackingEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, uid: str, tracked: set[str]) -> None:
        super().__init__(coordinator)
        self._uid = uid
        self._tracked = tracked
        self._removing = False
        self._attr_unique_id = f"{self._entry_id}_parcel_{uid}"

    @property
    def available(self) -> bool:
        return super().available and self._uid in self.coordinator.data

    @property
    def name(self) -> str:
        s = self.coordinator.data.get(self._uid)
        label = (s.carrier_label if s else None) or "Parcel"
        ident = (s.order_number or s.tracking_number if s else None) or self._uid
        return f"{label} {ident}"

    @property
    def native_value(self) -> str | None:
        s = self.coordinator.data.get(self._uid)
        return s.status if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.coordinator.data.get(self._uid)
        return s.to_dict() if s else {}

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._uid not in self.coordinator.data:
            if not self._removing:
                self._removing = True
                self._tracked.discard(self._uid)
                self.hass.async_create_task(self.async_remove(force_remove=True))
            return
        super()._handle_coordinator_update()
```

- [ ] **Step 4: Run** — `python -m pytest tests/test_platforms.py tests/test_coordinator.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat: device-grouped total and per-handler sensors`

---

### Task 8: Config flow, diagnostics, strings, icons — cleanup + new keys

**Files:**
- Modify: `config_flow.py`, `diagnostics.py`, `strings.json`, `translations/en.json`, `icons.json`
- Test: `tests/test_config_flow.py`, `tests/test_strings.py`, `tests/test_diagnostics.py`

**Interfaces:** removes `CONF_ACCOUNT` field; adds `entity.sensor.<slug>` + `next_delivery` names and icons.

- [ ] **Step 1: Write/adjust failing tests**

```python
# tests/test_strings.py — extend
def test_handler_translation_keys_resolve():
    from custom_components.email_parcel_tracking.const import HANDLER_SLUGS

    strings = _load("strings.json")
    sensor = strings["entity"]["sensor"]
    assert sensor["next_delivery"]["name"]
    for slug in HANDLER_SLUGS.values():
        assert sensor[slug]["name"]
```
Update `test_config_flow.py::test_options_flow` to submit only `folder`/`lookback_days`/`keep_delivered_days` (no `account`).

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_strings.py tests/test_config_flow.py -v` → FAIL.

- [ ] **Step 3: Implement**
  - `config_flow.py`: remove the `CONF_ACCOUNT` import, the options-flow field, and the `selector`/`EMAIL_DOMAIN` imports if now unused.
  - `diagnostics.py`: `TO_REDACT = {"tracking_number", "order_number"}` (drop `account`/`config_entry_id`).
  - `strings.json` (+ copy to `translations/en.json`): remove the `account` option label; under `entity.sensor` add `next_delivery` and one entry per handler slug:

```json
"entity": {
  "sensor": {
    "next_delivery": { "name": "Next delivery" },
    "amazon": { "name": "Amazon" },
    "tubby_toms": { "name": "Tubby Toms" },
    "rave": { "name": "Rave" },
    "royal_mail": { "name": "Royal Mail" },
    "dhl": { "name": "DHL" },
    "dpd": { "name": "DPD" },
    "dx": { "name": "DX" },
    "evri": { "name": "Evri" },
    "fedex": { "name": "FedEx" },
    "ups": { "name": "UPS" }
  },
  ...
}
```
  - `icons.json`: under `entity.sensor` give `next_delivery` (`mdi:truck-fast`) and each handler slug an icon (`mdi:package-variant-closed`), keep button/calendar.

- [ ] **Step 4: Run** — `python -m pytest tests/test_strings.py tests/test_config_flow.py tests/test_diagnostics.py -v` → PASS. (`test_diagnostics` now asserts `order_number`/`tracking_number` redacted.)

- [ ] **Step 5: Commit** — `feat: refresh flow, diagnostics and translations for the new model`

---

### Task 9: quality_scale flips + full verification (ruff, pyright, pytest, hassfest)

**Files:**
- Modify: `custom_components/email_parcel_tracking/quality_scale.yaml`

- [ ] **Step 1: Flip rules** — set `devices: done`, `stale-devices: done`, `entity-disabled-by-default: done`; keep `dynamic-devices` exempt. Confirm `grep -c ': todo' quality_scale.yaml` → `0`.

- [ ] **Step 2: Verify suite**

Run:
```bash
cd /home/juicebox/ha-email-tracking
ruff check .
python -m pyright custom_components/
python -m pytest -q
bash scripts/skill_audit.sh
```
Expected: ruff clean, pyright `0 errors`, all tests pass, audit PASS.

- [ ] **Step 3: hassfest**

Run:
```bash
cd /home/juicebox/HA-core
python -m script.hassfest --integration-path /home/juicebox/ha-email-tracking/custom_components/email_parcel_tracking --action validate
```
Expected: `Invalid integrations: 0`, no warnings.

- [ ] **Step 4: Commit** — `chore: mark device and disabled-by-default rules done`

---

### Task 10: Real redacted e-mail fixture test bed

**Files:**
- Create: `tests/fixtures/emails/` (dir), `tests/fixtures/README.md` (scrub checklist), `tests/fixtures_loader.py`
- Test: `tests/test_fixtures.py`

**Interfaces:**
- Produces: `load_flow(name: str) -> list[dict]` — loads a JSON fixture list of `query_emails`-shaped dicts, shifting relative dates forward to `dt_util.now()`.

- [ ] **Step 1: Add a synthetic paired fixture + loader test** (real user payloads dropped in later)

```python
# tests/fixtures/emails/tubby_royalmail.json
[
    {
        "uid": 1,
        "sender": "info@tubbytoms.com",
        "subject": "Order #12345 received",
        "body": "Thanks for your order",
        "days_ago": 3,
    },
    {
        "uid": 2,
        "sender": "no-reply@royalmail.com",
        "subject": "Your Royal Mail parcel from Tubby Toms Ltd. is on its way",
        "body": "Tracking AB123456789GB",
        "days_ago": 1,
    },
]
```

```python
# tests/test_fixtures.py
from fixtures_loader import load_flow
from custom_components.email_parcel_tracking.api import parse_email
from custom_components.email_parcel_tracking.linking import find_match
from homeassistant.util import dt as dt_util


def test_tubby_royalmail_flow_links_to_one_parcel():
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
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_fixtures.py -v` → FAIL (loader missing).

- [ ] **Step 3: Implement `tests/fixtures_loader.py`**

```python
"""Load redacted e-mail fixtures, shifting relative dates to 'now'."""

import json
from pathlib import Path

from homeassistant.util import dt as dt_util

_DIR = Path(__file__).parent / "fixtures" / "emails"


def load_flow(name: str) -> list[dict]:
    raw = json.loads((_DIR / f"{name}.json").read_text())
    now = dt_util.now()
    out = []
    for item in raw:
        days_ago = item.pop("days_ago", 0)
        when = now - dt_util.dt.timedelta(days=days_ago)
        out.append({**item, "date": when.strftime("%a, %d %b %Y %H:%M:%S %z")})
    return out
```
  And `tests/fixtures/README.md` — the scrub checklist: replace recipient name/address/e-mail/postcode; replace order numbers with `TubbyT-#####`/format-valid synthetics; replace tracking numbers with format-valid synthetics; keep sender address, subject wording, and the retailer mention verbatim (they drive parsing); set `days_ago` instead of a hard date.

- [ ] **Step 4: Run** — `python -m pytest tests/test_fixtures.py -v` → PASS.

- [ ] **Step 5: Commit** — `test: add redacted e-mail fixture test bed`

---

## Self-Review

**Spec coverage:** device (T6), remove CONF_ACCOUNT (T2/T5/T8), lifecycle Shipment (T1), vendor senders + parsing (T2/T3), linking incl. fuzzy + guard (T4), coordinator uid ingest (T5), total + handler + opt-in per-parcel + auto-enable (T7), diagnostics/strings/icons (T8), quality_scale + hassfest (T9), redacted-fixture test bed (T10). All spec sections mapped.

**Placeholder scan:** the `...` in Task 7 tests are explicitly "fill using existing helpers" for setup boilerplate, with the asserted behaviour spelled out; all logic-bearing code is complete.

**Type consistency:** `parse_email -> ParsedEmail(shipment, retailer_name)` used consistently (T3, T5, T10); `find_match(shipments, incoming, retailer_name) -> uid|None` (T4, T5, T10); `Shipment` fields/`carrier_label`/`merge` consistent (T1, T5, T7); handler unique_id `{entry}_handler_{slug}` consistent (T7, T8 tests).
