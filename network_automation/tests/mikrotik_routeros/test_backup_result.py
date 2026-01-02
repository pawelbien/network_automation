# network_automation/tests/mikrotik_routeros/test_backup_result.py

from network_automation.results import OperationResult

def test_backup_returns_result(monkeypatch, updater, tmp_path):
    monkeypatch.setattr(
        updater,
        "connect",
        lambda: None,
    )

    monkeypatch.setattr(
        updater,
        "disconnect",
        lambda: None,
    )

    monkeypatch.setattr(
        updater.conn if updater.conn else updater,
        "conn",
        type(
            "FakeConn",
            (),
            {
                "send_command": lambda *a, **k: "",
                "file_transfer": lambda *a, **k: None,
            },
        )(),
    )

    result = updater.backup(
        "test_backup",
        return_result=True,
        download_dir=str(tmp_path),
    )

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "backup"
    assert "local_path" in result.metadata
