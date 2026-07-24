# network_automation/tests/opnsense/test_backup.py

import pytest

from network_automation.results import OperationResult
from network_automation.platforms.opnsense.backup import _looks_like_valid_config_xml


class FakeSFTP:
    def __init__(self, content: bytes = b"<?xml version=\"1.0\"?>\n<opnsense></opnsense>\n"):
        self.downloads = []
        self._content = content

    def get(self, remote, local):
        self.downloads.append((remote, local))
        with open(local, "wb") as f:
            f.write(self._content)

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


def test_backup_returns_result_and_downloads(monkeypatch, opnsense_client, tmp_path):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)

    fake_sftp = FakeSFTP()
    opnsense_client.conn = FakeConn(fake_sftp)

    result = opnsense_client.backup(
        "test-backup",
        return_result=True,
        download_dir=str(tmp_path),
    )

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "backup"

    assert result.metadata["remote_file"] == "/conf/config.xml"
    assert result.metadata["local_path"] == f"{tmp_path}/test-backup.xml"

    assert fake_sftp.downloads == [
        ("/conf/config.xml", f"{tmp_path}/test-backup.xml")
    ]


def test_backup_return_result_false_returns_none(monkeypatch, opnsense_client, tmp_path):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)
    opnsense_client.conn = FakeConn(FakeSFTP())

    assert opnsense_client.backup("test-backup", download_dir=str(tmp_path)) is None


def test_backup_raises_and_marks_failed_on_sftp_error(monkeypatch, opnsense_client, tmp_path):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)

    class BrokenSFTP(FakeSFTP):
        def get(self, remote, local):
            raise OSError("no such file")

    opnsense_client.conn = FakeConn(BrokenSFTP())

    with pytest.raises(OSError):
        opnsense_client.backup("test-backup", download_dir=str(tmp_path))


def test_backup_raises_on_empty_downloaded_file(monkeypatch, opnsense_client, tmp_path):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)

    opnsense_client.conn = FakeConn(FakeSFTP(content=b""))

    with pytest.raises(RuntimeError, match="empty"):
        opnsense_client.backup("test-backup", download_dir=str(tmp_path))


def test_backup_raises_on_non_xml_downloaded_file(monkeypatch, opnsense_client, tmp_path):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)

    opnsense_client.conn = FakeConn(FakeSFTP(content=b"not xml at all"))

    with pytest.raises(RuntimeError, match="does not look like valid XML"):
        opnsense_client.backup("test-backup", download_dir=str(tmp_path))


# -------------------------------------------------------
# _looks_like_valid_config_xml
# -------------------------------------------------------

def test_looks_like_valid_config_xml_accepts_real_config(tmp_path):
    path = tmp_path / "config.xml"
    path.write_bytes(b"<?xml version=\"1.0\"?>\n<opnsense></opnsense>\n")

    _looks_like_valid_config_xml(str(path))  # does not raise


def test_looks_like_valid_config_xml_rejects_empty_file(tmp_path):
    path = tmp_path / "config.xml"
    path.write_bytes(b"")

    with pytest.raises(RuntimeError, match="empty"):
        _looks_like_valid_config_xml(str(path))


def test_looks_like_valid_config_xml_rejects_non_xml(tmp_path):
    path = tmp_path / "config.xml"
    path.write_bytes(b"<html>not a config</html>")

    with pytest.raises(RuntimeError, match="does not look like valid XML"):
        _looks_like_valid_config_xml(str(path))
