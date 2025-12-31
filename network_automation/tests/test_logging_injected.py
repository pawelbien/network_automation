# network_automation/tests/test_logging_injected.py

from network_automation.factory import get_client

class FakeJobLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("INFO", msg))

    def debug(self, msg):
        self.messages.append(("DEBUG", msg))

    def warning(self, msg):
        self.messages.append(("WARNING", msg))

    def error(self, msg):
        self.messages.append(("ERROR", msg))


def test_client_uses_injected_logger():
    fake_logger = FakeJobLogger()

    client = get_client(
        device_type="mikrotik_routeros",
        logger=fake_logger,
        host="1.2.3.4",
        firmware_version="7.15",
        username="user",
        password="pass",
    )

    client.logger.info("hello from job")

    assert ("INFO", "hello from job") in fake_logger.messages
