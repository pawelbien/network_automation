# network_automation/tests/opnsense/conftest.py

import pytest
from network_automation.platforms.opnsense.client import OPNsense


@pytest.fixture
def opnsense_client():
    return OPNsense(
        host="1.1.1.1",
        username="admin",
        password="secret",
        connect_retries=1,
        connect_delay=0,
    )
