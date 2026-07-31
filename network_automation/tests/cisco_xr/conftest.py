# network_automation/tests/cisco_xr/conftest.py

import pytest
from network_automation.platforms.cisco_xr.client import CiscoXR


@pytest.fixture
def cisco_xr_client():
    return CiscoXR(
        host="1.1.1.1",
        username="admin",
        key_file="key",
        passphrase="pass",
        connect_retries=1,
        connect_delay=0,
    )
