# network_automation/tests/huawei_vrp/test_run.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.cli_errors import CLIError
from network_automation.results import OperationResult


def test_run_single_command_returns_output(monkeypatch, huawei_client):
    # ---- lifecycle mocks ----
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    # ---- fake connection ----
    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "OK"

    huawei_client.conn = fake_conn

    # ---- run command ----
    result = huawei_client.run(
        "display version",
        return_result=True,
    )

    # ---- assertions ----
    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "run"

    assert result.metadata["output"] == [
        {
            "command": "display version",
            "output": "OK",
        }
    ]

    fake_conn.send_command.assert_called_once_with(
        "display version"
    )


def test_run_multiple_commands(monkeypatch, huawei_client):
    # ---- lifecycle mocks ----
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    # ---- fake connection ----
    fake_conn = MagicMock()
    fake_conn.send_command.side_effect = [
        "OUT1",
        "OUT2",
    ]

    huawei_client.conn = fake_conn

    # ---- run commands ----
    outputs = huawei_client.run(
        [
            "display ip interface brief",
            "display version",
        ],
        return_result=False,
    )

    # ---- assertions ----
    assert outputs == [
        {
            "command": "display ip interface brief",
            "output": "OUT1",
        },
        {
            "command": "display version",
            "output": "OUT2",
        },
    ]

    assert fake_conn.send_command.call_count == 2


def test_run_raises_cli_error_and_does_not_reach_output_list(monkeypatch, huawei_client):
    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "% Unrecognized command"
    huawei_client.conn = fake_conn

    with pytest.raises(CLIError):
        huawei_client.run("display bogus", return_result=False)
