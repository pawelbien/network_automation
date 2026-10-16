# network_automation/tests/cisco_ios/test_info.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.cisco_ios.info import (
    _parse_show_version,
    extract_discovery_facts,
    get_info,
    read_info,
)


_SHOW_VERSION = """
Cisco IOS XE Software, Version 17.09.04a
Cisco IOS Software [Cupertino], Catalyst L3 Switch Software (CAT9K_IOSXE), Version 17.9.4a, RELEASE SOFTWARE (fc3)

Switch uptime is 2 weeks, 3 days, 4 hours, 5 minutes

cisco C9300-24T (X86) processor with 1441075K/6147K bytes of memory.
Processor board ID FCW1234A0BC
"""

_SHOW_VERSION_XE_3 = """
Cisco IOS XE Software, Version 03.18.06.SP.156-2.SP6-ext
Cisco IOS Software, ASR920 Software (PPC_LINUX_IOSD-UNIVERSALK9_NPE-M), Version 15.6(2)SP6, RELEASE SOFTWARE (fc1)

r015 uptime is 1 year, 2 weeks, 3 days, 4 hours, 5 minutes

cisco ASR-920-4SZ-A (Freescale P2020) processor (revision 1.0 GHz) with 900263K/6147K bytes of memory.
Processor board ID CAT2102U4MZ
"""

_SHOW_VERSION_CLASSIC = """
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E8, RELEASE SOFTWARE (fc2)

sw01 uptime is 5 days, 1 hour, 2 minutes

cisco WS-C2960X-24TS-L (APM86XXX) processor (revision B0) with 524288K bytes of memory.
Processor board ID FOC1234X5YZ
"""


@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- _parse_show_version ----------

def test_parse_show_version():
    parsed = _parse_show_version(_SHOW_VERSION)

    assert parsed["name"] == "Switch"
    assert parsed["version"] == "17.09.04a"
    assert parsed["model"] == "C9300-24T"
    assert parsed["serial"] == "FCW1234A0BC"


def test_parse_show_version_xe_3_prefers_xe_version():
    parsed = _parse_show_version(_SHOW_VERSION_XE_3)

    assert parsed["name"] == "r015"
    assert parsed["version"] == "03.18.06.SP.156-2.SP6-ext"
    assert parsed["model"] == "ASR-920-4SZ-A"
    assert parsed["serial"] == "CAT2102U4MZ"


def test_parse_show_version_classic_ios():
    parsed = _parse_show_version(_SHOW_VERSION_CLASSIC)

    assert parsed["name"] == "sw01"
    assert parsed["version"] == "15.2(7)E8"
    assert parsed["model"] == "WS-C2960X-24TS-L"
    assert parsed["serial"] == "FOC1234X5YZ"


def test_parse_show_version_missing_hostname():
    with pytest.raises(ValueError, match="Hostname not found"):
        _parse_show_version("Version 17.9.4a,\ncisco C9300-24T (X86)\nProcessor board ID FCW1234A0BC")


def test_parse_show_version_missing_version():
    with pytest.raises(ValueError, match="Version not found"):
        _parse_show_version("Switch uptime is 1 day\ncisco C9300-24T (X86)\nProcessor board ID FCW1234A0BC")


def test_parse_show_version_missing_model():
    with pytest.raises(ValueError, match="Model not found"):
        _parse_show_version("Switch uptime is 1 day\nVersion 17.9.4a,\nProcessor board ID FCW1234A0BC")


def test_parse_show_version_missing_serial():
    with pytest.raises(ValueError, match="Serial number not found"):
        _parse_show_version("Switch uptime is 1 day\nVersion 17.9.4a,\ncisco C9300-24T (X86)")


# ---------- get_info ----------

def test_get_info_parsing(cisco_client, fake_conn):
    fake_conn.send_command.return_value = _SHOW_VERSION
    cisco_client.conn = fake_conn

    info = get_info(cisco_client)

    assert cisco_client.current_version == "17.09.04a"
    assert info == {
        "units": [
            {
                "id": 0,
                "role": "master",
                "version": "17.09.04a",
                "name": "Switch",
                "serial": "FCW1234A0BC",
                "model": "C9300-24T",
            }
        ]
    }


# ---------- read_info workflow ----------

def test_read_info_returns_result(monkeypatch, cisco_client, fake_conn):
    monkeypatch.setattr(cisco_client, "connect", lambda: None)
    monkeypatch.setattr(cisco_client, "disconnect", lambda: None)
    cisco_client.conn = fake_conn
    fake_conn.send_command.return_value = _SHOW_VERSION

    from network_automation.results import OperationResult

    result = read_info(cisco_client, return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "info"
    unit = result.metadata["units"][0]
    assert unit["name"] == "Switch"
    assert unit["version"] == "17.09.04a"
    assert unit["model"] == "C9300-24T"
    assert unit["serial"] == "FCW1234A0BC"


def test_read_info_default_return(monkeypatch, cisco_client, fake_conn):
    monkeypatch.setattr(cisco_client, "connect", lambda: None)
    monkeypatch.setattr(cisco_client, "disconnect", lambda: None)
    cisco_client.conn = fake_conn
    fake_conn.send_command.return_value = _SHOW_VERSION

    info = read_info(cisco_client)

    assert "units" in info
    assert info["units"][0]["serial"] == "FCW1234A0BC"


# ---------- extract_discovery_facts ----------

def test_extract_discovery_facts(monkeypatch, cisco_client, fake_conn):
    monkeypatch.setattr(cisco_client, "connect", lambda: None)
    monkeypatch.setattr(cisco_client, "disconnect", lambda: None)
    cisco_client.conn = fake_conn
    fake_conn.send_command.return_value = _SHOW_VERSION

    facts = extract_discovery_facts(read_info(cisco_client)["units"])

    assert facts == {"serial": "FCW1234A0BC", "software_version": "17.09.04a"}
