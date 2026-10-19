# network_automation/tests/dcn_os/test_client.py

import pytest

from network_automation.factory import get_client
from network_automation.platforms.dcn_os.client import DcnOS
from network_automation.results import OperationResult


def test_device_dict(dcn_os_client):
    assert dcn_os_client.device["device_type"] == "cisco_ios"
    assert dcn_os_client.device["host"] == "1.1.1.1"
    assert dcn_os_client.device["username"] == "admin"
    assert dcn_os_client.device["key_file"] == "key"
    assert dcn_os_client.device["passphrase"] == "pass"
    assert dcn_os_client.device["disabled_algorithms"] is None


def test_disabled_algorithms_passed_through():
    legacy = {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}
    client = DcnOS(host="1.1.1.1", username="admin", disabled_algorithms=legacy)

    assert client.device["disabled_algorithms"] == legacy


def test_factory_returns_dcn_os():
    client = get_client(device_type="dcn_os", host="1.1.1.1", username="admin")

    assert isinstance(client, DcnOS)


@pytest.fixture
def info_result():
    result = OperationResult(success=True, operation="info")
    result.metadata["units"] = [{
        "id": 0,
        "role": "master",
        "version": "V700R001C001B001",
        "name": "sw1",
        "serial": "SW0000000000000001",
        "model": "S5750E-28X-SI",
        "devtype_id": "360",
    }]
    return result


def test_get_discovery_facts(monkeypatch, dcn_os_client, info_result):
    monkeypatch.setattr(dcn_os_client, "get_info", lambda return_result=False: info_result)

    assert dcn_os_client.get_discovery_facts() == {
        "serial": "SW0000000000000001",
        "software_version": "V700R001C001B001",
        "model": "S5750E-28X-SI",
        "devtype_id": "360",
    }


def test_get_discovery_facts_return_result(monkeypatch, dcn_os_client, info_result):
    monkeypatch.setattr(dcn_os_client, "get_info", lambda return_result=False: info_result)

    result = dcn_os_client.get_discovery_facts(return_result=True)

    assert result is info_result
    assert result.metadata["software_version"] == "V700R001C001B001"
    assert result.metadata["devtype_id"] == "360"
