# network_automation/tests/mikrotik_routeros/test_uload.py

from pathlib import Path
from network_automation.results import OperationResult


# -------------------------------------------------------
# Fake SFTP stack (jak w test_backup)
# -------------------------------------------------------

class FakeSFTP:
    def __init__(self):
        self.uploads = []

    def put(self, local, remote):
        self.uploads.append((local, remote))

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

def test_upload_files_success(monkeypatch, mikrotik_client, tmp_path):
    """
    Upload single file via SFTP.
    """

    # ---- prepare local file ----
    local_file = tmp_path / "test.txt"
    local_file.write_text("hello")

    # ---- lifecycle mocks ----
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    # ---- fake SFTP ----
    fake_sftp = FakeSFTP()
    mikrotik_client.conn = FakeConn(fake_sftp)

    # ---- run upload ----
    result = mikrotik_client.upload(
        files=[str(local_file)],
        remote_dir="/",
        return_result=True,
    )

    # ---- assertions ----
    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "upload"

    # ---- metadata ----
    assert result.metadata["files"] == ["test.txt"]
    assert result.metadata["remote_dir"] == "/"

    # ---- SFTP interaction ----
    assert fake_sftp.uploads == [
        (str(local_file), "/test.txt")
    ]
