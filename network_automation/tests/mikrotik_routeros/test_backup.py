# network_automation/tests/mikrotik_routeros/test_backup.py

from network_automation.results import OperationResult
from network_automation.platforms.mikrotik_routeros.backup import (
    _safe_backup_name,
    MAX_BACKUP_NAME_LENGTH,
)

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


def test_backup_returns_result_and_downloads(monkeypatch, mikrotik_client, tmp_path):
    # ---- lifecycle mocks ----
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    # ---- fake SFTP stack ----
    fake_sftp = FakeSFTP()
    mikrotik_client.conn = FakeConn(fake_sftp)

    # ---- run backup ----
    result = mikrotik_client.backup(
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


# -------------------------------------------------------
# _safe_backup_name
# -------------------------------------------------------

def test_safe_backup_name_short_name_unchanged():
    assert _safe_backup_name("test-backup") == "nauto_test-backup"


def test_safe_backup_name_falls_back_to_hash_when_too_long():
    # No "flash:/" prefix or ".zip" extension here (unlike huawei_vrp), so
    # more headroom before MAX_BACKUP_NAME_LENGTH is exceeded — needs a
    # longer name than the VRP case to actually trigger the fallback.
    long_name = "01029595-Krotoski-Przybyszewskiego176-r1-260712_224107-extra"
    assert len(f"nauto_{long_name}") > MAX_BACKUP_NAME_LENGTH

    result = _safe_backup_name(long_name)

    assert len(result) <= MAX_BACKUP_NAME_LENGTH
    assert result.startswith("nauto_")
    assert long_name not in result


def test_safe_backup_name_hash_is_deterministic_and_name_sensitive():
    assert _safe_backup_name("a" * 60) == _safe_backup_name("a" * 60)
    assert _safe_backup_name("a" * 60) != _safe_backup_name("b" * 60)


def test_backup_uses_hashed_name_for_long_device_name(monkeypatch, mikrotik_client, tmp_path):
    """
    A long device name must produce an on-device backup name within
    MAX_BACKUP_NAME_LENGTH — verified end-to-end via the same command
    run_backup() actually sends.
    """
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    long_name = "01029595-Krotoski-Przybyszewskiego176-r1-260712_224107-extra"
    assert len(f"nauto_{long_name}") > MAX_BACKUP_NAME_LENGTH
    expected_backup_name = _safe_backup_name(long_name)

    fake_sftp = FakeSFTP()
    mikrotik_client.conn = FakeConn(fake_sftp)

    mikrotik_client.backup(
        long_name,
        return_result=True,
        download_dir=str(tmp_path),
    )

    assert fake_sftp.downloads == [
        (f"{expected_backup_name}.backup", f"{tmp_path}/{long_name}.backup")
    ]
