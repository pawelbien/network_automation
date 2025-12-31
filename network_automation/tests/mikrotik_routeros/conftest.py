# network_automation/tests/conftest.py

import pytest
from network_automation.platforms.mikrotik_routeros.client import MikrotikRouterOS


@pytest.fixture
def updater():
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
