"""Fixtures for the integration's tests."""

import pytest

# Without this import, setup fails with "Integration not found".
import custom_components  # noqa: F401


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components/ in every test."""
