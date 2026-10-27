"""Real Home Assistant tests; never install the lightweight contract doubles here."""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def enable_hpvc(enable_custom_integrations):
    yield
