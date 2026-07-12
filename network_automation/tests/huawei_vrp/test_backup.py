# network_automation/tests/huawei_vrp/test_backup.py

from unittest.mock import MagicMock

import pytest
from netmiko.exceptions import ReadTimeout

from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.backup import (
    cleanup_old_backups,
    run_backup,
    _flash_safe_filename,
    _verify_backup_file_exists,
    MAX_FLASH_PATH_LENGTH,
    _FLASH_INFO_RETRIES,
)


# -------------------------------------------------------
# Fake SFTP stack (dedicated connection opened internally by run_backup())
# -------------------------------------------------------

class FakeChannel:
    def __init__(self):
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout


class FakeSFTP:
    def __init__(self):
        self.downloads = []
        self.channel = FakeChannel()

    def get_channel(self):
        return self.channel

    def normalize(self, path):
        return "/"

    def get(self, remote, local, callback=None):
        self.downloads.append((remote, local))
        if callback is not None:
            callback(1, 1)

    def close(self):
        pass


class FakeConn:
    """Stands in for the plain paramiko.SSHClient _connect_dedicated() returns."""

    def __init__(self, sftp):
        self._sftp = sftp

    def open_sftp(self):
        return self._sftp

    def close(self):
        pass


@pytest.fixture
def fake_conn():
    return MagicMock()


# -------------------------------------------------------
# cleanup_old_backups
# -------------------------------------------------------

_DIR_WITH_BACKUPS = """\
Directory of flash:/

  Idx  Attr     Size(Byte)  Date        Time(LMT)  FileName
    0  drw-              -  Nov 30 2023 14:17:02   shelldir
   17  -rw-          2,305  Jul 01 2026 09:27:55   vrpcfg.zip
   18  -rw-          2,100  Jul 01 2026 09:00:00   nauto_old1.zip
   19  -rw-          2,100  Jul 02 2026 09:00:00   nauto_old2.zip

631,960 KB total available (237,728 KB free)
"""


def test_cleanup_old_backups_deletes_only_nauto_prefixed_files(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [_DIR_WITH_BACKUPS]
    fake_conn.send_command_timing.side_effect = [
        "Delete flash:/nauto_old1.zip?[Y/N]:",
        "Info: Deleting file flash:/nauto_old1.zip...succeeded",
        "Delete flash:/nauto_old2.zip?[Y/N]:",
        "Info: Deleting file flash:/nauto_old2.zip...succeeded",
    ]

    cleanup_old_backups(huawei_client)

    fake_conn.send_command.assert_called_once_with("dir")

    timing_commands = [call.args[0] for call in fake_conn.send_command_timing.call_args_list]
    assert timing_commands == [
        "delete flash:/nauto_old1.zip", "y",
        "delete flash:/nauto_old2.zip", "y",
    ]


def test_cleanup_old_backups_no_candidates_deletes_nothing(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = ["""\
Directory of flash:/

  Idx  Attr     Size(Byte)  Date        Time(LMT)  FileName
   17  -rw-          2,305  Jul 01 2026 09:27:55   vrpcfg.zip

631,960 KB total available (237,728 KB free)
"""]

    cleanup_old_backups(huawei_client)

    fake_conn.send_command_timing.assert_not_called()


# -------------------------------------------------------
# run_backup
# -------------------------------------------------------

def test_run_backup_returns_result_and_downloads(monkeypatch, huawei_client, fake_conn, tmp_path):
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.backup.cleanup_old_backups",
        lambda client: None,
    )

    fake_sftp = FakeSFTP()
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )
    fake_conn.send_command.side_effect = [
        "Save the configuration successfully.<Huawei>",
        """\
Directory of flash:/

  Idx  Attr     Size(Byte)  Date        Time(LMT)  FileName
   17  -rw-          2,305  Jul 01 2026 09:27:55   nauto_daily.zip

631,960 KB total available (237,728 KB free)
""",
    ]
    huawei_client.conn = fake_conn

    result = huawei_client.backup(
        "daily",
        return_result=True,
        download_dir=str(tmp_path),
    )

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "backup"

    assert result.metadata["backup_name"] == "daily"
    assert result.metadata["remote_file"] == "daily.zip"
    assert result.metadata["local_path"] == f"{tmp_path}/daily.zip"

    fake_conn.send_command.assert_any_call(
        "save flash:/nauto_daily.zip",
        expect_string=r"(?i)y/n|[\]>]",
        read_timeout=300,
        strip_prompt=False,
        strip_command=False,
    )

    assert fake_sftp.downloads == [
        ("flash:/nauto_daily.zip", f"{tmp_path}/daily.zip")
    ]


def test_run_backup_return_result_false_returns_none(monkeypatch, huawei_client, fake_conn, tmp_path):
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.backup.cleanup_old_backups",
        lambda client: None,
    )

    fake_sftp = FakeSFTP()
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )
    fake_conn.send_command.side_effect = [
        "Save the configuration successfully.<Huawei>",
        """\
Directory of flash:/

  Idx  Attr     Size(Byte)  Date        Time(LMT)  FileName
   17  -rw-          2,305  Jul 01 2026 09:27:55   nauto_daily.zip

631,960 KB total available (237,728 KB free)
""",
    ]
    huawei_client.conn = fake_conn

    outcome = huawei_client.backup("daily", download_dir=str(tmp_path))

    assert outcome is None


def test_run_backup_raises_when_save_did_not_create_file(monkeypatch, huawei_client, fake_conn, tmp_path):
    """
    save_configuration()'s [Y/N] handling is unverified on hardware other
    than the two lab units it was tested against — if 'save <filename>'
    doesn't actually create the file (observed live on a third device),
    run_backup() must fail with a clear RuntimeError right after save,
    not a bare/cryptic SFTP error from the download attempt.
    """
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.backup.cleanup_old_backups",
        lambda client: None,
    )

    fake_sftp = FakeSFTP()
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )
    # 'dir' listing does NOT contain nauto_daily.zip — save didn't create it.
    fake_conn.send_command.side_effect = [
        "Save the configuration successfully.<Huawei>",
        """\
Directory of flash:/

  Idx  Attr     Size(Byte)  Date        Time(LMT)  FileName
   17  -rw-          2,305  Jul 01 2026 09:27:55   vrpcfg.zip

631,960 KB total available (237,728 KB free)
""",
    ]
    huawei_client.conn = fake_conn

    with pytest.raises(RuntimeError, match="was not found on the device after 'save'"):
        huawei_client.backup("daily", download_dir=str(tmp_path))

    # download must never be attempted for a file that doesn't exist
    assert fake_sftp.downloads == []


# -------------------------------------------------------
# _flash_safe_filename
# -------------------------------------------------------

def test_flash_safe_filename_short_name_unchanged():
    assert _flash_safe_filename("net-lab-hua-r3-260712_132114") == \
        "nauto_net-lab-hua-r3-260712_132114.zip"


def test_flash_safe_filename_falls_back_to_hash_when_too_long():
    # Same device name that failed live (2026-07-12): 71-char remote path.
    long_name = "01029595-Krotoski-Przybyszewskiego176-r1-260712_224107"
    assert len(f"flash:/nauto_{long_name}.zip") > MAX_FLASH_PATH_LENGTH

    result = _flash_safe_filename(long_name)

    assert len(f"flash:/{result}") <= MAX_FLASH_PATH_LENGTH
    assert result.startswith("nauto_")
    assert result.endswith(".zip")
    assert long_name not in result


def test_flash_safe_filename_hash_is_deterministic_and_name_sensitive():
    assert _flash_safe_filename("a" * 60) == _flash_safe_filename("a" * 60)
    assert _flash_safe_filename("a" * 60) != _flash_safe_filename("b" * 60)


def test_run_backup_uses_hashed_filename_for_long_device_name(monkeypatch, huawei_client, fake_conn, tmp_path):
    """
    A long device name (like the one that failed live) must produce a
    remote path within MAX_FLASH_PATH_LENGTH — verified end-to-end via the
    same command run_backup() actually sends.
    """
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.backup.cleanup_old_backups",
        lambda client: None,
    )

    long_name = "01029595-Krotoski-Przybyszewskiego176-r1-260712_224107"
    expected_filename = _flash_safe_filename(long_name)

    fake_sftp = FakeSFTP()
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )
    fake_conn.send_command.side_effect = [
        "Save the configuration successfully.<Huawei>",
        f"""\
Directory of flash:/

  Idx  Attr     Size(Byte)  Date        Time(LMT)  FileName
   17  -rw-          2,305  Jul 01 2026 09:27:55   {expected_filename}

631,960 KB total available (237,728 KB free)
""",
    ]
    huawei_client.conn = fake_conn

    result = huawei_client.backup(
        long_name,
        return_result=True,
        download_dir=str(tmp_path),
    )

    assert result.success is True
    sent_command = fake_conn.send_command.call_args_list[0].args[0]
    assert sent_command == f"save flash:/{expected_filename}"
    assert len(sent_command.removeprefix("save ")) <= MAX_FLASH_PATH_LENGTH
    # OperationResult metadata still reports the full, un-hashed logical name.
    assert result.metadata["remote_file"] == f"{long_name}.zip"
    assert result.metadata["local_path"] == f"{tmp_path}/{long_name}.zip"


# -------------------------------------------------------
# _verify_backup_file_exists: ReadTimeout retry
# -------------------------------------------------------

def test_verify_backup_file_exists_retries_on_read_timeout_then_succeeds(mocker, huawei_client):
    mock_sleep = mocker.patch("network_automation.platforms.huawei_vrp.backup.time.sleep")
    mock_get_flash_info = mocker.patch(
        "network_automation.platforms.huawei_vrp.backup.get_flash_info",
        side_effect=[
            ReadTimeout("Pattern not detected: 'dir' in output."),
            {"files": [{"name": "nauto_daily.zip", "size": 2305, "is_dir": False}]},
        ],
    )

    _verify_backup_file_exists(huawei_client, filename="nauto_daily.zip")

    assert mock_get_flash_info.call_count == 2
    mock_sleep.assert_called_once()


def test_verify_backup_file_exists_raises_after_exhausting_read_timeout_retries(mocker, huawei_client):
    mock_sleep = mocker.patch("network_automation.platforms.huawei_vrp.backup.time.sleep")
    mock_get_flash_info = mocker.patch(
        "network_automation.platforms.huawei_vrp.backup.get_flash_info",
        side_effect=ReadTimeout("Pattern not detected: 'dir' in output."),
    )

    with pytest.raises(RuntimeError, match="Could not read the flash directory listing"):
        _verify_backup_file_exists(huawei_client, filename="nauto_daily.zip")

    assert mock_get_flash_info.call_count == _FLASH_INFO_RETRIES
    assert mock_sleep.call_count == _FLASH_INFO_RETRIES - 1
