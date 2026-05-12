# network_automation/tests/huawei_vrp/conftest.py

import pytest
from network_automation.platforms.huawei_vrp.client import HuaweiVRP


@pytest.fixture
def huawei_client():
    return HuaweiVRP(
        host="1.1.1.1",
        username="admin",
        password="secret",
        connect_retries=1,
        connect_delay=0,
    )
