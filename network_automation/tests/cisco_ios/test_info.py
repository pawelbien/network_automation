# network_automation/tests/cisco_ios/test_info.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.cisco_ios.info import (
    _parse_show_version,
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


@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- _parse_show_version ----------

def test_parse_show_version():
    parsed = _parse_show_version(_SHOW_VERSION)

    assert parsed["name"] == "Switch"
    assert parsed["version"] == "17.9.4a"
    assert parsed["model"] == "C9300-24T"
    assert parsed["serial"] == "FCW1234A0BC"


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

    assert cisco_client.current_version == "17.9.4a"
    assert info == {
        "units": [
            {
                "id": 0,
                "role": "master",
                "version": "17.9.4a",
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
    assert unit["version"] == "17.9.4a"
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
