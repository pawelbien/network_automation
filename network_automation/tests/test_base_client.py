# network_automation/tests/test_base_client.py

from unittest.mock import MagicMock

from network_automation.base_client import BaseClient


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
