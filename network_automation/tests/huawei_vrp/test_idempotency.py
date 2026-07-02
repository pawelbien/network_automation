# network_automation/tests/huawei_vrp/test_idempotency.py

import hashlib
from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.idempotency import (
    already_running_target,
    file_already_on_flash,
    patch_already_active,
)

_ESN = " ESN of device: 2S5001048324A0014851\n"


def _display_version(spc: str) -> str:
    return f"""\
Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (AR650 V300R024C00SPC{spc})
Copyright (C) 2011-2024 HUAWEI TECH CO., LTD
Huawei AR651 Router uptime is 2 weeks, 1 day, 12 hours, 21 minutes

MPU 0(Master) : uptime is 2 weeks, 1 day, 12 hours, 21 minutes
"""


def _display_startup(current_filename: str, next_filename: str) -> str:
    return f"""\
MainBoard:
  Startup system software:                   flash:/{current_filename}
  Next startup system software:              flash:/{next_filename}
  Startup patch package:                     null
  Next startup patch package:                null
"""


def _display_patch_information(patch_version: str, package_name: str, state: str = "Running") -> str:
    return f"""\
Patch version         :{patch_version}
Patch package name    :flash:/{package_name}
The state of the patch state file is:{state}
The current state is:{state}
"""


def _display_file_md5(filename: str, md5_hex: str) -> str:
    return f"Info: The MD5 value of the file flash:/{filename} is: {md5_hex}\n"


# ---------- file_already_on_flash ----------

def test_file_already_on_flash_true_on_matching_md5(tmp_path):
    local_file = tmp_path / "AR650A_V300R024C00SPC200.cc"
    local_file.write_bytes(b"firmware image contents")
    expected_md5 = hashlib.md5(local_file.read_bytes()).hexdigest()

    conn = MagicMock()
    conn.send_command.side_effect = [_display_file_md5(local_file.name, expected_md5)]
    client = MagicMock(conn=conn)

    already_present, md5_result = file_already_on_flash(client, local_file)

    assert already_present is True
    assert md5_result == {"expected_md5": expected_md5, "actual_md5": expected_md5, "match": True}


def test_file_already_on_flash_false_on_mismatched_md5(tmp_path):
    local_file = tmp_path / "AR650A_V300R024C00SPC200.cc"
    local_file.write_bytes(b"firmware image contents")

    conn = MagicMock()
    conn.send_command.side_effect = [_display_file_md5(local_file.name, "0" * 32)]
    client = MagicMock(conn=conn)

    already_present, md5_result = file_already_on_flash(client, local_file)

    assert already_present is False
    assert md5_result["match"] is False


def test_file_already_on_flash_false_when_missing(tmp_path):
    local_file = tmp_path / "AR650A_V300R024C00SPC200.cc"
    local_file.write_bytes(b"firmware image contents")

    conn = MagicMock()
    conn.send_command.side_effect = ["Error: file does not exist"]
    client = MagicMock(conn=conn)

    already_present, md5_result = file_already_on_flash(client, local_file)

    assert already_present is False
    assert md5_result["actual_md5"] is None


# ---------- patch_already_active ----------

def test_patch_already_active_true_when_running_and_matching():
    conn = MagicMock()
    conn.send_command.side_effect = [
        _display_patch_information("ARV300R024SPH1b0", "AR650A_V300R024SPH1b0.pat")
    ]
    client = MagicMock(conn=conn)

    assert patch_already_active(client, "ARV300R024SPH1b0") is True


def test_patch_already_active_false_when_version_mismatches():
    conn = MagicMock()
    conn.send_command.side_effect = [
        _display_patch_information("ARV300R024SPH1a0", "AR650A_V300R024SPH1a0.pat")
    ]
    client = MagicMock(conn=conn)

    assert patch_already_active(client, "ARV300R024SPH1b0") is False


def test_patch_already_active_false_when_not_running():
    conn = MagicMock()
    conn.send_command.side_effect = [
        _display_patch_information("ARV300R024SPH1b0", "AR650A_V300R024SPH1b0.pat", state="Idle")
    ]
    client = MagicMock(conn=conn)

    assert patch_already_active(client, "ARV300R024SPH1b0") is False


def test_patch_already_active_false_when_no_patch():
    conn = MagicMock()
    conn.send_command.side_effect = ["No patch exists.\n"]
    client = MagicMock(conn=conn)

    assert patch_already_active(client, "ARV300R024SPH1b0") is False


# ---------- already_running_target ----------

def test_already_running_target_true_firmware_only():
    conn = MagicMock()
    conn.send_command.side_effect = [
        _display_version("200"), _ESN, _display_startup("x.cc", "x.cc"),
    ]
    client = MagicMock(conn=conn)

    assert already_running_target(client, "V300R024C00SPC200", None) is True


def test_already_running_target_false_when_firmware_differs():
    conn = MagicMock()
    conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("x.cc", "x.cc"),
    ]
    client = MagicMock(conn=conn)

    assert already_running_target(client, "V300R024C00SPC200", None) is False


def test_already_running_target_true_firmware_and_patch():
    conn = MagicMock()
    conn.send_command.side_effect = [
        _display_version("200"), _ESN, _display_startup("x.cc", "x.cc"),
        _display_patch_information("ARV300R024SPH1b0", "AR650A_V300R024SPH1b0.pat"),
    ]
    client = MagicMock(conn=conn)

    result = already_running_target(client, "V300R024C00SPC200", "ARV300R024SPH1b0")

    assert result is True


def test_already_running_target_false_when_patch_not_yet_active():
    conn = MagicMock()
    conn.send_command.side_effect = [
        _display_version("200"), _ESN, _display_startup("x.cc", "x.cc"),
        _display_patch_information("ARV300R024SPH1a0", "AR650A_V300R024SPH1a0.pat"),
    ]
    client = MagicMock(conn=conn)

    result = already_running_target(client, "V300R024C00SPC200", "ARV300R024SPH1b0")

    assert result is False
