# network_automation/platforms/opnsense/client.py

import re

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.opnsense.exceptions import OPNsenseShellError
from network_automation.platforms.opnsense.info import read_info
from network_automation.platforms.opnsense.upgrade import upgrade as upgrade_workflow
from network_automation.platforms.opnsense.reboot import (
    reboot as reboot_workflow,
    wait_for_reconnect as wait_for_reconnect_workflow,
)
from network_automation.platforms.opnsense.backup import run_backup


class OPNsense(BaseClient):
    """
    Platform client for OPNsense devices (SSH/CLI via Netmiko).
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
        connect_retries=1,
        connect_delay=1,
        skip_menu: bool = True,
        shell_menu_option: str = "8",
        disabled_algorithms: dict | None = None,
        *,
        context: ExecutionContext | None = None,
    ):
        """
        skip_menu          — OPNsense's SSH console normally shows a numbered
                             menu ("0) Logout" ... "8) Shell") instead of a
                             shell prompt. True (default) assumes the SSH
                             account already lands directly in a shell (e.g.
                             a dedicated automation user with /bin/sh as its
                             login shell). Set False for accounts that still
                             see the console menu - the client will then
                             select shell_menu_option to reach a shell prompt
                             before running any command.
        shell_menu_option   — console menu option that selects "Shell"
                             (default "8", OPNsense's default numbering).
                             Only used when skip_menu=False.
        disabled_algorithms — passed directly to Paramiko; use to re-enable
                             legacy algorithms on older devices that don't
                             support modern SSH pubkey signature algorithms.
        """
        # Initialize shared BaseClient state (context, logger, retry config)
        super().__init__(
            context=context,
            connect_retries=connect_retries,
            connect_delay=connect_delay,
        )

        # Netmiko connection parameters (platform-specific).
        # No native Netmiko driver exists for OPNsense's console; the
        # generic terminal-server driver is used because it does not
        # assert a specific prompt pattern during session_preparation -
        # required to safely handle both the numbered console menu and a
        # direct shell prompt.
        self.device = {
            "device_type": "generic_termserver_ssh",
            "host": host,
            "username": username,
            "password": password,
            "key_file": key_file,
            "passphrase": passphrase,
            "use_keys": use_keys,
            "port": port,
            "disabled_algorithms": disabled_algorithms,
        }

        # Device metadata
        self.host = host
        self.username = username
        self.skip_menu = skip_menu
        self.shell_menu_option = shell_menu_option

        # Runtime state, populated by get_info()
        self.hostname = None
        self.opnsense_version = None

    # -------------------------------------------------------
    # Console menu handling
    # -------------------------------------------------------

    def _ensure_shell(self):
        """
        Make sure the SSH session is at a FreeBSD shell prompt rather than
        OPNsense's numbered console menu.

        No-op when skip_menu=True. Otherwise selects shell_menu_option and
        raises OPNsenseShellError if the resulting output doesn't look like
        a shell prompt.
        """
        if self.skip_menu:
            return

        self.logger.info("Selecting shell from OPNsense console menu...")

        output = self.conn.send_command_timing(self.shell_menu_option)

        if not re.search(r"[#$]\s*$", output):
            raise OPNsenseShellError(
                "Did not observe a shell prompt after selecting menu "
                f"option {self.shell_menu_option!r}. Output: {output!r}"
            )

    # -------------------------------------------------------
    # System info
    # -------------------------------------------------------

    def get_info(self, *, return_result: bool = False):
        """Read device info (hostname, OPNsense/FreeBSD version, uptime)."""
        return read_info(self, return_result=return_result)

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
        """Create a configuration backup and download it to download_dir."""
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
        """Reboot the device."""
        return reboot_workflow(self)

    def wait_for_reconnect(self):
        """Wait until the device is reachable via SSH again after a reboot."""
        return wait_for_reconnect_workflow(self)

    # -------------------------------------------------------
    # Upgrade
    # -------------------------------------------------------

    def upgrade(self, *, return_result: bool = False):
        """Run the full firmware/version upgrade workflow."""
        return upgrade_workflow(self, return_result=return_result)
