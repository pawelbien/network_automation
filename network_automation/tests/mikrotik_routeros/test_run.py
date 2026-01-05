# network_automation/tests/mikrotik_routeros/test_run.py

from unittest.mock import MagicMock
from network_automation.results import OperationResult


def test_run_single_command_returns_output(monkeypatch, mikrotik_client):
    # ---- lifecycle mocks ----
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    # ---- fake connection ----
    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "OK"

    mikrotik_client.conn = fake_conn

    # ---- run command ----
    result = mikrotik_client.run(
        "/system resource print",
        return_result=True,
    )

    # ---- assertions ----
    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "run"

    assert result.metadata["output"] == [
        {
            "command": "/system resource print",
            "output": "OK",
        }
    ]

    fake_conn.send_command.assert_called_once_with(
        "/system resource print"
    )


def test_run_multiple_commands(monkeypatch, mikrotik_client):
    # ---- lifecycle mocks ----
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    # ---- fake connection ----
    fake_conn = MagicMock()
    fake_conn.send_command.side_effect = [
        "OUT1",
        "OUT2",
    ]

    mikrotik_client.conn = fake_conn

    # ---- run commands ----
    outputs = mikrotik_client.run(
        [
            "/ip address print",
            "/interface print",
        ],
        return_result=False,
    )

    # ---- assertions ----
    assert outputs == [
        {
            "command": "/ip address print",
            "output": "OUT1",
        },
        {
            "command": "/interface print",
            "output": "OUT2",
        },
    ]

    assert fake_conn.send_command.call_count == 2
