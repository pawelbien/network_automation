# network_automation/tests/juniper_junos/test_client.py

import pytest

from network_automation.factory import get_client
from network_automation.platforms.juniper_junos.client import JuniperJunos
from network_automation.results import OperationResult


def test_device_dict(juniper_junos_client):
    assert juniper_junos_client.device["device_type"] == "juniper_junos"
    assert juniper_junos_client.device["host"] == "1.1.1.1"
    assert juniper_junos_client.device["username"] == "admin"
    assert juniper_junos_client.device["key_file"] == "key"
    assert juniper_junos_client.device["passphrase"] == "pass"


def test_factory_returns_juniper_junos():
    client = get_client(device_type="juniper_junos", host="1.1.1.1", username="admin")

    assert isinstance(client, JuniperJunos)


def test_upgrade_not_implemented(juniper_junos_client):
    with pytest.raises(NotImplementedError):
        juniper_junos_client.upgrade()


@pytest.fixture
def info_result():
    result = OperationResult(success=True, operation="info")
    result.metadata["units"] = [{"id": 0, "role": "master", "version": "21.4R3-S5.4", "name": "r1", "serial": "JN1234ABCDEF", "model": "mx204"}]
    return result


def test_get_discovery_facts(monkeypatch, juniper_junos_client, info_result):
    monkeypatch.setattr(juniper_junos_client, "get_info", lambda return_result=False: info_result)

    assert juniper_junos_client.get_discovery_facts() == {
        "serial": "JN1234ABCDEF",
        "software_version": "21.4R3-S5.4",
        "model": "mx204",
    }


def test_get_discovery_facts_return_result(monkeypatch, juniper_junos_client, info_result):
    monkeypatch.setattr(juniper_junos_client, "get_info", lambda return_result=False: info_result)

    result = juniper_junos_client.get_discovery_facts(return_result=True)

    assert result is info_result
    assert result.metadata["serial"] == "JN1234ABCDEF"
    assert result.metadata["software_version"] == "21.4R3-S5.4"
    assert result.metadata["model"] == "mx204"
    assert "units" in result.metadata
