"""Load redacted e-mail fixtures, shifting relative dates to 'now'."""

from datetime import timedelta
import json
from pathlib import Path

from homeassistant.util import dt as dt_util

_DIR = Path(__file__).parent / "fixtures" / "emails"


def load_flow(name: str) -> list[dict]:
    """Load a fixture list of e-mails, resolving ``days_ago`` to a date."""
    raw = json.loads((_DIR / f"{name}.json").read_text())
    now = dt_util.now()
    out = []
    for item in raw:
        days_ago = item.pop("days_ago", 0)
        when = now - timedelta(days=days_ago)
        out.append({**item, "date": when.strftime("%a, %d %b %Y %H:%M:%S %z")})
    return out
