# network_automation/platforms/opnsense/client.py

import re

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.opnsense.debug_log import debug_log
from network_automation.platforms.opnsense.exceptions import OPNsenseShellError
from network_automation.platforms.opnsense.info import read_info
from network_automation.platforms.opnsense.upgrade import (
    check_updates as check_updates_workflow,
    update as update_workflow,
    upgrade as upgrade_workflow,
)
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
        firmware_poll_interval: int = 15,
        firmware_poll_timeout: int = 3600,
        reboot_grace_period: int = 15,
        reconnect_timeout: int = 300,
        reconnect_delay: int = 10,
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
        firmware_poll_interval — seconds between configctl firmware
                             running()/status() polls during update()/
                             upgrade()/check_updates() (default 15).
        firmware_poll_timeout — max seconds to wait for the firmware
                             backend to report "ready" before raising
                             OPNsenseFirmwareError (default 3600 - base/
                             kernel updates can run well past 10-30
                             minutes on slow hardware).
        reboot_grace_period — seconds to wait after a ***REBOOT*** marker
                             is seen before starting reconnect attempts
                             (default 15). The backend writes the marker,
                             then `sleep 5`, then actually reboots - a
                             shorter grace period risks reconnecting to
                             the still-alive, about-to-die session and
                             mistaking it for the device being back up.
        reconnect_timeout   — seconds to wait for SSH after a reboot before
                             raising TimeoutError (default 300).
        reconnect_delay     — polling interval in seconds during reconnect
                             wait (default 10).
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

        # Firmware operation polling
        self.firmware_poll_interval = firmware_poll_interval
        self.firmware_poll_timeout = firmware_poll_timeout
        self.reboot_grace_period = reboot_grace_period

        # Reconnect-after-reboot configuration
        self.reconnect_timeout = reconnect_timeout
        self.reconnect_delay = reconnect_delay

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

        debug_log(self, "send_command_timing: %s", self.shell_menu_option)
        output = self.conn.send_command_timing(self.shell_menu_option)
        debug_log(self, "send_command_timing response: %s", output)

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
    # Firmware update / upgrade
    # -------------------------------------------------------

    def check_updates(self, *, return_result: bool = False):
        """
        Check for available updates (`configctl firmware check`).
        Read-only - never reboots, never modifies the device.
        """
        return check_updates_workflow(self, return_result=return_result)

    def update(self, *, return_result: bool = False):
        """
        Update within the device's current release branch
        (`configctl firmware update`). Reboots only if the backend
        decided a base/kernel update required one.
        """
        return update_workflow(self, return_result=return_result)

    def upgrade(self, *, return_result: bool = False):
        """
        Migrate the device to a new OPNsense release branch
        (`configctl firmware upgrade`). Reboots only if the backend
        decided one is required. Does NOT run update() first - call it
        explicitly beforehand if the device isn't up to date on its
        current branch.
        """
        return upgrade_workflow(self, return_result=return_result)
