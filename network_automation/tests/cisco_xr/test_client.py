# network_automation/tests/cisco_xr/test_client.py

import pytest

from network_automation.results import OperationResult


def test_device_dict(cisco_xr_client):
    assert cisco_xr_client.device["device_type"] == "cisco_xr"
    assert cisco_xr_client.device["host"] == "1.1.1.1"
    assert cisco_xr_client.device["username"] == "admin"
    assert cisco_xr_client.device["key_file"] == "key"
    assert cisco_xr_client.device["passphrase"] == "pass"


def test_upgrade_not_implemented(cisco_xr_client):
    with pytest.raises(NotImplementedError):
        cisco_xr_client.upgrade()


@pytest.fixture
def info_result():
    result = OperationResult(success=True, operation="info")
    result.metadata["units"] = [{"id": 0, "role": "master", "version": "7.3.2", "name": "PE1", "serial": "FOX2401A1BC", "model": "IOS-XRv 9000"}]
    return result


def test_get_discovery_facts(monkeypatch, cisco_xr_client, info_result):
    monkeypatch.setattr(cisco_xr_client, "get_info", lambda return_result=False: info_result)

    assert cisco_xr_client.get_discovery_facts() == {"serial": "FOX2401A1BC", "software_version": "7.3.2"}


def test_get_discovery_facts_return_result(monkeypatch, cisco_xr_client, info_result):
    monkeypatch.setattr(cisco_xr_client, "get_info", lambda return_result=False: info_result)

    result = cisco_xr_client.get_discovery_facts(return_result=True)

    assert result is info_result
    assert result.metadata["serial"] == "FOX2401A1BC"
    assert result.metadata["software_version"] == "7.3.2"
    assert "units" in result.metadata
