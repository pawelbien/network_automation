# network_automation/tests/huawei_vrp/test_backup.py

from unittest.mock import MagicMock

import pytest

from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.backup import cleanup_old_backups, run_backup


# -------------------------------------------------------
# Fake SFTP stack
# -------------------------------------------------------

class FakeSFTP:
    def __init__(self):
        self.downloads = []

    def get(self, remote, local):
        self.downloads.append((remote, local))

    def close(self):
        pass


class FakeRemoteConnPre:
    def __init__(self, sftp):
        self._sftp = sftp

    def open_sftp(self):
        return self._sftp


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
    fake_conn.remote_conn_pre = FakeRemoteConnPre(fake_sftp)
    fake_conn.send_command_timing.side_effect = [
        "Save the configuration successfully.<Huawei>",
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

    fake_conn.send_command_timing.assert_any_call("save flash:/nauto_daily.zip")

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
    fake_conn.remote_conn_pre = FakeRemoteConnPre(fake_sftp)
    fake_conn.send_command_timing.side_effect = [
        "Save the configuration successfully.<Huawei>",
    ]
    huawei_client.conn = fake_conn

    outcome = huawei_client.backup("daily", download_dir=str(tmp_path))

    assert outcome is None
