# network_automation/tests/cisco_ios/conftest.py

import pytest
from network_automation.platforms.cisco_ios.client import CiscoIOS


@pytest.fixture
def cisco_client():
    return CiscoIOS(
        host="1.1.1.1",
        username="admin",
        key_file="key",
        passphrase="pass",
        connect_retries=1,
        connect_delay=0,
    )
