# network_automation/tests/juniper_junos/conftest.py

import pytest
from network_automation.platforms.juniper_junos.client import JuniperJunos


@pytest.fixture
def juniper_junos_client():
    return JuniperJunos(
        host="1.1.1.1",
        username="admin",
        key_file="key",
        passphrase="pass",
        connect_retries=1,
        connect_delay=0,
    )
