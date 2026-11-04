# Email Parcel Tracking

![Email Parcel Tracking](custom_components/email_parcel_tracking/brand/logo.png)

Track parcel deliveries in Home Assistant by scanning your e-mail — no courier
APIs or accounts required. It reads order, dispatch, and delivery e-mails through
the [Email HA](https://github.com/PineappleEmperor/email-ha) integration and
exposes the next delivery, one sensor per retailer or courier, opt-in per-parcel
sensors, and a delivery calendar.

> [!NOTE]
> **AI assistance:** I'm a programmer; this project is built with AI (Claude, via Claude Code) for implementation, code review, and QA — under human direction, guided by my [`ha-integration`](https://github.com/PineappleEmperor/ha-skills) skill. Architecture and final review are mine; every change is human-reviewed before it merges.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=PineappleEmperor&repository=ha-email-tracking&category=integration)

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=email_parcel_tracking)

## Use cases

- Get a notification when a parcel is due today.
- Show a "parcels arriving" card on a dashboard, counting what's in transit.
- Put delivery ETAs on a calendar alongside the rest of your day.
- Trigger automations (turn on the porch light, mute the doorbell) around an
  expected delivery — without paying for a courier tracking API.

## Supported retailers & couriers

Parcels are recognised by sender address and subject line. Currently supported:

| Sender | Recognised as | Statuses detected |
|--------|---------------|-------------------|
| Amazon (`auto-confirm`, `shipment-tracking`, `order-update`) | retailer | Ordered, Dispatched, Out for delivery, Delivered, Exception |
| Tubby Toms | retailer | Ordered |
| Rave Coffee | retailer | Ordered, Dispatched |
| Royal Mail | courier | Dispatched, Out for delivery, Delivered, Exception |
| DHL | courier | Dispatched, Out for delivery, Delivered |
| DPD | courier | Ordered, Out for delivery |
| DX | courier | Dispatched, Out for delivery, Delivered |
| Evri | courier | Dispatched, Out for delivery, Delivered |
| FedEx | courier | Dispatched, Out for delivery, Delivered |
| UPS | courier | Dispatched, Out for delivery, Delivered |

A retailer's order e-mail and the courier's later tracking e-mails are linked
into one parcel: by order number, by tracking number, or — for a courier e-mail
that names the retailer — by retailer name within a few days of the order.

Adding a carrier is a data change in `const.py` (`_CARRIERS`, plus `RETAILERS` for
a retailer) and, if its order or tracking-number format is distinctive, `api.py`
(`_ORDER_PATTERNS`, `_TRACKING_PATTERNS`).

## Supported functions (entities & actions)

All entities belong to one **Email Parcel Tracking** service device.

| Entity | Description |
|--------|-------------|
| `sensor.email_parcel_tracking_next_delivery` | Timestamp of the soonest active delivery. Attributes: `active_count`, `next_carrier`, `by_carrier`, and `parcels` (every active parcel) |
| `sensor.email_parcel_tracking_<handler>` | One per retailer/courier above (`…_royal_mail`, `…_amazon`, …): the soonest delivery that handler is carrying. Disabled until that handler first has an active parcel, then enabled automatically |
| `sensor.email_parcel_tracking_<handler>_<id>` | One per tracked parcel, **disabled by default**: state is its delivery status (`Ordered`…`Delivered`/`Exception`), with order number, tracking number, retailer, courier and ETA attributes. Removed when the parcel is pruned |
| `calendar.email_parcel_tracking_deliveries` | Active deliveries with a known ETA, as all-day events |
| `button.email_parcel_tracking_rescan_inbox` | Re-scan the inbox on demand |

### Actions

- **`email_parcel_tracking.rescan`** — re-scan the inbox immediately for every
  configured entry. Takes no fields. Raises an error if the integration is not
  set up, or if the underlying Email HA query fails.

## How the data updates

This integration holds no IMAP connection of its own:

1. **On startup** it runs one scan — calling `email_imap.query_emails` for known
   parcel senders within the lookback window — and merges the result with the
   parcels persisted from the previous run.
2. **Live** it subscribes to the `email_imap_new_email` event; each new e-mail is
   fetched in full, parsed, and merged, updating entities immediately (push).
3. E-mails about the same parcel are merged into one, whose status only ever
   advances (Ordered → Dispatched → Out for delivery → Delivered), with
   Exception overriding.

Parcel state is persisted via Home Assistant's storage, so tracked parcels
survive a restart even though the startup scan only looks back a limited window.

## Installation

1. Install and configure [Email HA](https://github.com/PineappleEmperor/email-ha).
2. In HACS, add this repository as a custom repository (category: Integration),
   install **Email Parcel Tracking**, and restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration**, search for
   **Email Parcel Tracking**, and confirm. There are no setup parameters — it has
   no credentials of its own; Email HA owns the mailbox connection.

## Configuration parameters

Set via **Settings → Devices & Services → Email Parcel Tracking → Configure**.
Saving reloads the integration, so a changed folder or lookback takes effect at
once.

| Option | Default | Meaning |
|--------|---------|---------|
| Mail folder to scan | `INBOX` | The Email HA mail folder searched for parcel e-mails |
| Startup scan lookback (days) | `30` | How far back the scan at startup reaches |
| Keep delivered parcels (days) | `3` | Retention before delivered/exception parcels are pruned |

## Automation examples

Notify when the next delivery is due today:

```yaml
automation:
  - alias: Parcel due today
    triggers:
      - trigger: template
        value_template: >-
          {% set next = states('sensor.email_parcel_tracking_next_delivery')
             | as_datetime(none) %}
          {{ next is not none and as_local(next).date() == now().date() }}
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >-
            {{ state_attr('sensor.email_parcel_tracking_next_delivery',
                          'next_carrier') }} parcel due today.
```

Count parcels arriving today from the next-delivery sensor:

```yaml
template:
  - sensor:
      - name: Parcels arriving today
        state: >-
          {{ state_attr('sensor.email_parcel_tracking_next_delivery', 'parcels')
             | selectattr('eta', 'equalto', now().date().isoformat())
             | list | count }}
```

## Known limitations

- **Only recognises the senders listed above.** Unknown senders are ignored;
  a carrier that changes its subject wording or tracking-number format may stop
  being parsed until the rules are updated.
- **Depends entirely on Email HA.** If Email HA is not set up, the integration
  stays in a retry state and raises a repair issue.
- **No catch-up for missed e-mails.** If Email HA's live connection drops or Home
  Assistant is down when an e-mail arrives, that e-mail is only picked up by the
  next startup scan or a manual rescan.
- **Parsing is best-effort.** ETAs are extracted heuristically from e-mail text;
  a missing ETA is left blank rather than guessed.
- **Delivered parcels are pruned** after the retention window, so long-past
  deliveries do not linger as entities. Pruning runs whenever parcels are updated.

## Troubleshooting

- **A parcel never appears.** Confirm Email HA sees the e-mail
  (`email_imap.query_emails`) and that the sender/subject is in the supported
  table. Enable debug logging (below) — a classified e-mail with no extractable
  id is logged at debug.
- **"Email HA integration required" repair issue.** Email HA is not set up or its
  `query_emails` action is unavailable. Set up Email HA, then reload.
- **Nothing updates after startup.** The live path relies on the
  `email_imap_new_email` event; check Email HA is firing it. Use the **Rescan
  inbox** button to force a fresh scan.
- **A retailer or courier sensor is missing.** Per-handler sensors stay disabled
  until that handler has an active parcel; enable one by hand under the
  integration's device if you want it earlier.

```yaml
logger:
  logs:
    custom_components.email_parcel_tracking: debug
```

## Removal

Delete the integration entry from **Settings → Devices & Services**. Persisted
parcel state is removed with the entry. Then remove the repository from HACS.

## Development

```bash
git config core.hooksPath .githooks   # once per clone: commit-msg + prek hooks
pip install -r requirements.test.txt ruff==0.16.9 mypy==2.3.1 prek==0.5.4
ruff check . && ruff format --check .
mypy --config-file mypy.ini custom_components/
pytest tests/ -q
```

CI runs the same checks, plus core's pylint rules, the translation check and the
coverage gate, through
[ha-integration-ci](https://github.com/PineappleEmperor/ha-integration-ci).
