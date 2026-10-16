# network_automation/tests/test_base_client.py

import pytest
from unittest.mock import MagicMock

from network_automation.base_client import BaseClient, _classify_connect_failure
from netmiko import NetmikoTimeoutException, NetmikoAuthenticationException
from paramiko.ssh_exception import SSHException


def test_safe_log_info_swallows_logger_exception():
    # Nautobot's Job logger runs a DB query on every emit() with no
    # try/except of its own (confirmed live, 2026-07-12): a transient
    # OperationalError there must never propagate out of a status/
    # heartbeat log call. Shared by every platform client via BaseClient.
    client = BaseClient()
    client.logger = MagicMock()
    client.logger.info.side_effect = RuntimeError(
        "Lost connection to MySQL server during query"
    )

    client._safe_log_info("Still waiting for %s to reconnect (%ds elapsed)", "1.1.1.1", 65)  # must not raise

    client.logger.info.assert_called_once_with(
        "Still waiting for %s to reconnect (%ds elapsed)", "1.1.1.1", 65,
    )


def test_safe_log_info_calls_through_on_success():
    client = BaseClient()
    client.logger = MagicMock()

    client._safe_log_info("Device fully online (SSH + CLI ready).")

    client.logger.info.assert_called_once_with("Device fully online (SSH + CLI ready).")


# ---------------------------------------------------------------------------
# _classify_connect_failure
# ---------------------------------------------------------------------------

def test_classify_connect_failure_reset_via_context():
    outer = NetmikoTimeoutException("Unable to connect to port 22")
    outer.__context__ = ConnectionResetError("Connection reset by peer")

    result = _classify_connect_failure(outer)

    assert "reset by peer" in result.lower()
    assert "responded" in result.lower()


def test_classify_connect_failure_refused_via_context():
    outer = NetmikoTimeoutException("Unable to connect")
    outer.__context__ = ConnectionRefusedError("Connection refused")

    result = _classify_connect_failure(outer)

    assert "refused" in result.lower()


def test_classify_connect_failure_matches_on_message_text_too():
    # The reset can show up as plain text inside an SSHException message,
    # not as a ConnectionResetError instance.
    exc = NetmikoTimeoutException(
        "Error reading SSH protocol banner[Errno 54] Connection reset by peer"
    )

    result = _classify_connect_failure(exc)

    assert "reset by peer" in result.lower()


def test_classify_connect_failure_walks_multiple_chain_levels():
    inner = ConnectionResetError("Connection reset by peer")
    middle = Exception("wrapped")
    middle.__cause__ = inner
    outer = NetmikoTimeoutException("Unable to connect")
    outer.__context__ = middle

    result = _classify_connect_failure(outer)

    assert "reset by peer" in result.lower()


def test_classify_connect_failure_falls_back_to_offline_wording():
    exc = NetmikoTimeoutException("Unable to connect after 2 attempts.")

    result = _classify_connect_failure(exc)

    assert result == "Connection timeout. Device may be offline."


def test_classify_connect_failure_generic_sshexception_invalid_key():
    # A rejected pubkey signature algorithm surfaces as Netmiko wrapping a
    # bare SSHException("Invalid key") - not Connection*Error - and must
    # not fall through to the generic "may be offline" wording.
    outer = NetmikoTimeoutException(
        "A paramiko SSHException occurred during connection creation: Invalid key"
    )
    outer.__context__ = SSHException("Invalid key")

    result = _classify_connect_failure(outer)

    assert "invalid key" in result.lower()
    assert "disabled_algorithms" in result.lower()


def test_classify_connect_failure_prioritizes_reset_text_over_generic_sshexception():
    # "Error reading SSH protocol banner...Connection reset by peer" is
    # itself raised by paramiko as a bare SSHException - the reset-specific
    # wording must still win over the generic SSHException branch, since
    # it's more precise about what actually happened.
    exc = SSHException("Error reading SSH protocol banner[Errno 54] Connection reset by peer")

    result = _classify_connect_failure(exc)

    assert "reset by peer" in result.lower()
    assert "invalid key" not in result.lower()


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

def test_connect_final_exception_reflects_reset_classification(monkeypatch):
    reset_exc = NetmikoTimeoutException("banner error")
    reset_exc.__context__ = ConnectionResetError("Connection reset by peer")

    monkeypatch.setattr(
        "network_automation.base_client.ConnectHandler",
        MagicMock(side_effect=reset_exc),
    )

    client = BaseClient(connect_retries=1, connect_delay=0)
    client.logger = MagicMock()
    client.device = {}

    with pytest.raises(NetmikoTimeoutException) as exc_info:
        client.connect()

    assert "reset by peer" in str(exc_info.value).lower()
    assert exc_info.value.__cause__ is reset_exc


def test_connect_final_exception_preserves_offline_wording_for_genuine_timeout(monkeypatch):
    timeout_exc = NetmikoTimeoutException("Unable to connect to port 22 on 1.2.3.4")

    monkeypatch.setattr(
        "network_automation.base_client.ConnectHandler",
        MagicMock(side_effect=timeout_exc),
    )

    client = BaseClient(connect_retries=1, connect_delay=0)
    client.logger = MagicMock()
    client.device = {}

    with pytest.raises(NetmikoTimeoutException) as exc_info:
        client.connect()

    assert "may be offline" in str(exc_info.value).lower()
    assert exc_info.value.__cause__ is timeout_exc


def test_connect_final_exception_stays_single_reason_when_attempts_agree(monkeypatch):
    timeout_exc = NetmikoTimeoutException("Unable to connect to port 22")

    monkeypatch.setattr(
        "network_automation.base_client.ConnectHandler",
        MagicMock(side_effect=timeout_exc),
    )

    client = BaseClient(connect_retries=2, connect_delay=0)
    client.logger = MagicMock()
    client.device = {}

    with pytest.raises(NetmikoTimeoutException) as exc_info:
        client.connect()

    message = str(exc_info.value).lower()
    assert "attempt 1" not in message
    assert "attempt 2" not in message
    assert message.count("may be offline") == 1


def test_connect_final_exception_includes_all_distinct_attempt_reasons(monkeypatch):
    # Different attempts can fail for different reasons (e.g. a rejected
    # pubkey algorithm on attempt 1, a connection reset on attempt 2) - the
    # final exception must surface all distinct reasons, not just the
    # last attempt's.
    invalid_key_exc = NetmikoTimeoutException(
        "A paramiko SSHException occurred during connection creation: Invalid key"
    )
    invalid_key_exc.__context__ = SSHException("Invalid key")

    reset_exc = NetmikoTimeoutException("banner error")
    reset_exc.__context__ = ConnectionResetError("Connection reset by peer")

    monkeypatch.setattr(
        "network_automation.base_client.ConnectHandler",
        MagicMock(side_effect=[invalid_key_exc, reset_exc]),
    )

    client = BaseClient(connect_retries=2, connect_delay=0)
    client.logger = MagicMock()
    client.device = {}

    with pytest.raises(NetmikoTimeoutException) as exc_info:
        client.connect()

    message = str(exc_info.value).lower()
    assert "invalid key" in message
    assert "reset by peer" in message
    assert "attempt 1" in message
    assert "attempt 2" in message
    assert exc_info.value.__cause__ is reset_exc

    logged_warnings = [
        call.args[0] for call in client.logger.warning.call_args_list
    ]
    assert any("invalid key" in msg.lower() for msg in logged_warnings)
    assert any("reset by peer" in msg.lower() for msg in logged_warnings)


def test_connect_still_raises_authentication_exception_directly(monkeypatch):
    auth_exc = NetmikoAuthenticationException("bad credentials")

    monkeypatch.setattr(
        "network_automation.base_client.ConnectHandler",
        MagicMock(side_effect=auth_exc),
    )

    client = BaseClient(connect_retries=2, connect_delay=0)
    client.logger = MagicMock()
    client.device = {}

    with pytest.raises(NetmikoAuthenticationException):
        client.connect()


def test_connect_succeeds_without_touching_classification(monkeypatch):
    monkeypatch.setattr(
        "network_automation.base_client.ConnectHandler",
        MagicMock(return_value=MagicMock()),
    )

    client = BaseClient(connect_retries=2, connect_delay=0)
    client.logger = MagicMock()
    client.device = {}

    client.connect()

    assert client.conn is not None
