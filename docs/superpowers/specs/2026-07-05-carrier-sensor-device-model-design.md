# Design: device model, per-carrier sensors, retailer→courier linking

Date: 2026-07-05
Status: approved (pending written-spec review)

## Goal

Two coupled changes:

1. **Device-grouped, per-handler sensor model** — one device groups a fixed set
   of "handler" sensors (state = next ETA, catch-all attributes), an overall
   next-delivery total, opt-in per-parcel sensors, plus calendar and button.
2. **Retailer→courier lifecycle** — model one parcel across its life: a retailer
   confirmation (order number, no tracking) linked to the courier's later
   dispatch/delivery (tracking number, names the retailer), including the fuzzy
   name + ETA linking heuristic from the prior art.

## Decisions (from brainstorming)

- Device per config entry; single entry, **all accounts merged** → remove
  `CONF_ACCOUNT`.
- Handler sensor state = **next ETA** (`timestamp`); total sensor = **next ETA
  overall**.
- **Fixed handler sensors** (retailers ∪ couriers), empties disabled-by-default,
  **auto-enabled** when their first parcel arrives.
- **Per-parcel sensors kept opt-in** (`enabled_default=False`).
- Keep calendar + rescan button.
- **Full fuzzy retailer→courier linking now** (name + ETA window ~3 days).

## Data model (`models.py`)

A parcel is one lifecycle object, identified internally by a stable synthetic
`uid`, carrying **both** ids and **both** parties as they become known:

```python
@dataclass(slots=True)
class Shipment:
    uid: str = ""                # stable internal id (assigned by coordinator on insert)
    order_number: str | None = None    # from the retailer confirmation
    tracking_number: str | None = None # from the courier
    retailer: str | None = None
    courier: str | None = None         # may be inferred from the retailer email
    status: str | None = None
    eta: date | None = None
    updated: datetime | None = None

    @property
    def carrier_label(self) -> str | None:
        """Current handler: the courier once known, else the retailer."""
        return self.courier or self.retailer

    def merge(self, other: Shipment) -> None:
        # non-null fields win; status only advances; `updated` only if newer
        # (as today) — now also fills order_number/tracking_number/retailer/courier.
```

`to_dict`/`from_dict` include `uid` and both ids. The `Store` still holds a list
of shipment dicts (schema grows, no migration needed pre-1.0).

Rationale for a synthetic `uid`: identity must survive a parcel gaining a
tracking number after it was first keyed by order number (and vice-versa), so the
storage key can't be either id.

## Classification & parsing (`api.py`, pure)

`parse_email(email, ref) -> ParsedEmail | None` returns a partial shipment
(uid unset) plus the retailer **name text** a courier email mentioned, so the
linker can match. Extend the existing pure functions:

- **Add vendor senders** to `_CARRIERS` in `const.py`:
  - Tubby Toms `info@tubbytoms.com` — "Order #<n>" → `Ordered`; order_number
    `TubbyT-<n>`.
  - Rave `info@ravecoffee.co.uk` — "Order #<n> confirmed" → `Ordered`;
    "shipment from order #<n> is on the way" → `Dispatched`; order_number `<n>`.
- `RETAILERS` becomes `{"Amazon", "Tubby Toms", "Rave"}`; couriers are the rest.
- **Order-number extraction** per retailer (Amazon `\d{3}-\d{7}-\d{7}`, Tubby
  `Order #\d{5}`, Rave `#\d+`).
- **Tracking-number extraction** per courier (unchanged patterns + keyword
  generic).
- **Retailer-name mention** from courier emails, for linking:
  - Royal Mail subject `Your Royal Mail parcel from (?P<name>…) is (on its way|due to be delivered today)`.
  - Evri subject `We've got your (?P<name>…) parcel` / `Your (?P<name>…) parcel`.
  - Others: none (those parcels link only by shared id).
- **Shipper inference** from the Rave confirmation postage line
  (`Royal Mail`→`Royal Mail`, `SmartConsign`/£5→`DX`) → set `courier` on the
  confirmation so a later courier email links on courier too.
- **Retailer-name normalisation** `_normalize_retailer(name)`: lowercase, strip
  `Ltd`/`Ltd.`/`Limited`/punctuation/extra whitespace; an alias map handles
  known mismatches (`"tubby toms" ⇄ retailer label "Tubby Toms"`). Used only for
  linking comparison, never stored.

## Linking (`linking.py`, new pure module)

`find_match(shipments: Iterable[Shipment], incoming: Shipment,
incoming_retailer_name: str | None) -> str | None` returns the `uid` to merge
into, or `None` for a new parcel. Rules, in order:

1. **Order number** — `incoming.order_number` equals an existing
   `order_number` → that uid.
2. **Tracking number** — `incoming.tracking_number` equals an existing
   `tracking_number` → that uid.
3. **Fuzzy retailer→courier** — only when `incoming` has a tracking number but no
   order-number match, and it identifies a retailer (via
   `incoming.retailer`/`incoming_retailer_name`, normalised). Find **unlinked
   confirmations**: existing shipments with `tracking_number is None`, a matching
   normalised retailer, and:
   - if both etas known → `abs(eta_a - eta_b) <= LINK_ETA_WINDOW` (3 days), else
   - if the confirmation has no eta → its `updated` within `LINK_ORDER_WINDOW`
     (14 days) before the courier email.
   **False-merge guard:** link only if **exactly one** candidate qualifies;
   if zero or more than one, do **not** link (leave separate). Ambiguity never
   auto-merges.

Pure and dependency-free; heavily unit-tested (see Testing).

## Coordinator ingest (`coordinator.py`)

`_ingest` for each parsed email:

1. Build the partial `Shipment` (uid unset) from `parse_email`.
2. `uid = find_match(self._shipments.values(), parsed, retailer_name)`.
3. If matched → `self._shipments[uid].merge(parsed)`.
4. Else → assign `parsed.uid = ulid_now()` (`homeassistant.util.ulid`) and insert.

`_prune` and persistence unchanged except they key on `uid`. `_query`/event
handling lose the `account` filter (all accounts).

## Device (`__init__.py`, `entity.py`)

One device per entry:

```python
DeviceInfo(
    identifiers={(DOMAIN, entry.entry_id)},
    name="Email Parcel Tracking",
    manufacturer="Email Parcel Tracking",
    model="Mailbox parcel tracker",
    entry_type=DeviceEntryType.SERVICE,
)
```

Set on `ParcelTrackingEntity` base. Add:

```python
async def async_remove_config_entry_device(hass, entry, device_entry) -> bool:
    # Owns exactly one device (== the entry); never orphaned while loaded.
    return not any(
        domain == DOMAIN and ident == entry.entry_id
        for domain, ident in device_entry.identifiers
    )
```

## Entities

`HANDLER_LABELS` in `const.py` = ordered unique `retailers ∪ couriers`
(Amazon, Tubby Toms, Rave, Royal Mail, DHL, DPD, DX, Evri, FedEx, UPS);
`HANDLER_SLUGS` maps each to a slug via a tiny inline slugifier (const stays
HA-import-light). ETA date → aware datetime via
`dt_util.start_of_local_day(eta)`; `None` when no active ETA.

- **Total** `sensor…_next_delivery` — state = soonest active ETA overall;
  attrs `active_count`, `next_carrier`, `by_carrier{}`, `parcels[]`.
- **Handler sensors** `sensor…_handler_<slug>` (fixed, one per `HANDLER_LABELS`) —
  state = soonest active ETA whose `carrier_label == label`; attrs
  `active_count`, `current{}` (soonest parcel), `parcels[]`.
  `enabled_default` = label has an active parcel at construction; auto-enabled
  later (below). translation_key `<slug>`.
- **Per-parcel** `sensor…_parcel_<uid>` (opt-in, `enabled_default=False`) —
  state = status (ENUM); attrs order_number, tracking_number, retailer, courier,
  eta, updated. Dynamic add/remove, hidden by default.
- **calendar.deliveries**, **button.rescan_inbox** — unchanged, device-attached.

Grouping by `carrier_label` means a parcel moves from its **retailer** sensor
(while just ordered) to its **courier** sensor once dispatched/linked — no double
count.

### Auto-enable a handler sensor on first parcel

Disabled entities aren't instantiated, so enable at platform level. In
`sensor.async_setup_entry`, a coordinator listener enables any handler whose
label now has an active parcel and whose registry row is
`disabled_by is RegistryEntryDisabler.INTEGRATION`, via
`er.async_update_entity(entity_id, disabled_by=None)`. HA auto-reloads the entry
on enable, instantiating the sensor. Only ever enables (no loop).

## Remove CONF_ACCOUNT

Delete the const, the coordinator `account` property + its use in `_query`/
`_handle_new_email`, the options-flow field + `account` string, and
`account`/`config_entry_id` from diagnostics `TO_REDACT` (keep
`tracking_number`).

## quality_scale deltas

- `devices` exempt → **done**; `stale-devices` exempt → **done** (handler + test);
  `entity-disabled-by-default` exempt → **done**.
- `dynamic-devices` stays **exempt** (one static device).
- Keep `"quality_scale": "platinum"`.

## Migration

Pre-release (0.1.0). Old unique_ids abandoned; new scheme `{entry}_next_delivery`,
`{entry}_handler_<slug>`, `{entry}_parcel_<uid>`. No migration handler. `Store`
schema grows (adds `uid`, `order_number`); `from_dict` tolerates missing keys, so
old persisted rows load (they simply lack a uid → assigned on load).

## Testing

Pure/unit (highest value):
- **Linking** `find_match`: order-number match; tracking-number match; fuzzy
  link on retailer name + eta within window; **no** link when two candidate
  confirmations exist (ambiguity guard); no link when retailer differs; no link
  when eta outside window; confirmation-without-eta recency-window path.
- Retailer-name extraction (RM/Evri), normalisation (`Tubby Toms Ltd.` →
  `Tubby Toms`), Rave shipper inference.
- Shipment `merge` fills ids/parties, advances status, keeps newer `updated`.

Integration:
- Device created; every entity linked to it; `async_remove_config_entry_device`
  False for live device / True for foreign.
- Handler sensor ETA/count/current/parcels; a parcel moves retailer→courier
  sensor across the handoff (grouping by `carrier_label`).
- Total sensor ETA/active_count/next_carrier/by_carrier.
- Disabled empty handler → after a parcel arrives, registry row flips to
  `disabled_by is None`; post-reload it has state.
- Per-parcel sensor registered disabled by default.
- **End-to-end handoff**: a Tubby Toms confirmation then a Royal Mail dispatch
  naming Tubby Toms → **one** parcel (both ids, courier=Royal Mail), counted
  once, under the Royal Mail handler.
- Strings/icons resolve for new handler translation keys; existing suites updated
  for removed `CONF_ACCOUNT` and new ids/uid keying.

### Real redacted e-mail fixtures (test bed)

User provides real captured e-mail flows (e.g. a Tubby Toms confirmation + its
Royal Mail dispatch/delivery). Store scrubbed copies under
`tests/fixtures/emails/<carrier>/<case>.json` (or `.eml`), redacting PII
(recipient name/address/e-mail, postcodes, order/tracking numbers replaced with
synthetic-but-format-valid tokens). A small loader turns each into a
`query_emails`-shaped dict. End-to-end tests parametrise over these through the
mocked email-ha boundary and assert the resulting parcel(s): correct handler,
status, id extraction, and — for paired flows — that the confirmation and courier
e-mails link into one parcel. Dates in fixtures are shifted forward at load time
(not `freeze_time`) so "upcoming" ETAs stay upcoming, per the skill's fixture
guidance. A documented scrub checklist keeps real PII out of the repo.

## Out of scope

- Multi-account separation (single entry chosen).
- Per-parcel devices; reconfigure flow (still exempt).
- Live-inbox regex validation (empirical; needs a real mailbox).
- Retailers beyond Amazon/Tubby Toms/Rave and couriers beyond the current eight
  (data additions later).
