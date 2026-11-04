"""Assert every translation and icon key the code uses resolves in the JSON files."""

import json
from pathlib import Path
import re
from typing import Any

from custom_components.email_parcel_tracking.const import HANDLER_SLUGS

_PKG = Path(__file__).parent.parent / "custom_components" / "email_parcel_tracking"
_PLATFORMS = ("button", "calendar", "sensor")
_ATTR_KEY = re.compile(r'_attr_translation_key = "([a-z0-9_]+)"')
_RAISED_KEY = re.compile(r'translation_key="([a-z0-9_]+)"')


def _load(name: str) -> dict[str, Any]:
    return json.loads((_PKG / name).read_text())


def _entity_keys(platform: str) -> set[str]:
    keys = set(_ATTR_KEY.findall((_PKG / f"{platform}.py").read_text()))
    if platform == "sensor":
        keys |= set(HANDLER_SLUGS.values())
    return keys


def _raised_keys() -> set[str]:
    return {
        key
        for module in _PKG.glob("*.py")
        for key in _RAISED_KEY.findall(module.read_text())
    }


def test_no_strings_json() -> None:
    """Home Assistant loads translations/en.json only, so strings.json must not exist."""
    assert not (_PKG / "strings.json").exists()


def test_entity_translation_keys_resolve() -> None:
    """Every entity translation_key used in code has a name in en.json."""
    entity = _load("translations/en.json")["entity"]
    for platform in _PLATFORMS:
        keys = _entity_keys(platform)
        assert keys, platform
        for key in keys:
            assert entity[platform][key]["name"], (platform, key)


def test_raised_translation_keys_resolve() -> None:
    """Every translation_key raised or used for an issue exists in en.json."""
    strings = _load("translations/en.json")
    known = set(strings["exceptions"]) | set(strings["issues"])
    raised = _raised_keys()
    assert raised
    assert raised <= known, raised - known
    for key in strings["exceptions"]:
        assert strings["exceptions"][key]["message"]


def test_service_translations_resolve() -> None:
    """Every registered action has a name and description in en.json."""
    services = _load("translations/en.json")["services"]
    assert services["rescan"]["name"]
    assert services["rescan"]["description"]


def test_icon_keys_resolve() -> None:
    """Every entity translation_key used in code has an icon in icons.json."""
    icons = _load("icons.json")
    for platform in _PLATFORMS:
        for key in _entity_keys(platform):
            assert icons["entity"][platform][key]["default"], (platform, key)
    assert icons["services"]["rescan"]["service"]
