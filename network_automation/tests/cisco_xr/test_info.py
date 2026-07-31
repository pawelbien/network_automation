# network_automation/tests/cisco_xr/test_info.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.cisco_xr.info import (
    _parse_show_version,
    _parse_inventory,
    get_info,
    read_info,
)


_SHOW_VERSION = """
Cisco IOS XR Software, Version 7.3.2
Copyright (c) 2013-2021 by Cisco Systems, Inc.

ROM: GRUB, Version 1.99(0), predownload

PE1 uptime is 3 weeks, 2 days, 4 hours, 12 minutes
System image file is "bootflash:disk0/xrv9k-full-x-7.3.2/mdata/boot/initrd.img"

cisco IOS-XRv 9000 () processor with 8388608K bytes of memory.
"""

_SHOW_INVENTORY = """
NAME: "Rack 0", DESCR: "Cisco IOS-XRv 9000 Centralized Virtual Router"
PID: R-IOSXRV9000-CC  , VID: V01, SN: FOX2401A1BC

NAME: "0/RP0/CPU0", DESCR: "Cisco IOS-XRv 9000 Route Processor"
PID: R-IOSXRV9000-RP  , VID: V01, SN:
"""


@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- _parse_show_version ----------

def test_parse_show_version():
    parsed = _parse_show_version(_SHOW_VERSION)

    assert parsed["name"] == "PE1"
    assert parsed["version"] == "7.3.2"
    assert parsed["model"] == "IOS-XRv 9000"


def test_parse_show_version_missing_hostname():
    with pytest.raises(ValueError, match="Hostname not found"):
        _parse_show_version("Cisco IOS XR Software, Version 7.3.2\ncisco IOS-XRv 9000 ()")


def test_parse_show_version_missing_version():
    with pytest.raises(ValueError, match="Version not found"):
        _parse_show_version("PE1 uptime is 1 day\ncisco IOS-XRv 9000 ()")


def test_parse_show_version_missing_model():
    with pytest.raises(ValueError, match="Model not found"):
        _parse_show_version("PE1 uptime is 1 day\nCisco IOS XR Software, Version 7.3.2")


# ---------- _parse_inventory ----------

def test_parse_inventory():
    assert _parse_inventory(_SHOW_INVENTORY) == "FOX2401A1BC"


def test_parse_inventory_missing_serial():
    with pytest.raises(ValueError, match="Serial number not found"):
        _parse_inventory('NAME: "Rack 0", DESCR: "..."\nPID: X, VID: V01')


# ---------- get_info ----------

def test_get_info_parsing(cisco_xr_client, fake_conn):
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_INVENTORY]
    cisco_xr_client.conn = fake_conn

    info = get_info(cisco_xr_client)

    assert cisco_xr_client.current_version == "7.3.2"
    assert info == {
        "units": [
            {
                "id": 0,
                "role": "master",
                "version": "7.3.2",
                "name": "PE1",
                "serial": "FOX2401A1BC",
                "model": "IOS-XRv 9000",
            }
        ]
    }


# ---------- read_info workflow ----------

def test_read_info_returns_result(monkeypatch, cisco_xr_client, fake_conn):
    monkeypatch.setattr(cisco_xr_client, "connect", lambda: None)
    monkeypatch.setattr(cisco_xr_client, "disconnect", lambda: None)
    cisco_xr_client.conn = fake_conn
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_INVENTORY]

    from network_automation.results import OperationResult

    result = read_info(cisco_xr_client, return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "info"
    unit = result.metadata["units"][0]
    assert unit["name"] == "PE1"
    assert unit["version"] == "7.3.2"
    assert unit["model"] == "IOS-XRv 9000"
    assert unit["serial"] == "FOX2401A1BC"


def test_read_info_default_return(monkeypatch, cisco_xr_client, fake_conn):
    monkeypatch.setattr(cisco_xr_client, "connect", lambda: None)
    monkeypatch.setattr(cisco_xr_client, "disconnect", lambda: None)
    cisco_xr_client.conn = fake_conn
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_INVENTORY]

    info = read_info(cisco_xr_client)

    assert "units" in info
    assert info["units"][0]["serial"] == "FOX2401A1BC"
