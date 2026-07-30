# network_automation/platforms/cisco_ios/client.py

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.cisco_ios.backup import run_backup
from network_automation.platforms.cisco_ios.info import read_info


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
        """Not implemented yet."""
        raise NotImplementedError("CiscoIOS.reboot() is not implemented yet.")

    def wait_for_reconnect(self):
        """Not implemented yet."""
        raise NotImplementedError("CiscoIOS.wait_for_reconnect() is not implemented yet.")

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
