# network_automation/platforms/mikrotik_routeros/client.py

import time
from netmiko import ConnectHandler
from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.mikrotik_routeros.backup import run_backup
from network_automation.platforms.mikrotik_routeros.download import run_download
from network_automation.platforms.mikrotik_routeros.info import read_info
from network_automation.platforms.mikrotik_routeros.run import run as run_helper
from network_automation.platforms.mikrotik_routeros.upgrade import upgrade as upgrade_helper
from network_automation.platforms.mikrotik_routeros.bootloader import bootloader_upgrade
from network_automation.platforms.mikrotik_routeros.upload import run_upload


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
        firmware_delivery: str | None = None,
        repo_path: str | None = None,
        repo_url="https://download.mikrotik.com/routeros",
        port=22,
        connect_retries=2,
        connect_delay=2,
        reconnect_timeout=300,
        reconnect_delay=10,
        *,
        context: ExecutionContext | None = None,
    ):
        """
        firmware_version   — target version string used by upgrade(); e.g. "7.14".
        firmware_delivery  — how firmware reaches the device: "download" (device
                             fetches from repo_url) or "upload" (host pushes from
                             repo_path).
        repo_url           — base URL for "download" delivery; version and filename
                             are appended automatically.
        repo_path          — local directory root for "upload" delivery; expected
                             layout: <repo_path>/<version>/<filename>.npk.
        reconnect_timeout  — seconds to wait for SSH after reboot before raising
                             TimeoutError (default 300).
        reconnect_delay    — polling interval in seconds during reconnect wait
                             (default 10).
        """
        # Initialize shared BaseClient state (context, logger, retry config)
        super().__init__(
            context=context,
            connect_retries=connect_retries,
            connect_delay=connect_delay,
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
        self.firmware_delivery = firmware_delivery
        self.repo_path = repo_path
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

    def get_info(self, *, return_result: bool = False):
        """Read device info and populate arch/current_version on the client."""
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
        """Create a .backup file on the device and download it to download_dir."""
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
        """
        Wait until RouterOS is reachable via SSH and CLI is ready.

        All status/heartbeat logging here goes through
        BaseClient._safe_log_info() (best-effort, never raises) — a logger
        failure must never abort a reconnect wait that is itself
        succeeding. See that method's docstring for why (huawei_vrp hit
        this live first; identical risk here).
        """

        self._safe_log_info(
            "Waiting for %s to reconnect...",
            self.host,
        )

        start = time.time()
        last_log = start

        while True:
            elapsed = time.time() - start

            if elapsed > self.reconnect_timeout:
                raise TimeoutError(
                    f"Device did not reconnect within "
                    f"{self.reconnect_timeout} seconds."
                )

            conn = None
            try:
                # ---- attempt SSH connection ----
                conn = ConnectHandler(**self.device)

                # ---- give RouterOS time to initialize CLI ----
                time.sleep(1.0)

                # ---- probe CLI readiness (bounded, must not hang) ----
                out = conn.send_command(
                    "/system resource print",
                    delay_factor=2,
                    read_timeout=10,
                )

                if "version" in out.lower():
                    self._safe_log_info(
                        "Device fully online (SSH + CLI ready)."
                    )
                    self.conn = conn
                    return conn   # SUCCESS → do NOT disconnect

            except Exception:
                # retry silently; heartbeat will indicate progress
                pass

            # ---- cleanup only failed attempt ----
            if conn:
                try:
                    conn.disconnect()
                except Exception:
                    pass

            # ---- heartbeat INFO every 60s ----
            now = time.time()
            if now - last_log > 60:
                self._safe_log_info(
                    "Still waiting for %s to reconnect "
                    "(%ds elapsed)",
                    self.host,
                    int(elapsed),
                )
                last_log = now

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
        """Run full firmware upgrade: provide firmware, reboot, verify version."""
        return upgrade_helper(self, return_result=return_result)

    # -------------------------------------------------------
    # Bootloader upgrade
    # -------------------------------------------------------

    def bootloader_upgrade(self, *, return_result: bool = False):
        """
        Upgrade device bootloader firmware (RouterBOARD).
        This is a separate operation from RouterOS upgrade.
        """
        return bootloader_upgrade(self, return_result=return_result)

    # -------------------------------------------------------
    # Run arbitrary commands
    # -------------------------------------------------------

    def run(self, commands, *, return_result: bool = False):
        """Execute one command (str) or a list of commands on the device."""
        return run_helper(
            self,
            commands,
            return_result=return_result,
        )

    # -------------------------------------------------------
    # File upload
    # -------------------------------------------------------

    def upload(
        self,
        *,
        files: list[str],
        remote_dir: str = "/",
        return_result: bool = False,
    ):
        """
        Upload local files to device via SFTP.
        """
        return run_upload(
            self,
            files=files,
            remote_dir=remote_dir,
            return_result=return_result,
        )

    # -------------------------------------------------------
    # File download
    # -------------------------------------------------------

    def download(
        self,
        *,
        files: list[str],
        local_dir: str,
        return_result: bool = False,
    ):
        """
        Download files from device via SFTP
        """
        return run_download(
            self,
            files=files,
            local_dir=local_dir,
            return_result=return_result,
        )

