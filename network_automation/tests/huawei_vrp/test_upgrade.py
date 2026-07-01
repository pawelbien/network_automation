# network_automation/tests/huawei_vrp/test_upgrade.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.upgrade import (
    configure_next_startup,
    configure_next_startup_patch,
    apply_patch,
    upgrade,
)
from network_automation.results import OperationResult


# ---------- Shared device output helpers ----------

_ESN = " ESN of device: 2S5001048324A0014851\n"

TARGET_FILENAME = "AR650A_V300R024C00SPC200.cc"
PATCH_FILENAME = "AR650A_V300R024SPH1b0.pat"


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


def _display_startup_with_patch(
    current_image: str, next_image: str, current_patch: str, next_patch: str
) -> str:
    return f"""\
MainBoard:
  Startup system software:                   flash:/{current_image}
  Next startup system software:              flash:/{next_image}
  Startup patch package:                     flash:/{current_patch}
  Next startup patch package:                flash:/{next_patch}
"""


def _display_patch_information(patch_version: str, package_name: str, state: str = "Running") -> str:
    return f"""\
Patch version         :{patch_version}
Patch package name    :flash:/{package_name}
The state of the patch state file is:{state}
The current state is:{state}
"""


# ---------- Fixtures ----------

@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- configure_next_startup ----------

def test_configure_next_startup_success(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",  # ack for "startup system-software ..."
        _display_startup("old.cc", TARGET_FILENAME),
    ]

    configure_next_startup(huawei_client, TARGET_FILENAME)

    assert fake_conn.send_command.call_count == 2


def test_configure_next_startup_mismatch_raises(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",
        _display_startup("old.cc", "unexpected.cc"),
    ]

    with pytest.raises(RuntimeError):
        configure_next_startup(huawei_client, TARGET_FILENAME)


# ---------- configure_next_startup_patch ----------

def test_configure_next_startup_patch_success(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",  # ack for "startup patch ..."
        _display_startup_with_patch("fw.cc", "fw.cc", "old.pat", PATCH_FILENAME),
    ]

    configure_next_startup_patch(huawei_client, PATCH_FILENAME)

    assert fake_conn.send_command.call_count == 2


def test_configure_next_startup_patch_mismatch_raises(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",
        _display_startup_with_patch("fw.cc", "fw.cc", "old.pat", "unexpected.pat"),
    ]

    with pytest.raises(RuntimeError):
        configure_next_startup_patch(huawei_client, PATCH_FILENAME)


# ---------- apply_patch ----------

def test_apply_patch_success(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",  # ack for "patch load ... all run"
        _display_patch_information("ARV300R024SPH1b0", PATCH_FILENAME),
    ]

    apply_patch(huawei_client, PATCH_FILENAME, "ARV300R024SPH1b0")

    assert fake_conn.send_command.call_count == 2


def test_apply_patch_state_not_running_raises(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",
        _display_patch_information("ARV300R024SPH1b0", PATCH_FILENAME, state="Idle"),
    ]

    with pytest.raises(RuntimeError):
        apply_patch(huawei_client, PATCH_FILENAME, "ARV300R024SPH1b0")


def test_apply_patch_version_mismatch_raises(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",
        _display_patch_information("ARV300R024SPH1a0", PATCH_FILENAME),
    ]

    with pytest.raises(RuntimeError):
        apply_patch(huawei_client, PATCH_FILENAME, "ARV300R024SPH1b0")


# ---------- upgrade workflow ----------

def test_upgrade_skipped_if_not_newer(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"
    huawei_client.firmware_file = "/tmp/AR650A_V300R024C00SPC100.cc"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
    ]

    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    huawei_client.upgrade()

    mock_upload.assert_not_called()


def test_upgrade_success(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current=100)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # configure_next_startup
        "", _display_startup("old.cc", TARGET_FILENAME),
        # get_info() after reboot (final=200)
        _display_version("200"), _ESN,
        _display_startup(TARGET_FILENAME, TARGET_FILENAME),
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    mocker.patch.object(huawei_client, "reboot")
    mocker.patch.object(
        huawei_client,
        "wait_for_reconnect",
        return_value=fake_conn,
    )

    huawei_client.upgrade()

    huawei_client.reboot.assert_called_once()


def test_upgrade_raises_on_multiple_units(mocker, huawei_client):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch.object(huawei_client, "connect")
    mocker.patch.object(huawei_client, "disconnect")

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.get_info",
        return_value={
            "units": [
                {"software_version": "V300R024C00SPC100"},
                {"software_version": "V300R024C00SPC100"},
            ]
        },
    )

    with pytest.raises(RuntimeError):
        upgrade(huawei_client)


def test_upgrade_version_mismatch_raises(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # configure_next_startup
        "", _display_startup("old.cc", TARGET_FILENAME),
        # get_info() after reboot (mismatch: still 100 instead of 200)
        _display_version("100"), _ESN,
        _display_startup(TARGET_FILENAME, TARGET_FILENAME),
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    mocker.patch.object(huawei_client, "reboot")
    mocker.patch.object(
        huawei_client,
        "wait_for_reconnect",
        return_value=fake_conn,
    )

    with pytest.raises(RuntimeError):
        huawei_client.upgrade()


def test_upgrade_returns_result(monkeypatch, huawei_client):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upgrade.get_info",
        lambda client: {
            "units": [{"software_version": client.firmware_version}]
        },
    )
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files",
        lambda client, **kwargs: None,
    )
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upgrade.configure_next_startup",
        lambda client, filename: None,
    )
    monkeypatch.setattr(huawei_client, "reboot", lambda: None)
    monkeypatch.setattr(
        huawei_client,
        "wait_for_reconnect",
        lambda: huawei_client.conn,
    )

    result = huawei_client.upgrade(return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "upgrade"


# ---------- upgrade workflow: patch-only / firmware+patch / none ----------

def test_upgrade_patch_only(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"  # same as current
    huawei_client.firmware_file = "/tmp/unused.cc"
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = f"/tmp/{PATCH_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current firmware == target)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # get_patch_info() before upgrade (current patch older than target)
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
        # apply_patch: ack for "patch load ... all run"
        "",
        # _verify_patch_active: get_patch_info() after apply
        _display_patch_information("ARV300R024SPH1b0", PATCH_FILENAME),
    ]
    fake_conn.send_command_timing.side_effect = [
        "Save the configuration successfully.",
    ]

    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    result = huawei_client.upgrade(return_result=True)

    mock_upload.assert_called_once()
    assert result.metadata["operation_type"] == "PATCH_ONLY"
    assert fake_conn.send_command_timing.call_count == 1


def test_upgrade_firmware_and_patch(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = f"/tmp/{PATCH_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current=100)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # get_patch_info() before upgrade (current patch older than target)
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
        # configure_next_startup
        "", _display_startup("old.cc", TARGET_FILENAME),
        # configure_next_startup_patch
        "", _display_startup_with_patch(TARGET_FILENAME, TARGET_FILENAME, "old.pat", PATCH_FILENAME),
        # get_info() after reboot (final=200)
        _display_version("200"), _ESN,
        _display_startup(TARGET_FILENAME, TARGET_FILENAME),
        # _verify_patch_active after reboot
        _display_patch_information("ARV300R024SPH1b0", PATCH_FILENAME),
    ]
    fake_conn.send_command_timing.side_effect = [
        "Save the configuration successfully.",
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    mocker.patch.object(huawei_client, "reboot")
    mocker.patch.object(
        huawei_client,
        "wait_for_reconnect",
        return_value=fake_conn,
    )

    result = huawei_client.upgrade(return_result=True)

    huawei_client.reboot.assert_called_once()
    assert result.metadata["operation_type"] == "FIRMWARE_AND_PATCH"
    assert fake_conn.send_command_timing.call_count == 1


def test_upgrade_none_skips_when_nothing_newer(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"
    huawei_client.firmware_file = "/tmp/unused.cc"
    huawei_client.patch_version = "ARV300R024SPH1a0"
    huawei_client.patch_file = "/tmp/old.pat"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # current patch == target patch -> nothing newer
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
    ]

    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    result = huawei_client.upgrade(return_result=True)

    mock_upload.assert_not_called()
    assert result.metadata["operation_type"] == "NONE"
    assert result.metadata["skipped"] is True
