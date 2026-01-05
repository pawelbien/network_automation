# network_automation/tests/mikrotik_routeros/conftest.py

import pytest
from network_automation.platforms.mikrotik_routeros.client import MikrotikRouterOS


@pytest.fixture
def mikrotik_client():
    return MikrotikRouterOS(
        host="1.1.1.1",
        username="admin",
        key_file="key",
        passphrase="pass",
        firmware_version="7.14",
        connect_retries=1,
        connect_delay=0,
        reconnect_timeout=1,
        reconnect_delay=0,
    )
