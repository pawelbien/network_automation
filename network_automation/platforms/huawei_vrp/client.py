# network_automation/platforms/huawei_vrp/client.py

import time

from netmiko import ConnectHandler

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.huawei_vrp.download import run_download
from network_automation.platforms.huawei_vrp.upload import run_upload
from network_automation.platforms.huawei_vrp.info import read_info
from network_automation.platforms.huawei_vrp.run import run as run_helper
from network_automation.platforms.huawei_vrp.upgrade import upgrade as upgrade_helper


class HuaweiVRP(BaseClient):
    """
    Platform client for Huawei VRP devices (Netmiko driver "huawei").
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
        firmware_version: str | None = None,
        firmware_file: str | None = None,
        reconnect_timeout=300,
        reconnect_delay=10,
        *,
        context: ExecutionContext | None = None,
    ):
        """
        disabled_algorithms — passed directly to Paramiko; use to re-enable
                              legacy algorithms on older Huawei devices that
                              don't support modern SSH key exchange or ciphers.
                              Example: {"kex": ["diffie-hellman-group14-sha1"]}.
        firmware_version    — expected post-upgrade `software_version` string
                              used by upgrade(); e.g. "V300R024C00SPC100".
        firmware_file       — local path to the `.cc` firmware image to upload.
                              Huawei firmware filenames are vendor-arbitrary
                              (unlike Mikrotik's templated names), so the
                              caller must provide the file explicitly.
        reconnect_timeout   — seconds to wait for SSH after reboot before
                              raising TimeoutError (default 300).
        reconnect_delay     — polling interval in seconds during reconnect
                              wait (default 10).
        """
        super().__init__(
            context=context,
            connect_retries=connect_retries,
            connect_delay=connect_delay,
        )

        self.device = {
            "device_type": "huawei",
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
        self.firmware_version = firmware_version
        self.firmware_file = firmware_file
        self.reconnect_timeout = reconnect_timeout
        self.reconnect_delay = reconnect_delay

    def get_info(self, *, return_result: bool = False):
        """Read device info (version, ESN, startup config) for all stack units."""
        return read_info(self, return_result=return_result)

    def run(self, commands, *, return_result: bool = False):
        """Execute one command (str) or a list of commands on the device."""
        return run_helper(
            self,
            commands,
            return_result=return_result,
        )

    def download(
        self,
        *,
        files: list[str],
        local_dir: str,
        return_result: bool = False,
    ):
        """Download files from device via SFTP."""
        return run_download(
            self,
            files=files,
            local_dir=local_dir,
            return_result=return_result,
        )

    def upload(
        self,
        *,
        files: list[str],
        remote_dir: str = "/",
        return_result: bool = False,
    ):
        """Upload local files to device via SFTP."""
        return run_upload(
            self,
            files=files,
            remote_dir=remote_dir,
            return_result=return_result,
        )

    # -------------------------------------------------------
    # Reboot & reconnect
    # -------------------------------------------------------

    def reboot(self):
        """Reboot the device, confirming any interactive [Y/N] prompts."""
        self.logger.info("Rebooting device...")

        output = self.conn.send_command_timing("reboot")

        for _ in range(3):
            if "y/n" not in output.lower():
                break
            output = self.conn.send_command_timing("y")

        try:
            self.conn.disconnect()
        except Exception:
            pass

        self.conn = None

    def wait_for_reconnect(self):
        """Wait until the device is reachable via SSH and CLI is ready."""

        self.logger.info("Waiting for %s to reconnect...", self.host)

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

                # ---- give VRP time to initialize CLI ----
                time.sleep(1.0)

                # ---- probe CLI readiness (bounded, must not hang) ----
                out = conn.send_command(
                    "display version",
                    delay_factor=2,
                    read_timeout=10,
                )

                if "vrp" in out.lower():
                    self.logger.info(
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
                self.logger.info(
                    "Still waiting for %s to reconnect "
                    "(%ds elapsed)",
                    self.host,
                    int(elapsed),
                )
                last_log = now

            time.sleep(self.reconnect_delay)

    # -------------------------------------------------------
    # Firmware upgrade
    # -------------------------------------------------------

    def upgrade(self, *, return_result: bool = False):
        """
        Run the firmware-only upgrade workflow (single-unit devices only).

        See network_automation/platforms/huawei_vrp/upgrade.py for scope
        and limitations.
        """
        return upgrade_helper(self, return_result=return_result)
