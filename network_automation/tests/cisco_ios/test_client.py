# network_automation/tests/cisco_ios/test_client.py

import pytest


def test_device_dict(cisco_client):
    assert cisco_client.device["device_type"] == "cisco_ios"
    assert cisco_client.device["host"] == "1.1.1.1"
    assert cisco_client.device["username"] == "admin"
    assert cisco_client.device["key_file"] == "key"
    assert cisco_client.device["passphrase"] == "pass"


def test_upgrade_not_implemented(cisco_client):
    with pytest.raises(NotImplementedError):
        cisco_client.upgrade()
