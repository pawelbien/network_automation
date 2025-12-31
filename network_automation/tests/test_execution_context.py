#network_automation/tests/test_execution_context.py

from network_automation.context import ExecutionContext
from network_automation.factory import get_client

class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(msg)


def test_context_logger_is_used():
    ctx = ExecutionContext(logger=FakeLogger())

    client = get_client(
        context=ctx,
        device_type="mikrotik_routeros",
        host="1.1.1.1",
        firmware_version="7.15",
        username="user",
        password="pass",
    )

    client.logger.info("hello")

    assert "hello" in ctx.logger.messages
