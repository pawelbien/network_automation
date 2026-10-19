# network_automation/tests/juniper_junos/test_backup.py

from unittest.mock import MagicMock

from network_automation.results import OperationResult

_CONFIG = "set system host-name r1\nset interfaces lo0 unit 0 family inet address 10.0.0.1/32"


def test_backup_returns_result_and_writes_file(monkeypatch, juniper_junos_client, tmp_path):
    monkeypatch.setattr(juniper_junos_client, "connect", lambda: None)
    monkeypatch.setattr(juniper_junos_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.return_value = _CONFIG
    juniper_junos_client.conn = fake_conn

    result = juniper_junos_client.backup(
        "test-backup",
        return_result=True,
        download_dir=str(tmp_path),
    )

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "backup"

    local_path = tmp_path / "test-backup.cfg"
    assert result.metadata["local_path"] == str(local_path)
    assert local_path.read_text() == _CONFIG

    fake_conn.send_command.assert_called_once_with("show configuration | display set")


def test_backup_default_return(monkeypatch, juniper_junos_client, tmp_path):
    monkeypatch.setattr(juniper_junos_client, "connect", lambda: None)
    monkeypatch.setattr(juniper_junos_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.return_value = _CONFIG
    juniper_junos_client.conn = fake_conn

    result = juniper_junos_client.backup("test-backup", download_dir=str(tmp_path))

    assert result is None
    assert (tmp_path / "test-backup.cfg").exists()
