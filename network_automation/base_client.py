# network_automation/base_client.py

import logging
import time
from network_automation.context import ExecutionContext
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException


class BaseClient:
    """
    BaseClient provides common connection handling and logging.

    Platform-specific clients should inherit from this class
    and provide platform-specific attributes (e.g. self.device).
    """

    def __init__(
        self,
        *,
        context: ExecutionContext | None = None,
        connect_retries: int = 1,
        connect_delay: int = 1,
    ):
        # Execution context (always present)
        self.context = context or ExecutionContext()

        # Logger resolved from execution context
        self.logger = self.context.logger or logging.getLogger(__name__)

        # Connection retry configuration
        self.connect_retries = connect_retries
        self.connect_delay = connect_delay

        # Netmiko connection handle
        self.conn = None

    # -------------------------------------------------------
    # Connection handling (shared)
    # -------------------------------------------------------

    def connect(self):
        """
        Establish a Netmiko connection with retry logic.

        Expects subclass to define:
          - self.device (Netmiko connection parameters)
        """
        attempt = 1

        while attempt <= self.connect_retries:
            self.logger.info(
                f"Connecting to device (attempt {attempt}/{self.connect_retries})..."
            )

            try:
                self.conn = ConnectHandler(**self.device)
                self.logger.info("Connected successfully.")
                return

            except NetmikoTimeoutException:
                self.logger.warning("Connection timeout. Device may be offline.")

            except NetmikoAuthenticationException:
                self.logger.error("Authentication failed.")
                raise

            except Exception as exc:
                self.logger.error(f"Unexpected connection error: {exc}")

            if attempt < self.connect_retries:
                self.logger.info(
                    f"Retrying in {self.connect_delay} seconds..."
                )
                time.sleep(self.connect_delay)

            attempt += 1

        raise NetmikoTimeoutException(
            f"Unable to connect after {self.connect_retries} attempts."
        )

    def disconnect(self):
        """Close Netmiko connection if open."""
        if self.conn:
            try:
                self.conn.disconnect()
            except Exception:
                pass
            self.conn = None
