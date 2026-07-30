# network_automation/tests/cisco_ios/test_backup.py

from unittest.mock import MagicMock

from network_automation.results import OperationResult


def test_backup_returns_result_and_writes_file(monkeypatch, cisco_client, tmp_path):
    monkeypatch.setattr(cisco_client, "connect", lambda: None)
    monkeypatch.setattr(cisco_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "hostname Switch\n!\nend"
    cisco_client.conn = fake_conn

    result = cisco_client.backup(
        "test-backup",
        return_result=True,
        download_dir=str(tmp_path),
    )

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "backup"

    local_path = tmp_path / "test-backup.cfg"
    assert result.metadata["local_path"] == str(local_path)
    assert local_path.read_text() == "hostname Switch\n!\nend"

    fake_conn.send_command.assert_called_once_with("show running-config")


def test_backup_default_return(monkeypatch, cisco_client, tmp_path):
    monkeypatch.setattr(cisco_client, "connect", lambda: None)
    monkeypatch.setattr(cisco_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "hostname Switch\n!\nend"
    cisco_client.conn = fake_conn

    result = cisco_client.backup("test-backup", download_dir=str(tmp_path))

    assert result is None
    assert (tmp_path / "test-backup.cfg").exists()
