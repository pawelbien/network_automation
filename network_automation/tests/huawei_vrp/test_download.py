# network_automation/tests/huawei_vrp/test_download.py

from unittest.mock import MagicMock

import pytest

from network_automation.results import OperationResult


@pytest.fixture(autouse=True)
def _skip_sftp_server_check(mocker):
    """
    _ensure_sftp_server_enabled() needs client.conn.send_command(), which
    these tests don't set up (they exercise the dedicated SFTP connection
    only, not client.conn) — patched to a no-op here. See
    test_sftp_server_check.py for dedicated tests of the check itself.
    """
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload._ensure_sftp_server_enabled",
    )


# -------------------------------------------------------
# Fake SFTP stack (dedicated connection opened internally by download_files())
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
# Tests
# -------------------------------------------------------

def test_download_files_success(monkeypatch, huawei_client, fake_conn, tmp_path):
    """
    Download single file via SFTP.
    """

    # ---- lifecycle mocks ----
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    # ---- fake dedicated SFTP connection ----
    fake_sftp = FakeSFTP()
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )
    huawei_client.conn = fake_conn

    # ---- run download ----
    result = huawei_client.download(
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
