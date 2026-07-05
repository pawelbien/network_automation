# network_automation/tests/huawei_vrp/test_flash.py

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from network_automation.platforms.huawei_vrp.flash import (
    _delete_file,
    calculate_required_space,
    cleanup_flash,
    ensure_flash_space,
)
from network_automation.platforms.huawei_vrp.version import (
    OPERATION_FIRMWARE_AND_PATCH,
    OPERATION_FIRMWARE_ONLY,
    OPERATION_PATCH_ONLY,
)

_FLASH_FILES = [
    {"name": "shelldir", "size": 0, "is_dir": True},
    {"name": "AR650A_V300R023C00SPC100.cc", "size": 161_819_648, "is_dir": False},
    {"name": "AR650A_V300R022C00SPC100.cc", "size": 198_369_024, "is_dir": False},
    {"name": "AR650A_V300R023SPH1b0.pat", "size": 13_396_864, "is_dir": False},
    {"name": "orphan.cc", "size": 50_000_000, "is_dir": False},
]


# ---------- calculate_required_space ----------

def test_calculate_required_space_basic():
    required = calculate_required_space(100_000_000, 10_000_000, [])

    assert required == 100_000_000 + 10_000_000 + 50 * 1024 * 1024


def test_calculate_required_space_adds_overwrite_margin_for_existing_same_name_file():
    required = calculate_required_space(
        100_000_000, 0, _FLASH_FILES,
        target_cc_name="AR650A_V300R023C00SPC100.cc",
    )

    assert required == 100_000_000 + 0 + 50 * 1024 * 1024 + 161_819_648


def test_calculate_required_space_no_overwrite_margin_when_name_not_present():
    required = calculate_required_space(
        100_000_000, 0, _FLASH_FILES,
        target_cc_name="new_firmware.cc",
    )

    assert required == 100_000_000 + 50 * 1024 * 1024


def test_calculate_required_space_custom_safety_margin():
    required = calculate_required_space(0, 0, [], safety_margin=1000)

    assert required == 1000


# ---------- _delete_file ----------

def test_delete_file_succeeds():
    conn = MagicMock()
    conn.send_command_timing.side_effect = [
        "Info: Delete flash:/old.cc? [Y/N]:",
        "Info: Deleting file flash:/old.cc...succeeded.",
    ]
    client = SimpleNamespace(conn=conn)

    _delete_file(client, "old.cc")

    assert conn.send_command_timing.call_count == 2


def test_delete_file_raises_when_rejected_as_system_startup_file():
    conn = MagicMock()
    conn.send_command_timing.side_effect = [
        "Info: Delete flash:/old.cc? [Y/N]:",
        "Error: This is system startup file",
    ]
    client = SimpleNamespace(conn=conn)

    with pytest.raises(RuntimeError, match="Failed to delete"):
        _delete_file(client, "old.cc")


# ---------- cleanup_flash ----------

def test_cleanup_flash_deletes_only_candidates():
    conn = MagicMock()
    conn.send_command_timing.side_effect = [
        "succeeded.",  # delete orphan.cc (no [Y/N] in this fake output)
        "succeeded.",  # reset recycle-bin
    ]
    client = SimpleNamespace(conn=conn, logger=MagicMock())

    deleted_files = cleanup_flash(
        client,
        flash_files=_FLASH_FILES,
        protected_names={
            "AR650A_V300R023C00SPC100.cc",
            "AR650A_V300R022C00SPC100.cc",
            "AR650A_V300R023SPH1b0.pat",
        },
        startup_image_name="AR650A_V300R023C00SPC100.cc",
        backup_image_name=None,
    )

    deleted = [
        c.args[0] for c in conn.send_command_timing.call_args_list
        if c.args[0].startswith("delete ")
    ]
    assert deleted == ["delete flash:/orphan.cc"]
    conn.send_command_timing.assert_any_call("reset recycle-bin")
    assert deleted_files == ["orphan.cc"]


def test_cleanup_flash_repoints_backup_before_deleting_it():
    conn = MagicMock()
    conn.send_command.return_value = "Info: Succeeded in setting the backup file for booting system"
    conn.send_command_timing.side_effect = [
        "succeeded.",  # delete AR650A_V300R022C00SPC100.cc (old backup)
        "succeeded.",  # delete orphan.cc
        "succeeded.",  # reset recycle-bin
    ]
    client = SimpleNamespace(conn=conn, logger=MagicMock())

    deleted_files = cleanup_flash(
        client,
        flash_files=_FLASH_FILES,
        protected_names={
            "AR650A_V300R023C00SPC100.cc",
            "AR650A_V300R023SPH1b0.pat",
        },
        startup_image_name="AR650A_V300R023C00SPC100.cc",
        backup_image_name="AR650A_V300R022C00SPC100.cc",
    )

    conn.send_command.assert_called_once_with(
        "startup system-software AR650A_V300R023C00SPC100.cc backup",
        read_timeout=300,
    )
    conn.send_command_timing.assert_any_call("delete flash:/AR650A_V300R022C00SPC100.cc")
    assert set(deleted_files) == {"AR650A_V300R022C00SPC100.cc", "orphan.cc"}


def test_cleanup_flash_never_touches_protected_files():
    conn = MagicMock()
    conn.send_command_timing.side_effect = ["succeeded."] * 10
    client = SimpleNamespace(conn=conn, logger=MagicMock())

    cleanup_flash(
        client,
        flash_files=_FLASH_FILES,
        protected_names={
            "AR650A_V300R023C00SPC100.cc",
            "AR650A_V300R022C00SPC100.cc",
            "AR650A_V300R023SPH1b0.pat",
        },
        startup_image_name="AR650A_V300R023C00SPC100.cc",
        backup_image_name="AR650A_V300R022C00SPC100.cc",  # protected -> not a candidate
    )

    deleted = [
        c.args[0] for c in conn.send_command_timing.call_args_list
        if c.args[0].startswith("delete ")
    ]
    assert deleted == ["delete flash:/orphan.cc"]
    conn.send_command.assert_not_called()  # no backup re-point needed


# ---------- ensure_flash_space ----------

def _client_with_flash(mocker, free_bytes, flash_files=_FLASH_FILES, already_on_flash=False):
    client = SimpleNamespace(
        conn=MagicMock(), logger=MagicMock(),
        firmware_file="/tmp/AR650A_V300R024C00SPC200.cc",
        patch_file="/tmp/AR650A_V300R024SPH1b0.pat",
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.get_flash_info",
        return_value={"files": flash_files, "free_bytes": free_bytes},
    )
    mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.file_already_on_flash",
        return_value=(already_on_flash, {"match": already_on_flash}),
    )
    return client


def test_ensure_flash_space_continues_when_enough_free(mocker, tmp_path):
    firmware_file = tmp_path / "fw.cc"
    firmware_file.write_bytes(b"x" * 1000)
    client = _client_with_flash(mocker, free_bytes=10_000_000_000)
    client.firmware_file = str(firmware_file)
    client.patch_file = None
    result = SimpleNamespace(metadata={})

    mock_cleanup = mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.cleanup_flash"
    )

    ensure_flash_space(client, result, OPERATION_FIRMWARE_ONLY, [{"model": "AR651"}])

    mock_cleanup.assert_not_called()
    assert "flash_cleanup_performed" not in result.metadata
    assert result.metadata["flash_required_bytes"] == 1000 + 50 * 1024 * 1024


def test_ensure_flash_space_runs_cleanup_when_insufficient(mocker, tmp_path):
    firmware_file = tmp_path / "fw.cc"
    firmware_file.write_bytes(b"x" * 1000)
    client = _client_with_flash(mocker, free_bytes=100)
    client.firmware_file = str(firmware_file)
    client.patch_file = None
    result = SimpleNamespace(metadata={})

    mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.get_flash_info",
        side_effect=[
            {"files": _FLASH_FILES, "free_bytes": 100},
            {"files": _FLASH_FILES, "free_bytes": 10_000_000_000},
        ],
    )
    mock_cleanup = mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.cleanup_flash",
        return_value=["orphan.cc"],
    )

    units = [{
        "startup_image": "flash:/AR650A_V300R023C00SPC100.cc",
        "next_startup_image": "flash:/AR650A_V300R023C00SPC100.cc",
        "backup_image": "flash:/AR650A_V300R022C00SPC100.cc",
        "startup_patch": None,
        "next_startup_patch": None,
    }]

    ensure_flash_space(client, result, OPERATION_FIRMWARE_ONLY, units)

    mock_cleanup.assert_called_once()
    assert result.metadata["flash_cleanup_performed"] is True
    assert result.metadata["flash_free_bytes"] == 10_000_000_000
    assert result.metadata["deleted_files"] == ["orphan.cc"]


def test_ensure_flash_space_dry_run_skips_cleanup(mocker, tmp_path):
    firmware_file = tmp_path / "fw.cc"
    firmware_file.write_bytes(b"x" * 1000)
    client = _client_with_flash(mocker, free_bytes=100)
    client.firmware_file = str(firmware_file)
    client.patch_file = None
    result = SimpleNamespace(metadata={})

    mock_cleanup = mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.cleanup_flash"
    )

    units = [{
        "startup_image": "flash:/AR650A_V300R023C00SPC100.cc",
        "next_startup_image": "flash:/AR650A_V300R023C00SPC100.cc",
        "backup_image": "flash:/AR650A_V300R022C00SPC100.cc",
        "startup_patch": None,
        "next_startup_patch": None,
    }]

    ensure_flash_space(client, result, OPERATION_FIRMWARE_ONLY, units, dry_run=True)

    mock_cleanup.assert_not_called()
    assert result.metadata["flash_cleanup_would_run"] is True
    assert "flash_cleanup_performed" not in result.metadata
    assert "deleted_files" not in result.metadata


def test_ensure_flash_space_raises_when_still_insufficient_after_cleanup(mocker, tmp_path):
    firmware_file = tmp_path / "fw.cc"
    firmware_file.write_bytes(b"x" * 1000)
    client = _client_with_flash(mocker, free_bytes=100)
    client.firmware_file = str(firmware_file)
    client.patch_file = None
    result = SimpleNamespace(metadata={})

    mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.get_flash_info",
        return_value={"files": _FLASH_FILES, "free_bytes": 100},
    )
    mocker.patch("network_automation.platforms.huawei_vrp.flash.cleanup_flash")

    units = [{
        "startup_image": "flash:/AR650A_V300R023C00SPC100.cc",
        "next_startup_image": "flash:/AR650A_V300R023C00SPC100.cc",
        "backup_image": None,
        "startup_patch": None,
        "next_startup_patch": None,
    }]

    with pytest.raises(RuntimeError, match="Insufficient flash space"):
        ensure_flash_space(client, result, OPERATION_FIRMWARE_ONLY, units)


def test_ensure_flash_space_skips_target_already_on_flash(mocker, tmp_path):
    # Root cause #6 (docs/problems/huawei-vrp-sftp-open-failure.md): a target
    # file already on flash with a matching MD5 won't actually be
    # re-uploaded (idempotency skips it in _upload_pending), so it must
    # contribute zero bytes — no size, no overwrite_margin — to
    # required_space, or a tight-but-sufficient device would be pushed into
    # a needless (or, once the file is protected as next_startup_image,
    # outright failing) cleanup.
    # free_bytes deliberately less than the target file's own size (but more
    # than the safety margin alone) — proves the fix, not just a generously
    # free device: this would fail calculate_required_space's old behavior
    # (which double-counted the existing file via overwrite_margin) but
    # must succeed now that an already-matching target contributes 0 bytes.
    firmware_file = tmp_path / "fw.cc"
    firmware_file.write_bytes(b"x" * 1000)
    client = _client_with_flash(mocker, free_bytes=60 * 1024 * 1024, already_on_flash=True)
    client.firmware_file = str(firmware_file)
    client.patch_file = None
    result = SimpleNamespace(metadata={})

    mock_cleanup = mocker.patch(
        "network_automation.platforms.huawei_vrp.flash.cleanup_flash"
    )

    ensure_flash_space(client, result, OPERATION_FIRMWARE_ONLY, [{"model": "AR651"}])

    mock_cleanup.assert_not_called()
    assert result.metadata["flash_required_bytes"] == 50 * 1024 * 1024
    assert "flash_cleanup_performed" not in result.metadata


def test_ensure_flash_space_only_sizes_files_the_operation_needs(mocker, tmp_path):
    # PATCH_ONLY must not stat() firmware_file (which may not even exist).
    patch_file = tmp_path / "p.pat"
    patch_file.write_bytes(b"x" * 500)
    client = _client_with_flash(mocker, free_bytes=10_000_000_000)
    client.firmware_file = "/nonexistent/does-not-exist.cc"
    client.patch_file = str(patch_file)
    result = SimpleNamespace(metadata={})

    ensure_flash_space(client, result, OPERATION_PATCH_ONLY, [{"model": "AR651"}])

    assert result.metadata["flash_required_bytes"] == 500 + 50 * 1024 * 1024
