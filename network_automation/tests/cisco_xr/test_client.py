# network_automation/tests/cisco_xr/test_client.py

import pytest


def test_device_dict(cisco_xr_client):
    assert cisco_xr_client.device["device_type"] == "cisco_xr"
    assert cisco_xr_client.device["host"] == "1.1.1.1"
    assert cisco_xr_client.device["username"] == "admin"
    assert cisco_xr_client.device["key_file"] == "key"
    assert cisco_xr_client.device["passphrase"] == "pass"


def test_upgrade_not_implemented(cisco_xr_client):
    with pytest.raises(NotImplementedError):
        cisco_xr_client.upgrade()
