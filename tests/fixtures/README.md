# Redacted e-mail fixtures

`emails/*.json` hold `query_emails`-shaped e-mail dicts used to drive
end-to-end parsing/linking tests against realistic payloads. Real user
e-mails may be dropped in here, but **must be scrubbed first**:

- Replace the recipient's name, postal address, and e-mail address.
- Replace order numbers with a format-valid synthetic
  (e.g. `TubbyT-#####`), not the real one.
- Replace tracking numbers with a format-valid synthetic (same courier
  pattern, different digits).
- **Keep verbatim**: the sender address, the subject wording, and any
  retailer-name mention — these drive classification/parsing and must
  stay real to be a useful fixture.
- Set a `days_ago` field instead of a hard-coded date; the loader
  (`tests/fixtures_loader.py`) shifts it relative to `dt_util.now()` so
  fixtures never go stale.
