# network_automation/platforms/mikrotik_routeros/client.py

import time
from netmiko import ConnectHandler
from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.mikrotik_routeros.backup import run_backup
from network_automation.platforms.mikrotik_routeros.info import get_info
from network_automation.platforms.mikrotik_routeros.run import run as run_helper
from network_automation.platforms.mikrotik_routeros.upgrade import upgrade as upgrade_helper


class MikrotikRouterOS(BaseClient):
    """
    Platform client for MikroTik RouterOS devices.
    """

    def __init__(
        self,
        host,
        username,
        firmware_version: str | None = None,
        password: str | None = None,
        key_file: str | None = None,
        passphrase: str | None = None,
        use_keys: bool = False,
        repo_url="https://download.mikrotik.com/routeros",
        port=22,
        connect_retries=2,
        connect_delay=2,
        reconnect_timeout=300,
        reconnect_delay=10,
        log_file=None,  # deprecated, kept for backward compatibility
        *,
        context: ExecutionContext | None = None,
    ):
        # Initialize shared BaseClient state (context, logger, retry config)
        super().__init__(
            context=context,
            connect_retries=connect_retries,
            connect_delay=connect_delay,
        )

        # Legacy parameter kept for backward compatibility
        if log_file:
            self.logger.debug(
                "Parameter 'log_file' is deprecated and ignored. "
                "Logging must be configured by the caller."
            )

        # Netmiko connection parameters (platform-specific)
        self.device = {
            "device_type": "mikrotik_routeros",
            "host": host,
            "username": username,
            "password": password,
            "key_file": key_file,
            "passphrase": passphrase,
            "use_keys": use_keys,
            "port": port,
        }

        # Device and workflow metadata
        self.host = host
        self.username = username
        self.version = firmware_version
        self.repo_url = repo_url.rstrip("/")

        # Reconnect-after-reboot configuration
        self.reconnect_timeout = reconnect_timeout
        self.reconnect_delay = reconnect_delay

        # Runtime state
        self.arch = None
        self.current_version = None
        self.firmware_file = None

    # -------------------------------------------------------
    # System info
    # -------------------------------------------------------

    def get_info(self):
        """Read device architecture and RouterOS version."""
        arch, version = get_info(self)
        self.arch = arch
        self.current_version = version

        self.logger.info(f"Architecture: {self.arch}")
        self.logger.info(f"Current version: {self.current_version}")

    # -------------------------------------------------------
    # Backup
    # -------------------------------------------------------

    def backup(
        self,
        name: str,
        *,
        return_result: bool = False,
        download_dir: str = ".",
    ):
        return run_backup(
            self,
            name,
            return_result=return_result,
            download_dir=download_dir,
        )

    # -------------------------------------------------------
    # Reboot & reconnect
    # -------------------------------------------------------

    def reboot(self):
        """Perform a stable reboot for RouterOS 7.x."""
        self.logger.info("Rebooting device...")

        out = self.conn.send_command_timing("/system reboot")

        if "[y/n" in out.lower():
            self.conn.send_command_timing("y")
        else:
            time.sleep(0.3)
            out2 = self.conn.send_command_timing("")
            if "[y/n" in out2.lower():
                self.conn.send_command_timing("y")
            else:
                self.logger.warning(
                    "Reboot prompt not detected — sending 'y' anyway."
                )
                self.conn.send_command_timing("y")

        # SSH connection is closed immediately after reboot
        try:
            self.conn.disconnect()
        except Exception:
            pass

        self.conn = None

    def wait_for_reconnect(self):
        """Wait until RouterOS is reachable via SSH and CLI is ready."""
        self.logger.info(f"Waiting for {self.host} to reconnect...")

        start = time.time()

        while True:
            if time.time() - start > self.reconnect_timeout:
                raise TimeoutError(
                    f"Device did not reconnect within {self.reconnect_timeout} seconds."
                )

            conn = None
            try:
                conn = ConnectHandler(**self.device)

                # Give RouterOS a moment to finish CLI initialization
                time.sleep(1.0)

                out = conn.send_command(
                    "/system resource print",
                    delay_factor=2,
                )

                if "version" in out.lower():
                    self.logger.info(
                        "Device fully online (SSH + CLI ready)."
                    )
                    self.conn = conn
                    return conn

            except Exception:
                pass

            if conn:
                try:
                    conn.disconnect()
                except Exception:
                    pass

            time.sleep(self.reconnect_delay)

    # -------------------------------------------------------
    # Final version check
    # -------------------------------------------------------

    def check_version(self):
        """Check RouterOS version after reboot."""
        self.get_info()
        self.logger.info(
            f"Version after reboot: {self.current_version}"
        )
        return self.current_version

    # -------------------------------------------------------
    # Main upgrade workflow
    # -------------------------------------------------------

    def upgrade(self, *, return_result: bool = False):
        return upgrade_helper(self, return_result=return_result)

    # -------------------------------------------------------
    # Run arbitrary commands
    # -------------------------------------------------------

    def run(self, commands, *, return_result: bool = False):
        return run_helper(
            self,
            commands,
            return_result=return_result,
        )

