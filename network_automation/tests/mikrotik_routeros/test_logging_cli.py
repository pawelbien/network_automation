import logging
from network_automation.factory import get_client

def test_client_uses_default_logger(caplog):
    caplog.set_level(logging.INFO)

    client = get_client(
        device_type="mikrotik_routeros",
        host="1.2.3.4",
        firmware_version="7.15",
        username="user",
        password="pass",
    )

    # We do NOT actually connect; just trigger a log line
    client.logger.info("test log message")

    assert any(
        "test log message" in record.message
        for record in caplog.records
    )
