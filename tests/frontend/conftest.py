"""Real HA and real browser fixture wiring; no production connection."""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def enable_hpvc(enable_custom_integrations):
    yield
