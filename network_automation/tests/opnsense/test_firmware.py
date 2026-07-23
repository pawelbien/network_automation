# network_automation/tests/opnsense/test_firmware.py

from unittest.mock import MagicMock

from network_automation.context import ExecutionContext
from network_automation.platforms.opnsense import firmware


def _client_with_response(response):
    client = MagicMock()
    client.conn.send_command.return_value = response
    client.context = None
    return client


def test_check_sends_expected_command():
    client = _client_with_response(" OK ")
    assert firmware.check(client) == "OK"
    client.conn.send_command.assert_called_once_with("configctl firmware check")


def test_update_sends_expected_command():
    client = _client_with_response(" OK ")
    assert firmware.update(client) == "OK"
    client.conn.send_command.assert_called_once_with("configctl firmware update")


def test_upgrade_sends_expected_command():
    client = _client_with_response(" OK ")
    assert firmware.upgrade(client) == "OK"
    client.conn.send_command.assert_called_once_with("configctl firmware upgrade")


def test_running_strips_and_returns_state():
    client = _client_with_response(" busy \n")
    assert firmware.running(client) == "busy"
    client.conn.send_command.assert_called_once_with("configctl firmware running")


def test_status_returns_raw_log_unstripped():
    log = "***GOT REQUEST FOR CHECK***\nCurrently running ...\n***DONE***\n"
    client = _client_with_response(log)
    assert firmware.status(client) == log
    client.conn.send_command.assert_called_once_with("configctl firmware status")


def test_last_log_returns_raw_persisted_log():
    log = "***GOT REQUEST FOR CHECK***\n...\n***DONE***\n"
    client = _client_with_response(log)
    assert firmware.last_log(client) == log
    client.conn.send_command.assert_called_once_with("configctl firmware log show")


def test_last_log_empty_when_no_operation_has_run():
    client = _client_with_response("")
    assert firmware.last_log(client) == ""


def test_send_logs_at_debug_when_enabled():
    client = _client_with_response("ready")
    client.context = ExecutionContext(debug_log=True)

    firmware.running(client)

    assert client.logger.debug.call_count == 2
    first_call, second_call = client.logger.debug.call_args_list
    assert "configctl firmware running" in first_call.args
    assert "ready" in second_call.args


def test_send_does_not_log_at_debug_when_disabled():
    client = _client_with_response("ready")
    client.context = ExecutionContext(debug_log=False)

    firmware.running(client)

    client.logger.debug.assert_not_called()
