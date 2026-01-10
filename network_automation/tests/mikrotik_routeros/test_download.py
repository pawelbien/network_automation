# network_automation/tests/mikrotik_routeros/test_uload.py

from pathlib import Path
from network_automation.results import OperationResult


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


class FakeConn:
    def __init__(self, sftp):
        self.remote_conn_pre = FakeRemoteConnPre(sftp)


# -------------------------------------------------------
# Tests
# -------------------------------------------------------

def test_download_files_success(monkeypatch, mikrotik_client, tmp_path):
    """
    Download single file via SFTP.
    """

    # ---- lifecycle mocks ----
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    # ---- fake SFTP ----
    fake_sftp = FakeSFTP()
    mikrotik_client.conn = FakeConn(fake_sftp)

    # ---- run download ----
    result = mikrotik_client.download(
        files=["test.txt"],
        local_dir=str(tmp_path),
        return_result=True,
    )

    # ---- assertions ----
    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "download"

    # ---- metadata ----
    assert result.metadata["files"] == ["test.txt"]
    assert result.metadata["local_dir"] == str(tmp_path)

    # ---- SFTP interaction ----
    expected_local = str(tmp_path / "test.txt")
    assert fake_sftp.downloads == [
        ("test.txt", expected_local)
    ]
