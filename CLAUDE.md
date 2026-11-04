# Email Parcel Tracking — project instructions

HACS custom integration. Tracks parcels by scanning e-mail via the **Email HA**
integration (`email_imap` domain) — it holds no IMAP credentials of its own.

## AI sessions
Before writing or modifying integration code (config flow, platforms, manifest,
websocket, services…), invoke the `ha-integration` skill. Re-invoke it after any
`/compact`, since compaction can drop the skill's guidance from context.

## Git hooks
Run `git config core.hooksPath .githooks` once in every clone.

## Architecture

- **Push, not polling.** The coordinator (`coordinator.py`) subscribes to
  `email_imap_new_email` and updates per e-mail; `_async_update_data` runs the
  one-off startup scan via `email_imap.query_emails`. No `update_interval`.
- **`api.py` and `linking.py` are pure** — stdlib, `const` and `models` only, no
  HA imports — so parsing and retailer→courier linking are unit-testable. Keep
  classification, parsing and linking logic there.
- **State** lives on `entry.runtime_data`; parcels persist via `Store`, keyed by a
  synthetic `uid`.
- **One service device per entry** groups every entity. The next-delivery and
  per-handler sensors are static; per-parcel sensors are dynamic, opt-in
  (disabled by default) and removed when their parcel is pruned.

## Conventions

- Target Platinum quality scale; keep `quality_scale.yaml` honest (mark `done`
  only with a test that proves the rule; otherwise `todo` or `exempt` + comment).
- CI is callers of PineappleEmperor/release-flow and ha-integration-ci; never
  copy a workflow body in. Dependabot moves the pins.
- Lint as CI does: `ruff check .`, `ruff format --check .`,
  `mypy --config-file mypy.ini custom_components/`, `pytest tests/ -q`.
- Terse Conventional Commits; **no AI-attribution trailers** (enforced by
  `.githooks/commit-msg`).
