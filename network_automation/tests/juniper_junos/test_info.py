# network_automation/tests/juniper_junos/test_info.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.juniper_junos.info import (
    _parse_show_version,
    _parse_chassis_hardware,
    extract_discovery_facts,
    get_info,
    read_info,
)


_SHOW_VERSION = """
Hostname: r1
Model: mx204
Junos: 21.4R3-S5.4
JUNOS OS Kernel 64-bit  [20230505.0e8b6d4_builder_stable_12_214]
JUNOS OS libs [20230505.0e8b6d4_builder_stable_12_214]
JUNOS Packet Forwarding Engine Support (MX/EX92XX Common) [21.4R3-S5.4]
"""

_SHOW_VERSION_LEGACY = """
Hostname: sw1
Model: ex4200-48t
JUNOS Base OS boot [12.3R12.4]
JUNOS Base OS Software Suite [12.3R12.4]
JUNOS Kernel Software Suite [12.3R12.4]
"""

_SHOW_VERSION_DUAL_RE = """
re0:
--------------------------------------------------------------------------
Hostname: r2-re0
Model: mx480
Junos: 22.4R2-S2.6
JUNOS OS Kernel 64-bit  [20231012.c1a2b3d_builder_stable_12_224]

re1:
--------------------------------------------------------------------------
Hostname: r2-re1
Model: mx480
Junos: 22.4R2-S2.6
"""

_SHOW_CHASSIS_HARDWARE = """
Hardware inventory:
Item             Version  Part number  Serial number     Description
Chassis                                JN1234ABCDEF      MX204
Midplane         REV 27   750-070866   ACRB1234          Lower Backplane
Routing Engine 0          BUILTIN      BUILTIN           RE-S-1600x8
"""


@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- _parse_show_version ----------

def test_parse_show_version():
    parsed = _parse_show_version(_SHOW_VERSION)

    assert parsed["name"] == "r1"
    assert parsed["version"] == "21.4R3-S5.4"
    assert parsed["model"] == "mx204"


def test_parse_show_version_legacy_format():
    parsed = _parse_show_version(_SHOW_VERSION_LEGACY)

    assert parsed["name"] == "sw1"
    assert parsed["version"] == "12.3R12.4"
    assert parsed["model"] == "ex4200-48t"


def test_parse_show_version_dual_re_uses_first_block():
    parsed = _parse_show_version(_SHOW_VERSION_DUAL_RE)

    assert parsed["name"] == "r2-re0"
    assert parsed["version"] == "22.4R2-S2.6"
    assert parsed["model"] == "mx480"


def test_parse_show_version_missing_hostname():
    with pytest.raises(ValueError, match="Hostname not found"):
        _parse_show_version("Model: mx204\nJunos: 21.4R3-S5.4")


def test_parse_show_version_missing_model():
    with pytest.raises(ValueError, match="Model not found"):
        _parse_show_version("Hostname: r1\nJunos: 21.4R3-S5.4")


def test_parse_show_version_missing_version():
    with pytest.raises(ValueError, match="Version not found"):
        _parse_show_version("Hostname: r1\nModel: mx204")


# ---------- _parse_chassis_hardware ----------

def test_parse_chassis_hardware():
    assert _parse_chassis_hardware(_SHOW_CHASSIS_HARDWARE) == "JN1234ABCDEF"


def test_parse_chassis_hardware_missing_serial():
    with pytest.raises(ValueError, match="Chassis serial number not found"):
        _parse_chassis_hardware("Hardware inventory:\nItem  Version  Part number  Serial number  Description")


# ---------- get_info ----------

def test_get_info_parsing(juniper_junos_client, fake_conn):
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_CHASSIS_HARDWARE]
    juniper_junos_client.conn = fake_conn

    info = get_info(juniper_junos_client)

    assert juniper_junos_client.current_version == "21.4R3-S5.4"
    assert info == {
        "units": [
            {
                "id": 0,
                "role": "master",
                "version": "21.4R3-S5.4",
                "name": "r1",
                "serial": "JN1234ABCDEF",
                "model": "mx204",
            }
        ]
    }
    fake_conn.send_command.assert_any_call("show version")
    fake_conn.send_command.assert_any_call("show chassis hardware")


# ---------- read_info workflow ----------

def test_read_info_returns_result(monkeypatch, juniper_junos_client, fake_conn):
    monkeypatch.setattr(juniper_junos_client, "connect", lambda: None)
    monkeypatch.setattr(juniper_junos_client, "disconnect", lambda: None)
    juniper_junos_client.conn = fake_conn
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_CHASSIS_HARDWARE]

    from network_automation.results import OperationResult

    result = read_info(juniper_junos_client, return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "info"
    unit = result.metadata["units"][0]
    assert unit["name"] == "r1"
    assert unit["version"] == "21.4R3-S5.4"
    assert unit["model"] == "mx204"
    assert unit["serial"] == "JN1234ABCDEF"


def test_read_info_default_return(monkeypatch, juniper_junos_client, fake_conn):
    monkeypatch.setattr(juniper_junos_client, "connect", lambda: None)
    monkeypatch.setattr(juniper_junos_client, "disconnect", lambda: None)
    juniper_junos_client.conn = fake_conn
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_CHASSIS_HARDWARE]

    info = read_info(juniper_junos_client)

    assert "units" in info
    assert info["units"][0]["serial"] == "JN1234ABCDEF"


def test_read_info_failure_marks_result_and_disconnects(monkeypatch, juniper_junos_client, fake_conn):
    disconnected = []
    monkeypatch.setattr(juniper_junos_client, "connect", lambda: None)
    monkeypatch.setattr(juniper_junos_client, "disconnect", lambda: disconnected.append(True))
    juniper_junos_client.conn = fake_conn
    fake_conn.send_command.side_effect = [_SHOW_VERSION, "Hardware inventory:\n"]

    with pytest.raises(ValueError, match="Chassis serial number not found"):
        read_info(juniper_junos_client)

    assert disconnected == [True]


# ---------- extract_discovery_facts ----------

def test_extract_discovery_facts(monkeypatch, juniper_junos_client, fake_conn):
    monkeypatch.setattr(juniper_junos_client, "connect", lambda: None)
    monkeypatch.setattr(juniper_junos_client, "disconnect", lambda: None)
    juniper_junos_client.conn = fake_conn
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_CHASSIS_HARDWARE]

    facts = extract_discovery_facts(read_info(juniper_junos_client)["units"])

    assert facts == {
        "serial": "JN1234ABCDEF",
        "software_version": "21.4R3-S5.4",
        "model": "mx204",
    }
