# network_automation/tests/mikrotik_routeros/test_backup_result.py

from network_automation.results import OperationResult

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


class FakeConn:
    def __init__(self, sftp):
        self.remote_conn_pre = FakeRemoteConnPre(sftp)

    def send_command(self, *args, **kwargs):
        return ""


def test_backup_returns_result_and_downloads(monkeypatch, updater, tmp_path):
    # ---- lifecycle mocks ----
    monkeypatch.setattr(updater, "connect", lambda: None)
    monkeypatch.setattr(updater, "disconnect", lambda: None)

    # ---- fake SFTP stack ----
    fake_sftp = FakeSFTP()
    updater.conn = FakeConn(fake_sftp)

    # ---- run backup ----
    result = updater.backup(
        "test-backup",
        return_result=True,
        download_dir=str(tmp_path),
    )

    # ---- assertions ----
    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "backup"

    # ---- metadata ----
    assert result.metadata["remote_file"] == "test-backup.backup"
    assert result.metadata["local_path"].endswith("test-backup.backup")

    # ---- SFTP interaction ----
    assert fake_sftp.downloads == [
        ("nauto_test-backup.backup", f"{tmp_path}/test-backup.backup")
    ]
