# network_automation/tests/huawei_vrp/test_info.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.info import (
    _parse_version,
    _parse_esn,
    _parse_startup,
    _parse_patch_information,
    _parse_file_md5,
    get_info,
    get_patch_info,
    get_file_md5,
    read_info,
)
from network_automation.results import OperationResult


# ---------------------------------------------------------------------------
# Sample command outputs (verbatim from real devices)
# ---------------------------------------------------------------------------

DISPLAY_VERSION_ROUTER = """\
Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (AR650 V300R024C00SPC100)
Copyright (C) 2011-2024 HUAWEI TECH CO., LTD
Huawei AR651 Router uptime is 2 weeks, 1 day, 12 hours, 21 minutes

MPU 0(Master) : uptime is 2 weeks, 1 day, 12 hours, 21 minutes
SDRAM Memory Size    : 2048    M bytes
Flash 0 Memory Size  : 1024    M bytes
Flash 1 Memory Size  : 32      M bytes
MPU version information :
1. PCB      Version  : AR-SRU651 VER.C
2. MAB      Version  : 3
3. Board    Type     : AR651
4. CPLD0    Version  : 108
5. BootROM  Version  : 1
6. Mcu      Version  : -
"""

DISPLAY_VERSION_STACK = """\
Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (S6730 V200R024C00SPC500)
Copyright (C) 2000-2024 HUAWEI TECH Co., Ltd.
HUAWEI S6730-H24X6C Routing Switch uptime is 26 weeks, 1 day, 12 hours, 35 minutes

ES6D2S30S003 1(Master)  : uptime is 26 weeks, 1 day, 12 hours, 32 minutes
DDR             Memory Size : 4096  M bytes
FLASH Total     Memory Size : 2048  M bytes
FLASH Available Memory Size : 1654  M bytes
Pcb           Version   : VER.A
MAB           Version   : 8
BootROM       Version   : 0000.052c
BootLoad      Version   : 0218.0000
CPLD          Version   : 0108
Software      Version   : VRP (R) Software, Version 5.170 (V200R024C00SPC500)
FLASH         Version   : 0000.0000
PWR1 information
Pcb           Version   : PWR VER.A
PMBus         Version   : 18
PWR2 information
Pcb           Version   : PWR VER.A
PMBus         Version   : 18
FAN1 information
Pcb           Version   : NA
FAN2 information
Pcb           Version   : NA
FAN3 information
Pcb           Version   : NA
FAN4 information
Pcb           Version   : NA

ES6D2S30S003 2(Standby)  : uptime is 26 weeks, 1 day, 12 hours, 30 minutes
DDR             Memory Size : 4096  M bytes
FLASH Total     Memory Size : 2048  M bytes
FLASH Available Memory Size : 1654  M bytes
Pcb           Version   : VER.A
MAB           Version   : 8
BootROM       Version   : 0000.052c
BootLoad      Version   : 0218.0000
CPLD          Version   : 0108
Software      Version   : VRP (R) Software, Version 5.170 (V200R024C00SPC500)
FLASH         Version   : 0000.0000
PWR1 information
Pcb           Version   : PWR VER.A
PMBus         Version   : 18
PWR2 information
Pcb           Version   : PWR VER.A
PMBus         Version   : 18
FAN1 information
Pcb           Version   : NA
FAN2 information
Pcb           Version   : NA
FAN3 information
Pcb           Version   : NA
FAN4 information
Pcb           Version   : NA
"""

DISPLAY_ESN_ROUTER = " ESN of device: 2S5001048324A0014851\n"

DISPLAY_ESN_STACK = """\
ESN of slot 1: 6R23C0039583
ESN of slot 2: 6R23C0039593
"""

DISPLAY_STARTUP_ROUTER = """\
MainBoard:
  Startup system software:                   flash:/AR650A_V300R024C00SPC100.cc
  Next startup system software:              flash:/AR650A_V300R024C00SPC100.cc
  Backup system software for next startup:   flash:/AR650A_V300R023C00SPC100.cc
  Startup saved-configuration file:          flash:/vrpcfg.zip
  Next startup saved-configuration file:     flash:/vrpcfg.zip
  Startup license file:                      flash:/LIC20250225BVAM80_2S24A0014851.dat
  Next startup license file:                 flash:/LIC20250225BVAM80_2S24A0014851.dat
  Startup patch package:                     flash:/AR650A_V300R024SPH121.pat
  Next startup patch package:                flash:/AR650A_V300R024SPH121.pat
  Startup voice-files:                       null
  Next startup voice-files:                  null
"""

DISPLAY_STARTUP_STACK = """\
MainBoard:
  Configured startup system software:        flash:/s6730_v200r024c00spc500.cc
  Startup system software:                   flash:/s6730_v200r024c00spc500.cc
  Next startup system software:              flash:/s6730_v200r024c00spc500.cc
  Startup saved-configuration file:          flash:/vrpcfg.zip
  Next startup saved-configuration file:     flash:/vrpcfg.zip
  Startup paf file:                          default
  Next startup paf file:                     default
  Startup license file:                      default
  Next startup license file:                 default
  Startup patch package:                     flash:/s6730-h_v200r024sph121.pat
  Next startup patch package:                flash:/s6730-h_v200r024sph121.pat
SlaveBoard:
  Configured startup system software:        flash:/s6730_v200r024c00spc500.cc
  Startup system software:                   flash:/s6730_v200r024c00spc500.cc
  Next startup system software:              flash:/s6730_v200r024c00spc500.cc
  Startup saved-configuration file:          flash:/vrpcfg.zip
  Next startup saved-configuration file:     flash:/vrpcfg.zip
  Startup paf file:                          default
  Next startup paf file:                     default
  Startup license file:                      default
  Next startup license file:                 default
  Startup patch package:                     flash:/s6730-h_v200r024sph121.pat
  Next startup patch package:                flash:/s6730-h_v200r024sph121.pat
"""

DISPLAY_PATCH_INFORMATION_ROUTER = """\
Patch version         :ARV300R023SPH1b0
Patch package name    :flash:/AR650A_V300R023SPH1b0.pat
The state of the patch state file is:Running
The current state is:Running
******************************************************************
*              The patch information,as follows                  *
******************************************************************
Type        State         Count          Time(YYYY-MM-DD HH:MM:SS)
------------------------------------------------------------------
vrp         Running       256            2026-07-01 09:15:05+01:00
exe         Running       2              2026-07-01 09:15:06+01:00
soft        Running       26             2026-07-01 09:15:08+01:00
driver      Running       1              2026-07-01 09:15:14+01:00
cap         Running       31             2026-07-01 09:15:31+01:00
"""

DISPLAY_PATCH_INFORMATION_NONE = """\
No patch exists.
"""

DISPLAY_FILE_MD5 = """\
Verifying the file, please wait...
Info: The MD5 value of the file flash:/AR650A_V300R024C00SPC200.cc is: 5F8AD13D1C9C7C50CBCBC7C0E5E7F8AB
"""


# ---------------------------------------------------------------------------
# _parse_version
# ---------------------------------------------------------------------------

def test_parse_version_router():
    units = _parse_version(DISPLAY_VERSION_ROUTER)

    assert len(units) == 1
    m = units[0]
    assert m["id"] == 0
    assert m["role"] == "master"
    assert m["model"] == "AR651"
    assert m["vrp_version"] == "5.170"
    assert m["software_version"] == "V300R024C00SPC100"


def test_parse_version_stack():
    units = _parse_version(DISPLAY_VERSION_STACK)

    assert len(units) == 2

    master, standby = units
    assert master["id"] == 1
    assert master["role"] == "master"
    assert master["model"] == "S6730-H24X6C"
    assert master["vrp_version"] == "5.170"
    assert master["software_version"] == "V200R024C00SPC500"

    assert standby["id"] == 2
    assert standby["role"] == "standby"
    assert standby["model"] == "S6730-H24X6C"
    assert standby["vrp_version"] == "5.170"
    assert standby["software_version"] == "V200R024C00SPC500"


# ---------------------------------------------------------------------------
# _parse_esn
# ---------------------------------------------------------------------------

def test_parse_esn_single_device():
    esn_map = _parse_esn(DISPLAY_ESN_ROUTER)

    assert esn_map == {"device": "2S5001048324A0014851"}


def test_parse_esn_stack():
    esn_map = _parse_esn(DISPLAY_ESN_STACK)

    assert esn_map == {1: "6R23C0039583", 2: "6R23C0039593"}


# ---------------------------------------------------------------------------
# _parse_startup
# ---------------------------------------------------------------------------

def test_parse_startup_router():
    startup_map = _parse_startup(DISPLAY_STARTUP_ROUTER)

    assert set(startup_map.keys()) == {"master"}
    s = startup_map["master"]
    assert s["startup_image"] == "flash:/AR650A_V300R024C00SPC100.cc"
    assert s["next_startup_image"] == "flash:/AR650A_V300R024C00SPC100.cc"
    assert s["startup_patch"] == "flash:/AR650A_V300R024SPH121.pat"
    assert s["next_startup_patch"] == "flash:/AR650A_V300R024SPH121.pat"


def test_parse_startup_stack():
    startup_map = _parse_startup(DISPLAY_STARTUP_STACK)

    assert set(startup_map.keys()) == {"master", "standby"}

    for role in ("master", "standby"):
        s = startup_map[role]
        assert s["startup_image"] == "flash:/s6730_v200r024c00spc500.cc"
        assert s["next_startup_image"] == "flash:/s6730_v200r024c00spc500.cc"
        assert s["startup_patch"] == "flash:/s6730-h_v200r024sph121.pat"
        assert s["next_startup_patch"] == "flash:/s6730-h_v200r024sph121.pat"


def test_parse_startup_null_patch_becomes_none():
    output = """\
MainBoard:
  Startup system software:                   flash:/image.cc
  Next startup system software:              flash:/image.cc
  Startup patch package:                     null
  Next startup patch package:                null
"""
    s = _parse_startup(output)["master"]
    assert s["startup_patch"] is None
    assert s["next_startup_patch"] is None


# ---------------------------------------------------------------------------
# _parse_patch_information
# ---------------------------------------------------------------------------

def test_parse_patch_information_present():
    info = _parse_patch_information(DISPLAY_PATCH_INFORMATION_ROUTER)

    assert info["patch_version"] == "ARV300R023SPH1b0"
    assert info["patch_package_name"] == "flash:/AR650A_V300R023SPH1b0.pat"
    assert info["state"] == "Running"


def test_parse_patch_information_absent():
    info = _parse_patch_information(DISPLAY_PATCH_INFORMATION_NONE)

    assert info["patch_version"] is None
    assert info["patch_package_name"] is None
    assert info["state"] is None


# ---------------------------------------------------------------------------
# _parse_file_md5
# ---------------------------------------------------------------------------

def test_parse_file_md5_extracts_lowercased_hash():
    md5 = _parse_file_md5(DISPLAY_FILE_MD5)

    assert md5 == "5f8ad13d1c9c7c50cbcbc7c0e5e7f8ab"


def test_parse_file_md5_raises_when_no_hash_present():
    with pytest.raises(ValueError):
        _parse_file_md5("Error: file does not exist\n")


# ---------------------------------------------------------------------------
# get_file_md5 (uses fake conn, no connection lifecycle)
# ---------------------------------------------------------------------------

def test_get_file_md5(huawei_client):
    conn = MagicMock()
    conn.send_command.side_effect = [DISPLAY_FILE_MD5]
    huawei_client.conn = conn

    md5 = get_file_md5(huawei_client, "AR650A_V300R024C00SPC200.cc")

    assert md5 == "5f8ad13d1c9c7c50cbcbc7c0e5e7f8ab"
    conn.send_command.assert_called_once_with(
        "display system file-md5 flash:/AR650A_V300R024C00SPC200.cc"
    )


# ---------------------------------------------------------------------------
# get_patch_info (uses fake conn, no connection lifecycle)
# ---------------------------------------------------------------------------

def test_get_patch_info(huawei_client):
    conn = MagicMock()
    conn.send_command.side_effect = [DISPLAY_PATCH_INFORMATION_ROUTER]
    huawei_client.conn = conn

    info = get_patch_info(huawei_client)

    assert info["patch_version"] == "ARV300R023SPH1b0"
    assert info["state"] == "Running"
    conn.send_command.assert_called_once_with("display patch-information")


# ---------------------------------------------------------------------------
# get_info (uses fake conn, no connection lifecycle)
# ---------------------------------------------------------------------------

def _fake_conn(version_out, esn_out, startup_out):
    conn = MagicMock()
    conn.send_command.side_effect = [version_out, esn_out, startup_out]
    return conn


def test_get_info_router(huawei_client):
    huawei_client.conn = _fake_conn(
        DISPLAY_VERSION_ROUTER, DISPLAY_ESN_ROUTER, DISPLAY_STARTUP_ROUTER
    )

    info = get_info(huawei_client)
    units = info["units"]

    assert len(units) == 1
    m = units[0]
    assert m["id"] == 0
    assert m["role"] == "master"
    assert m["model"] == "AR651"
    assert m["esn"] == "2S5001048324A0014851"
    assert m["vrp_version"] == "5.170"
    assert m["software_version"] == "V300R024C00SPC100"
    assert m["startup_image"] == "flash:/AR650A_V300R024C00SPC100.cc"
    assert m["next_startup_image"] == "flash:/AR650A_V300R024C00SPC100.cc"
    assert m["startup_patch"] == "flash:/AR650A_V300R024SPH121.pat"
    assert m["next_startup_patch"] == "flash:/AR650A_V300R024SPH121.pat"


def test_get_info_stack(huawei_client):
    huawei_client.conn = _fake_conn(
        DISPLAY_VERSION_STACK, DISPLAY_ESN_STACK, DISPLAY_STARTUP_STACK
    )

    info = get_info(huawei_client)
    units = info["units"]

    assert len(units) == 2

    master, standby = units
    assert master["id"] == 1
    assert master["role"] == "master"
    assert master["model"] == "S6730-H24X6C"
    assert master["esn"] == "6R23C0039583"
    assert master["startup_image"] == "flash:/s6730_v200r024c00spc500.cc"
    assert master["startup_patch"] == "flash:/s6730-h_v200r024sph121.pat"

    assert standby["id"] == 2
    assert standby["role"] == "standby"
    assert standby["esn"] == "6R23C0039593"
    assert standby["startup_image"] == "flash:/s6730_v200r024c00spc500.cc"
    assert standby["startup_patch"] == "flash:/s6730-h_v200r024sph121.pat"


# ---------------------------------------------------------------------------
# read_info (full workflow with connect/disconnect mocked)
# ---------------------------------------------------------------------------

def test_read_info_returns_dict(monkeypatch, huawei_client):
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)
    huawei_client.conn = _fake_conn(
        DISPLAY_VERSION_ROUTER, DISPLAY_ESN_ROUTER, DISPLAY_STARTUP_ROUTER
    )

    result = read_info(huawei_client, return_result=False)

    assert isinstance(result, dict)
    assert "units" in result
    assert result["units"][0]["model"] == "AR651"


def test_read_info_returns_operation_result(monkeypatch, huawei_client):
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)
    huawei_client.conn = _fake_conn(
        DISPLAY_VERSION_ROUTER, DISPLAY_ESN_ROUTER, DISPLAY_STARTUP_ROUTER
    )

    result = read_info(huawei_client, return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "info"
    assert "units" in result.metadata
    assert result.metadata["units"][0]["model"] == "AR651"
