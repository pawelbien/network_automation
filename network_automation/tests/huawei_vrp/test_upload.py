# network_automation/tests/huawei_vrp/test_upload.py

import hashlib

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from network_automation.platforms.huawei_vrp.upload import (
    compute_local_md5,
    verify_remote_file,
    upload_with_retry,
)
from network_automation.results import OperationResult


# -------------------------------------------------------
# Fake SFTP stack
# -------------------------------------------------------

class FakeChannel:
    def __init__(self):
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout


class FakeSFTP:
    def __init__(self, fail_first_n=0):
        self.uploads = []
        self.channel = FakeChannel()
        self._fail_first_n = fail_first_n
        self._put_calls = 0

    def get_channel(self):
        return self.channel

    def normalize(self, path):
        return "/"

    def put(self, local, remote):
        self._put_calls += 1
        if self._put_calls <= self._fail_first_n:
            raise OSError("simulated transfer failure")
        self.uploads.append((local, remote))

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

    # ---- fake SFTP (dedicated connection opened internally by upload_files()) ----
    fake_sftp = FakeSFTP()
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )

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
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )

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
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )

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
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )

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
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        lambda client: FakeConn(fake_sftp),
    )

    huawei_client.upload(
        files=[str(local_file)],
        remote_dir="/flash/",
    )

    assert fake_sftp.uploads == [(str(local_file), "/flash/fw.cc")]


# -------------------------------------------------------
# verify_remote_file (Faza 9)
# -------------------------------------------------------

def test_verify_remote_file_success(mocker, huawei_client):
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload.get_flash_info",
        return_value={
            "files": [{"name": "fw.cc", "size": 1234, "is_dir": False}],
            "free_bytes": 10_000_000,
        },
    )

    result = verify_remote_file(huawei_client, filename="fw.cc", expected_size=1234)

    assert result == {
        "exists": True,
        "expected_size": 1234,
        "actual_size": 1234,
        "match": True,
    }


def test_verify_remote_file_missing_raises(mocker, huawei_client):
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload.get_flash_info",
        return_value={"files": [], "free_bytes": 10_000_000},
    )

    with pytest.raises(RuntimeError, match="not found on flash"):
        verify_remote_file(huawei_client, filename="fw.cc", expected_size=1234)


def test_verify_remote_file_size_mismatch_raises(mocker, huawei_client):
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload.get_flash_info",
        return_value={
            "files": [{"name": "fw.cc", "size": 999, "is_dir": False}],
            "free_bytes": 10_000_000,
        },
    )

    with pytest.raises(RuntimeError, match="expected size 1234"):
        verify_remote_file(huawei_client, filename="fw.cc", expected_size=1234)


# -------------------------------------------------------
# upload_with_retry (Faza 9)
# -------------------------------------------------------

def _mock_flash_info_for(mocker, files):
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload.get_flash_info",
        return_value={
            "files": [
                {"name": p.name, "size": p.stat().st_size, "is_dir": False}
                for p in files
            ],
            "free_bytes": 10_000_000,
        },
    )


def test_upload_with_retry_success_first_attempt(mocker, huawei_client, tmp_path):
    local_file = tmp_path / "fw.cc"
    local_file.write_bytes(b"firmware contents")

    fake_sftp = FakeSFTP()
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        return_value=FakeConn(fake_sftp),
    )
    _mock_flash_info_for(mocker, [local_file])

    result = upload_with_retry(
        huawei_client, files=[local_file], remote_dir="flash:/", timeout=30, retries=3,
    )

    assert fake_sftp.uploads == [(str(local_file), "flash:/fw.cc")]
    assert result["fw.cc"]["match"] is True
    assert fake_sftp.channel.timeout == 30


def test_upload_with_retry_succeeds_after_one_failure(mocker, huawei_client, tmp_path):
    local_file = tmp_path / "fw.cc"
    local_file.write_bytes(b"firmware contents")

    fake_sftp = FakeSFTP(fail_first_n=1)
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        return_value=FakeConn(fake_sftp),
    )
    _mock_flash_info_for(mocker, [local_file])
    mock_sleep = mocker.patch("network_automation.platforms.huawei_vrp.upload.time.sleep")

    result = upload_with_retry(
        huawei_client, files=[local_file], remote_dir="flash:/", timeout=30, retries=3,
    )

    assert result["fw.cc"]["match"] is True
    assert fake_sftp.uploads == [(str(local_file), "flash:/fw.cc")]
    mock_sleep.assert_called_once()


def test_upload_with_retry_exhausts_retries_raises(mocker, huawei_client, tmp_path):
    local_file = tmp_path / "fw.cc"
    local_file.write_bytes(b"firmware contents")

    fake_sftp = FakeSFTP(fail_first_n=99)
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        return_value=FakeConn(fake_sftp),
    )
    mocker.patch("network_automation.platforms.huawei_vrp.upload.time.sleep")

    with pytest.raises(RuntimeError, match="Upload failed after 3 attempt"):
        upload_with_retry(
            huawei_client, files=[local_file], remote_dir="flash:/", timeout=30, retries=3,
        )

    assert fake_sftp._put_calls == 3


def test_upload_with_retry_missing_local_file_not_retried(mocker, huawei_client, tmp_path):
    missing_file = tmp_path / "ghost.cc"

    fake_sftp = FakeSFTP()
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
        return_value=FakeConn(fake_sftp),
    )
    mock_sleep = mocker.patch("network_automation.platforms.huawei_vrp.upload.time.sleep")

    with pytest.raises(FileNotFoundError):
        upload_with_retry(
            huawei_client, files=[missing_file], remote_dir="flash:/", timeout=30, retries=3,
        )

    mock_sleep.assert_not_called()
