# network_automation/tests/huawei_vrp/test_upgrade.py

import hashlib

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.cli_errors import CLIError
from network_automation.platforms.huawei_vrp.lock import DeviceBusyError, _lock_path
from network_automation.platforms.huawei_vrp.version import DowngradeRejectedError
from network_automation.platforms.huawei_vrp.upgrade import (
    configure_next_startup,
    configure_next_startup_patch,
    apply_patch,
    verify_md5,
    save_configuration,
    upgrade,
)
from network_automation.results import OperationResult

# MD5 verification is mocked out (via verify_md5) in tests that aren't
# specifically about MD5, since firmware_file/patch_file there are fake
# paths that don't exist on disk — see the dedicated MD5 match/mismatch
# tests near the bottom of this file for real compute_local_md5 coverage.
_FAKE_MD5_RESULT = {"expected_md5": "d" * 32, "actual_md5": "d" * 32, "match": True}
_NOT_ON_FLASH = (False, {"expected_md5": None, "actual_md5": None, "match": False})


@pytest.fixture(autouse=True)
def _no_idempotency_skips(mocker):
    """
    Default all idempotency pre-checks (Faza 7 — idempotency.py) to "not
    already done", so existing tests exercise the full upload/apply/reboot
    flow unchanged. Tests that specifically exercise skip behavior override
    these within the test body (mocker.patch again, or drive the real
    idempotency.py functions directly — see test_idempotency.py).
    """
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.file_already_on_flash",
        return_value=_NOT_ON_FLASH,
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.patch_already_active",
        return_value=False,
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.already_running_target",
        return_value=False,
    )


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


def _display_file_md5(filename: str, md5_hex: str) -> str:
    return (
        f"Info: The MD5 value of the file flash:/{filename} is: {md5_hex}\n"
    )


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


def test_configure_next_startup_raises_cli_error_on_ack_error(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = ["% Wrong parameter"]

    with pytest.raises(CLIError):
        configure_next_startup(huawei_client, TARGET_FILENAME)


def test_configure_next_startup_raises_cli_error_on_display_startup_error(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = ["", "Error: internal failure"]

    with pytest.raises(CLIError):
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


def test_apply_patch_raises_cli_error_on_ack_error(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = ["% Unrecognized command"]

    with pytest.raises(CLIError):
        apply_patch(huawei_client, PATCH_FILENAME, "ARV300R024SPH1b0")


def test_save_configuration_does_not_raise_on_normal_yn_prompt(huawei_client, fake_conn):
    # Proves save_configuration() does NOT falsely trigger the CLI-error
    # check on ordinary [Y/N] prompt text (no check is applied at all here).
    huawei_client.conn = fake_conn
    fake_conn.send_command_timing.side_effect = [
        "Warning: dangerous, continue? [Y/N]:",
        "Save the configuration successfully.",
    ]

    save_configuration(huawei_client)  # must not raise

    assert fake_conn.send_command_timing.call_count == 2


# ---------- verify_md5 ----------

def test_verify_md5_success(huawei_client, fake_conn, tmp_path):
    local_file = tmp_path / TARGET_FILENAME
    local_file.write_bytes(b"firmware image contents")
    expected_md5 = hashlib.md5(local_file.read_bytes()).hexdigest()

    huawei_client.conn = fake_conn
    fake_conn.send_command.side_effect = [
        _display_file_md5(TARGET_FILENAME, expected_md5),
    ]

    result = verify_md5(huawei_client, local_file)

    assert result == {
        "expected_md5": expected_md5,
        "actual_md5": expected_md5,
        "match": True,
    }
    fake_conn.send_command.assert_called_once_with(
        f"display system file-md5 flash:/{TARGET_FILENAME}"
    )


def test_verify_md5_mismatch_raises(huawei_client, fake_conn, tmp_path):
    local_file = tmp_path / TARGET_FILENAME
    local_file.write_bytes(b"firmware image contents")

    huawei_client.conn = fake_conn
    fake_conn.send_command.side_effect = [
        _display_file_md5(TARGET_FILENAME, "0" * 32),
    ]

    with pytest.raises(RuntimeError, match="MD5 verification failed"):
        verify_md5(huawei_client, local_file)


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
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
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
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
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
    assert result.metadata["lock_acquired"] is True


# ---------- concurrency lock ----------

def test_upgrade_raises_device_busy_and_never_connects(mocker, huawei_client, tmp_path):
    import json
    import os
    import time

    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"
    huawei_client.lock_dir = str(tmp_path)

    path = _lock_path(huawei_client)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"pid": os.getpid(), "acquired_at": time.time()}, f)

    mock_connect = mocker.patch.object(huawei_client, "connect")

    with pytest.raises(DeviceBusyError):
        huawei_client.upgrade()

    mock_connect.assert_not_called()


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
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
    )

    result = huawei_client.upgrade(return_result=True)

    mock_upload.assert_called_once()
    assert result.metadata["operation_type"] == "PATCH_ONLY"
    assert result.metadata["md5_verified"] is True
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
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
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
    assert result.metadata["md5_verified"] is True
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


# ---------- upgrade workflow: input validation / forced downgrade ----------

def test_upgrade_downgrade_rejected_by_default(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"  # older than current
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("200"), _ESN, _display_startup("old.cc", "old.cc"),
    ]

    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    with pytest.raises(DowngradeRejectedError):
        huawei_client.upgrade()

    mock_upload.assert_not_called()


def test_upgrade_force_downgrade_without_confirmation_raises(mocker, huawei_client):
    huawei_client.firmware_version = "V300R024C00SPC100"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"
    huawei_client.force_downgrade = True
    # i_understand_downgrade_risk left at its default (False)

    mock_connect = mocker.patch.object(huawei_client, "connect")

    with pytest.raises(ValueError, match="i_understand_downgrade_risk"):
        huawei_client.upgrade()

    mock_connect.assert_not_called()


def test_upgrade_force_downgrade_with_confirmation_succeeds(mocker, huawei_client, fake_conn):
    downgrade_filename = "AR650A_V300R024C00SPC100.cc"
    huawei_client.firmware_version = "V300R024C00SPC100"  # older than current (200)
    huawei_client.firmware_file = f"/tmp/{downgrade_filename}"
    huawei_client.force_downgrade = True
    huawei_client.i_understand_downgrade_risk = True

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current=200)
        _display_version("200"), _ESN, _display_startup("old.cc", "old.cc"),
        # configure_next_startup
        "", _display_startup("old.cc", downgrade_filename),
        # get_info() after reboot (final=100, the downgraded version)
        _display_version("100"), _ESN,
        _display_startup(downgrade_filename, downgrade_filename),
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
    )
    mocker.patch.object(huawei_client, "reboot")
    mocker.patch.object(
        huawei_client, "wait_for_reconnect", return_value=fake_conn,
    )

    result = huawei_client.upgrade(return_result=True)

    assert result.success is True
    assert result.metadata["downgrade_forced"] is True


def test_upgrade_rejects_invalid_firmware_filename_before_upload(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = "/tmp/firmware.bin"

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

    with pytest.raises(ValueError, match="firmware filename"):
        huawei_client.upgrade()

    mock_upload.assert_not_called()


def test_upgrade_rejects_hardware_family_mismatch_before_upload(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = "/tmp/S6730_V300R024C00SPC200.cc"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # display version reports model "AR651" (router), filename is S6730 (switch)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
    ]

    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    with pytest.raises(ValueError, match="hardware"):
        huawei_client.upgrade()

    mock_upload.assert_not_called()


def test_upgrade_rejects_patch_release_mismatch_before_upload(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"  # same as current
    huawei_client.firmware_file = "/tmp/unused.cc"
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = "/tmp/AR650A_V300R023SPH1b0.pat"  # wrong release train

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
    ]

    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    with pytest.raises(ValueError, match="release train"):
        huawei_client.upgrade()

    mock_upload.assert_not_called()


# ---------- upgrade workflow: idempotency ----------

def test_upgrade_skips_upload_when_already_on_flash(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"  # same as current -> PATCH_ONLY
    huawei_client.firmware_file = "/tmp/unused.cc"
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = f"/tmp/{PATCH_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
    ]
    fake_conn.send_command_timing.side_effect = ["Save the configuration successfully."]

    md5_result = {"expected_md5": "a" * 32, "actual_md5": "a" * 32, "match": True}
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.file_already_on_flash",
        return_value=(True, md5_result),
    )
    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.apply_patch"
    )

    result = huawei_client.upgrade(return_result=True)

    mock_upload.assert_not_called()
    assert result.metadata["skipped_steps"][f"upload_{PATCH_FILENAME}"]
    assert result.metadata["md5_results"] == {PATCH_FILENAME: md5_result}


def test_upgrade_skips_apply_patch_when_already_active(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"
    huawei_client.firmware_file = "/tmp/unused.cc"
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = f"/tmp/{PATCH_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
    ]
    fake_conn.send_command_timing.side_effect = ["Save the configuration successfully."]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.patch_already_active",
        return_value=True,
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
    )
    mock_apply = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.apply_patch"
    )

    result = huawei_client.upgrade(return_result=True)

    mock_apply.assert_not_called()
    assert result.metadata["skipped_steps"]["apply_patch"]


def test_upgrade_skips_configure_next_startup_when_already_set(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info(): next_startup_image already points to target
        _display_version("100"), _ESN, _display_startup("old.cc", TARGET_FILENAME),
        # get_info() after reboot
        _display_version("200"), _ESN, _display_startup(TARGET_FILENAME, TARGET_FILENAME),
    ]

    mocker.patch("network_automation.platforms.huawei_vrp.upgrade.upload_files")
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
    )
    mock_configure = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.configure_next_startup"
    )
    mocker.patch.object(huawei_client, "reboot")
    mocker.patch.object(huawei_client, "wait_for_reconnect", return_value=fake_conn)

    result = huawei_client.upgrade(return_result=True)

    mock_configure.assert_not_called()
    assert result.metadata["skipped_steps"]["configure_next_startup"]


def test_upgrade_skips_reboot_when_already_running_target(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() at start (still old -> FIRMWARE_ONLY is decided)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # configure_next_startup: ack + verify read
        "", _display_startup("old.cc", TARGET_FILENAME),
        # info_after, fetched once reboot is skipped: already shows target
        _display_version("200"), _ESN, _display_startup(TARGET_FILENAME, TARGET_FILENAME),
    ]

    mocker.patch("network_automation.platforms.huawei_vrp.upgrade.upload_files")
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.verify_md5",
        return_value=_FAKE_MD5_RESULT,
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.already_running_target",
        return_value=True,
    )
    mock_reboot = mocker.patch.object(huawei_client, "reboot")

    result = huawei_client.upgrade(return_result=True)

    mock_reboot.assert_not_called()
    assert result.metadata["skipped_steps"]["reboot"]
    assert result.metadata["new_firmware"] == "V300R024C00SPC200"


# ---------- upgrade workflow: MD5 verification (match / mismatch per branch) ----------
#
# These use real local files (tmp_path) and a real compute_local_md5 pass, so
# the device-reported MD5 is faked to either match or intentionally
# mismatch the real hash of the uploaded content.

def test_upgrade_patch_only_md5_match(mocker, huawei_client, fake_conn, tmp_path):
    patch_file = tmp_path / PATCH_FILENAME
    patch_file.write_bytes(b"patch package contents")
    patch_md5 = hashlib.md5(patch_file.read_bytes()).hexdigest()

    huawei_client.firmware_version = "V300R024C00SPC100"  # same as current
    huawei_client.firmware_file = "/tmp/unused.cc"
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = str(patch_file)

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
        _display_file_md5(PATCH_FILENAME, patch_md5),
        "",  # ack for "patch load ... all run"
        _display_patch_information("ARV300R024SPH1b0", PATCH_FILENAME),
    ]
    fake_conn.send_command_timing.side_effect = [
        "Save the configuration successfully.",
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    result = huawei_client.upgrade(return_result=True)

    assert result.metadata["md5_verified"] is True
    assert result.metadata["md5_results"] == {
        PATCH_FILENAME: {
            "expected_md5": patch_md5,
            "actual_md5": patch_md5,
            "match": True,
        }
    }


def test_upgrade_patch_only_md5_mismatch_raises(mocker, huawei_client, fake_conn, tmp_path):
    patch_file = tmp_path / PATCH_FILENAME
    patch_file.write_bytes(b"patch package contents")

    huawei_client.firmware_version = "V300R024C00SPC100"  # same as current
    huawei_client.firmware_file = "/tmp/unused.cc"
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = str(patch_file)

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
        _display_file_md5(PATCH_FILENAME, "0" * 32),  # wrong MD5
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )
    mock_apply = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.apply_patch"
    )

    with pytest.raises(RuntimeError, match="MD5 verification failed"):
        huawei_client.upgrade()

    mock_apply.assert_not_called()


def test_upgrade_firmware_only_md5_match(mocker, huawei_client, fake_conn, tmp_path):
    firmware_file = tmp_path / TARGET_FILENAME
    firmware_file.write_bytes(b"firmware image contents")
    firmware_md5 = hashlib.md5(firmware_file.read_bytes()).hexdigest()

    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = str(firmware_file)

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current=100)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_file_md5(TARGET_FILENAME, firmware_md5),
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

    result = huawei_client.upgrade(return_result=True)

    assert result.metadata["md5_verified"] is True
    assert result.metadata["md5_results"] == {
        TARGET_FILENAME: {
            "expected_md5": firmware_md5,
            "actual_md5": firmware_md5,
            "match": True,
        }
    }


def test_upgrade_firmware_only_md5_mismatch_raises(mocker, huawei_client, fake_conn, tmp_path):
    firmware_file = tmp_path / TARGET_FILENAME
    firmware_file.write_bytes(b"firmware image contents")

    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = str(firmware_file)

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_file_md5(TARGET_FILENAME, "0" * 32),  # wrong MD5
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )
    mock_configure = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.configure_next_startup"
    )
    mocker.patch.object(huawei_client, "reboot")

    with pytest.raises(RuntimeError, match="MD5 verification failed"):
        huawei_client.upgrade()

    mock_configure.assert_not_called()
    huawei_client.reboot.assert_not_called()


def test_upgrade_firmware_and_patch_md5_match(mocker, huawei_client, fake_conn, tmp_path):
    firmware_file = tmp_path / TARGET_FILENAME
    patch_file = tmp_path / PATCH_FILENAME
    firmware_file.write_bytes(b"firmware image contents")
    patch_file.write_bytes(b"patch package contents")
    firmware_md5 = hashlib.md5(firmware_file.read_bytes()).hexdigest()
    patch_md5 = hashlib.md5(patch_file.read_bytes()).hexdigest()

    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = str(firmware_file)
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = str(patch_file)

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current=100)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # get_patch_info() before upgrade (current patch older than target)
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
        # MD5 verification: firmware then patch
        _display_file_md5(TARGET_FILENAME, firmware_md5),
        _display_file_md5(PATCH_FILENAME, patch_md5),
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

    assert result.metadata["md5_verified"] is True
    assert result.metadata["md5_results"] == {
        TARGET_FILENAME: {
            "expected_md5": firmware_md5,
            "actual_md5": firmware_md5,
            "match": True,
        },
        PATCH_FILENAME: {
            "expected_md5": patch_md5,
            "actual_md5": patch_md5,
            "match": True,
        },
    }


def test_upgrade_firmware_and_patch_md5_mismatch_on_firmware_raises(mocker, huawei_client, fake_conn, tmp_path):
    firmware_file = tmp_path / TARGET_FILENAME
    patch_file = tmp_path / PATCH_FILENAME
    firmware_file.write_bytes(b"firmware image contents")
    patch_file.write_bytes(b"patch package contents")

    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = str(firmware_file)
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = str(patch_file)

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
        _display_file_md5(TARGET_FILENAME, "0" * 32),  # wrong firmware MD5
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )
    mock_configure = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.configure_next_startup"
    )

    with pytest.raises(RuntimeError, match="MD5 verification failed"):
        huawei_client.upgrade()

    mock_configure.assert_not_called()


def test_upgrade_firmware_and_patch_md5_mismatch_on_patch_raises(mocker, huawei_client, fake_conn, tmp_path):
    firmware_file = tmp_path / TARGET_FILENAME
    patch_file = tmp_path / PATCH_FILENAME
    firmware_file.write_bytes(b"firmware image contents")
    patch_file.write_bytes(b"patch package contents")
    firmware_md5 = hashlib.md5(firmware_file.read_bytes()).hexdigest()

    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = str(firmware_file)
    huawei_client.patch_version = "ARV300R024SPH1b0"
    huawei_client.patch_file = str(patch_file)

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        _display_patch_information("ARV300R024SPH1a0", "old.pat"),
        _display_file_md5(TARGET_FILENAME, firmware_md5),  # firmware OK
        _display_file_md5(PATCH_FILENAME, "0" * 32),       # wrong patch MD5
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )
    mock_configure = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.configure_next_startup"
    )

    with pytest.raises(RuntimeError, match="MD5 verification failed"):
        huawei_client.upgrade()

    mock_configure.assert_not_called()
