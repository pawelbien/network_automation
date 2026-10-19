# network_automation/tests/dcn_os/conftest.py

import pytest
from network_automation.platforms.dcn_os.client import DcnOS


@pytest.fixture
def dcn_os_client():
    return DcnOS(
        host="1.1.1.1",
        username="admin",
        key_file="key",
        passphrase="pass",
        connect_retries=1,
        connect_delay=0,
    )
