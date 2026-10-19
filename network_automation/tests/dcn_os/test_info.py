# network_automation/tests/dcn_os/test_info.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.dcn_os.info import (
    _parse_show_version,
    _parse_show_vendor,
    extract_discovery_facts,
    get_info,
    read_info,
)


_SHOW_VERSION = """\
  S5750E-28X-SI Device, Compiled on Jan 01 00:00:00 2024
  sysLocation China
  CPU Mac 00:00:5e:00:53:01
  Vlan MAC 00:00:5e:00:53:00
  SoftWare Package Version V700R001C001B001
  BootRom Version 1.0.1
  HardWare Version 1.0.0
  CPLD Version 1.00
  Serial No.:SW0000000000000001
  Copyright (C) 2001-2024 by DC YunKe Networks Co.,Ltd.
  All rights reserved
  Last reboot is cold reset.
  Uptime is 1 weeks, 2 days, 3 hours, 4 minutes
"""

# V706R firmware: "Serial No" without ".:", value separated by spaces.
_SHOW_VERSION_V706 = """\
  S5750E-26X-SI Device, Compiled on Jan 01 00:00:00 2024
  sysLocation Example Location
  CPU MAC          00-00-5e-00-53-03
  VLAN MAC         00-00-5e-00-53-02
  SoftWare Package Version V706R001C001B001
  BootRom Version  1.0.1
  HardWare Version 1.0.0
  CPLD Version     1.00
  Serial No        SW0000000000000002
  Copyright (C) 2001-2024 by DC YunKe Networks Co.,Ltd.
  All rights reserved
  Last reboot was cold reset.
  Uptime is 1 weeks, 2 days, 3 hours, 4 minutes
"""

_SHOW_VENDOR = """\
NAME            LEN          VALUE
------------    -----        ------------------------------
SwitchName      13           S5750E-28X-SI
VersionPre      0
VendNameEn      26           DC YunKe Networks Co.,Ltd.
VendNameBr      3            DCN
VendorOid       16           1.3.6.1.4.1.6339
DeviceOid       26           1.3.6.1.4.1.6339.1.1.1.640
KeyNeed         4            0
CliStyle        3            0
HsrpNeed        4            0
DevType(ID)     4            360
ChassisCard     0
FileVersion     5            1.0.1
IMGPrefix       0
NeedLicense     6            YES
"""


@pytest.fixture
def fake_conn():
    conn = MagicMock()
    conn.base_prompt = "sw1"
    return conn


# ---------- _parse_show_version ----------

def test_parse_show_version():
    assert _parse_show_version(_SHOW_VERSION) == {
        "model": "S5750E-28X-SI",
        "version": "V700R001C001B001",
        "serial": "SW0000000000000001",
    }


def test_parse_show_version_v706_serial_without_colon():
    assert _parse_show_version(_SHOW_VERSION_V706) == {
        "model": "S5750E-26X-SI",
        "version": "V706R001C001B001",
        "serial": "SW0000000000000002",
    }


def test_parse_show_version_empty_serial_does_not_take_next_line():
    with pytest.raises(ValueError, match="Serial number not found"):
        _parse_show_version(
            "  S5750E-28X-SI Device, Compiled on Jan 01 2024\n"
            "  SoftWare Package Version V700R001C001B001\n"
            "  Serial No.:\n"
            "  Copyright (C) 2001-2024\n"
        )


def test_parse_show_version_missing_model():
    with pytest.raises(ValueError, match="Model not found"):
        _parse_show_version("  SoftWare Package Version V700R001C001B001\n  Serial No.:SW1\n")


def test_parse_show_version_missing_version():
    with pytest.raises(ValueError, match="Version not found"):
        _parse_show_version("  S5750E-28X-SI Device, Compiled on Jan 01 2024\n  Serial No.:SW1\n")


def test_parse_show_version_missing_serial():
    with pytest.raises(ValueError, match="Serial number not found"):
        _parse_show_version(
            "  S5750E-28X-SI Device, Compiled on Jan 01 2024\n"
            "  SoftWare Package Version V700R001C001B001\n"
        )


# ---------- _parse_show_vendor ----------

def test_parse_show_vendor():
    assert _parse_show_vendor(_SHOW_VENDOR) == "360"


def test_parse_show_vendor_missing_devtype_id():
    with pytest.raises(ValueError, match="DevType"):
        _parse_show_vendor("NAME   LEN   VALUE\nSwitchName  13  S5750E-28X-SI\n")


# ---------- get_info ----------

def test_get_info(dcn_os_client, fake_conn):
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_VENDOR]
    dcn_os_client.conn = fake_conn

    info = get_info(dcn_os_client)

    assert info == {"units": [{
        "id": 0,
        "role": "master",
        "version": "V700R001C001B001",
        "name": "sw1",
        "serial": "SW0000000000000001",
        "model": "S5750E-28X-SI",
        "devtype_id": "360",
    }]}
    assert dcn_os_client.current_version == "V700R001C001B001"
    assert [c.args[0] for c in fake_conn.send_command.call_args_list] == ["show version", "show vendor"]


# ---------- extract_discovery_facts ----------

def test_extract_discovery_facts():
    units = [{
        "id": 0, "role": "master", "version": "V700R001C001B001", "name": "sw1",
        "serial": "SW0000000000000001", "model": "S5750E-28X-SI", "devtype_id": "360",
    }]

    assert extract_discovery_facts(units) == {
        "serial": "SW0000000000000001",
        "software_version": "V700R001C001B001",
        "model": "S5750E-28X-SI",
        "devtype_id": "360",
    }


# ---------- read_info ----------

def test_read_info_connects_and_disconnects(monkeypatch, dcn_os_client, fake_conn):
    fake_conn.send_command.side_effect = [_SHOW_VERSION, _SHOW_VENDOR]

    def fake_connect():
        dcn_os_client.conn = fake_conn

    monkeypatch.setattr(dcn_os_client, "connect", fake_connect)

    result = read_info(dcn_os_client, return_result=True)

    assert result.success
    assert result.metadata["units"][0]["devtype_id"] == "360"
    fake_conn.disconnect.assert_called_once()
    assert dcn_os_client.conn is None


def test_read_info_failure_marks_result_and_disconnects(monkeypatch, dcn_os_client, fake_conn):
    fake_conn.send_command.side_effect = ["garbage", _SHOW_VENDOR]

    def fake_connect():
        dcn_os_client.conn = fake_conn

    monkeypatch.setattr(dcn_os_client, "connect", fake_connect)

    with pytest.raises(ValueError):
        read_info(dcn_os_client)

    fake_conn.disconnect.assert_called_once()
    assert dcn_os_client.conn is None
