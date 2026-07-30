# network_automation/platforms/cisco_ios/client.py

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.cisco_ios.backup import run_backup
from network_automation.platforms.cisco_ios.info import read_info
from network_automation.platforms.cisco_ios.reboot import reboot as reboot_helper
from network_automation.platforms.cisco_ios.reboot import wait_for_reconnect as wait_for_reconnect_helper


class CiscoIOS(BaseClient):
    """
    Platform client for Cisco IOS/IOS-XE devices.
    """

    def __init__(
        self,
        host,
        username,
        password: str | None = None,
        key_file: str | None = None,
        passphrase: str | None = None,
        use_keys: bool = False,
        port=22,
        connect_retries=2,
        connect_delay=2,
        reconnect_timeout=300,
        reconnect_delay=10,
        disabled_algorithms: dict | None = None,
        *,
        context: ExecutionContext | None = None,
    ):
        super().__init__(
            context=context,
            connect_retries=connect_retries,
            connect_delay=connect_delay,
        )

        self.device = {
            "device_type": "cisco_ios",
            "host": host,
            "username": username,
            "password": password,
            "key_file": key_file,
            "passphrase": passphrase,
            "use_keys": use_keys,
            "port": port,
            "disabled_algorithms": disabled_algorithms,
        }

        self.host = host
        self.username = username
        self.current_version = None

        self.reconnect_timeout = reconnect_timeout
        self.reconnect_delay = reconnect_delay

    # -------------------------------------------------------
    # System info
    # -------------------------------------------------------

    def get_info(self, *, return_result: bool = False):
        """Read device info and populate current_version on the client."""
        return read_info(self, return_result=return_result)

    # -------------------------------------------------------
    # Reboot & reconnect
    # -------------------------------------------------------

    def reboot(self):
        """Reload the device."""
        return reboot_helper(self)

    def wait_for_reconnect(self):
        """Wait until the device is reachable via SSH again."""
        return wait_for_reconnect_helper(self)

    # -------------------------------------------------------
    # Upgrade
    # -------------------------------------------------------

    def upgrade(self, *, return_result: bool = False):
        """Not implemented yet."""
        raise NotImplementedError("CiscoIOS.upgrade() is not implemented yet.")

    # -------------------------------------------------------
    # Backup
    # -------------------------------------------------------

    def backup(self, name: str, *, return_result: bool = False, download_dir: str = "."):
        """Capture running-config and write it to download_dir."""
        return run_backup(self, name, return_result=return_result, download_dir=download_dir)
