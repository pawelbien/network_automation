# network_automation/tests/huawei_vrp/test_upload.py

import hashlib

import pytest
from pathlib import Path
from network_automation.platforms.huawei_vrp.upload import compute_local_md5
from network_automation.results import OperationResult


# -------------------------------------------------------
# Fake SFTP stack
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
# compute_local_md5
# -------------------------------------------------------

def test_compute_local_md5_matches_hashlib(tmp_path):
    local_file = tmp_path / "AR650A_V300R024C00SPC200.cc"
    local_file.write_bytes(b"firmware image contents" * 1000)

    expected = hashlib.md5(local_file.read_bytes()).hexdigest()

    assert compute_local_md5(local_file) == expected


def test_compute_local_md5_differs_for_different_content(tmp_path):
    file_a = tmp_path / "a.cc"
    file_b = tmp_path / "b.cc"
    file_a.write_bytes(b"content a")
    file_b.write_bytes(b"content b")

    assert compute_local_md5(file_a) != compute_local_md5(file_b)


# -------------------------------------------------------
# Tests
# -------------------------------------------------------

def test_upload_files_success(monkeypatch, huawei_client, tmp_path):
    """
    Upload single file via SFTP.
    """

    # ---- prepare local file ----
    local_file = tmp_path / "config.cfg"
    local_file.write_text("version 5.170")

    # ---- lifecycle mocks ----
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    # ---- fake SFTP ----
    fake_sftp = FakeSFTP()
    huawei_client.conn = FakeConn(fake_sftp)

    # ---- run upload ----
    result = huawei_client.upload(
        files=[str(local_file)],
        remote_dir="/flash/",
        return_result=True,
    )

    # ---- assertions ----
    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "upload"

    # ---- metadata ----
    assert result.metadata["files"] == ["config.cfg"]
    assert result.metadata["remote_dir"] == "/flash/"

    # ---- SFTP interaction ----
    assert fake_sftp.uploads == [
        (str(local_file), "/flash/config.cfg")
    ]


def test_upload_multiple_files(monkeypatch, huawei_client, tmp_path):
    """
    Upload multiple files; all appear in metadata and SFTP calls.
    """

    files = []
    for name in ("a.cfg", "b.pat"):
        f = tmp_path / name
        f.write_text("data")
        files.append(f)

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    fake_sftp = FakeSFTP()
    huawei_client.conn = FakeConn(fake_sftp)

    result = huawei_client.upload(
        files=[str(f) for f in files],
        remote_dir="/flash",
        return_result=True,
    )

    assert result.success is True
    assert result.metadata["files"] == ["a.cfg", "b.pat"]
    assert fake_sftp.uploads == [
        (str(files[0]), "/flash/a.cfg"),
        (str(files[1]), "/flash/b.pat"),
    ]


def test_upload_returns_none_when_return_result_false(monkeypatch, huawei_client, tmp_path):
    local_file = tmp_path / "test.cfg"
    local_file.write_text("data")

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    fake_sftp = FakeSFTP()
    huawei_client.conn = FakeConn(fake_sftp)

    result = huawei_client.upload(
        files=[str(local_file)],
        remote_dir="/flash",
        return_result=False,
    )

    assert result is None


def test_upload_missing_local_file_raises(monkeypatch, huawei_client, tmp_path):
    """
    Missing local file raises RuntimeError with descriptive message.
    """

    missing = tmp_path / "ghost.cfg"

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    fake_sftp = FakeSFTP()
    huawei_client.conn = FakeConn(fake_sftp)

    with pytest.raises(RuntimeError, match="ghost.cfg"):
        huawei_client.upload(
            files=[str(missing)],
            remote_dir="/flash",
        )


def test_upload_remote_dir_trailing_slash_normalised(monkeypatch, huawei_client, tmp_path):
    """
    remote_dir with and without trailing slash both produce the same remote path.
    """

    local_file = tmp_path / "fw.cc"
    local_file.write_text("data")

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    fake_sftp = FakeSFTP()
    huawei_client.conn = FakeConn(fake_sftp)

    huawei_client.upload(
        files=[str(local_file)],
        remote_dir="/flash/",
    )

    assert fake_sftp.uploads == [(str(local_file), "/flash/fw.cc")]
