# network_automation/tests/cisco_ios/test_client.py

import pytest

from network_automation.results import OperationResult


def test_device_dict(cisco_client):
    assert cisco_client.device["device_type"] == "cisco_ios"
    assert cisco_client.device["host"] == "1.1.1.1"
    assert cisco_client.device["username"] == "admin"
    assert cisco_client.device["key_file"] == "key"
    assert cisco_client.device["passphrase"] == "pass"


def test_upgrade_not_implemented(cisco_client):
    with pytest.raises(NotImplementedError):
        cisco_client.upgrade()


@pytest.fixture
def info_result():
    result = OperationResult(success=True, operation="info")
    result.metadata["units"] = [{"id": 0, "role": "master", "version": "17.9.4a", "name": "Switch", "serial": "FCW1234A0BC", "model": "C9300-24T"}]
    return result


def test_get_discovery_facts(monkeypatch, cisco_client, info_result):
    monkeypatch.setattr(cisco_client, "get_info", lambda return_result=False: info_result)

    assert cisco_client.get_discovery_facts() == {"serial": "FCW1234A0BC", "software_version": "17.9.4a"}


def test_get_discovery_facts_return_result(monkeypatch, cisco_client, info_result):
    monkeypatch.setattr(cisco_client, "get_info", lambda return_result=False: info_result)

    result = cisco_client.get_discovery_facts(return_result=True)

    assert result is info_result
    assert result.metadata["serial"] == "FCW1234A0BC"
    assert result.metadata["software_version"] == "17.9.4a"
    assert "units" in result.metadata
