# network_automation/platforms/huawei_vrp/client.py

import os
import tempfile
import time

from netmiko import ConnectHandler

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.huawei_vrp.download import run_download
from network_automation.platforms.huawei_vrp.upload import run_upload
from network_automation.platforms.huawei_vrp.backup import run_backup
from network_automation.platforms.huawei_vrp.info import read_info, extract_discovery_facts
from network_automation.platforms.huawei_vrp.run import run as run_helper
from network_automation.platforms.huawei_vrp.upgrade import upgrade as upgrade_helper
from network_automation.platforms.huawei_vrp.debug_log import debug_log


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
        keepalive: int = 30,
        disabled_algorithms: dict | None = None,
        firmware_version: str | None = None,
        firmware_file: str | None = None,
        patch_version: str | None = None,
        patch_file: str | None = None,
        reconnect_timeout=300,
        reconnect_delay=10,
        lock_timeout=3600,
        lock_dir: str | None = None,
        force_downgrade: bool = False,
        i_understand_downgrade_risk: bool = False,
        upload_timeout: float = 120,
        upload_retries: int = 3,
        health_check_mode: str = "abort",
        health_check_cpu_threshold: float = 80.0,
        health_check_memory_threshold: float = 80.0,
        health_check_max_down_interfaces: int = 0,
        *,
        context: ExecutionContext | None = None,
    ):
        """
        keepalive           — seconds between SSH-level keepalive packets
                              (default 30; 0 disables). Some VRP operations
                              (e.g. cleanup_flash()'s "startup system-software
                              ... backup" re-pointing step) block silently
                              for several minutes with zero traffic on the
                              wire; without keepalives, a stateful firewall/
                              NAT sitting between here and the device can
                              treat that as an idle connection and reset it
                              mid-operation — verified against a real
                              "Connection reset by peer" during that exact
                              step on a live device.
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
        patch_version       — expected active patch version string used by
                              upgrade(); e.g. "SPH1b0". Optional — omit for a
                              firmware-only upgrade. Must be provided together
                              with patch_file.
        patch_file          — local path to the `.pat` patch package to
                              upload. Must be provided together with
                              patch_version.
        reconnect_timeout   — seconds to wait for SSH after reboot before
                              raising TimeoutError (default 300).
        reconnect_delay     — polling interval in seconds during reconnect
                              wait (default 10).
        lock_timeout        — seconds a device lock must sit unrenewed with
                              a dead holder process before upgrade() may
                              reclaim it as stale (default 3600). A live
                              holder's lock is never reclaimed regardless of
                              age.
        lock_dir            — directory for device lock files, keyed by
                              host; one lock file per device, so only one
                              upgrade() can run against it at a time.
                              Defaults to a fixed subdirectory of the
                              system temp dir, shared by all HuaweiVRP
                              instances on this machine.
        force_downgrade     — upgrade() rejects a target firmware/patch
                              older than what's currently running unless
                              this is True (default False). When True, the
                              downgrade is logged at warning level and a
                              best-effort configuration-compatibility
                              warning is issued; requires
                              i_understand_downgrade_risk=True as well.
        i_understand_downgrade_risk — required second, explicit
                              confirmation when force_downgrade=True
                              (default False); upgrade() raises ValueError
                              if force_downgrade is set without this.
        upload_timeout      — seconds bounding each individual SFTP
                              transfer attempt during upgrade()'s firmware/
                              patch upload (default 120). Does not apply to
                              the general-purpose client.upload().
        upload_retries      — number of upload+verify (exists + size)
                              attempts before upgrade() gives up and raises
                              RuntimeError (default 3).
        health_check_mode   — "abort" (default) or "warn". Controls what
                              upgrade() does when the pre-upgrade health
                              check (CPU/memory/alarms/interfaces) finds a
                              violation: "abort" raises RuntimeError before
                              any state change; "warn" logs and continues.
                              The check itself always runs and always
                              evaluates in both modes — "warn" is an
                              explicit, non-default opt-in, never a silent
                              skip. Invalid values raise ValueError.
        health_check_cpu_threshold — percent; pre-upgrade CPU usage above
                              this triggers abort/warn (default 80.0).
        health_check_memory_threshold — percent; pre-upgrade memory usage
                              above this triggers abort/warn (default 80.0).
        health_check_max_down_interfaces — number of interfaces already
                              down before upgrade that's tolerated without
                              triggering abort/warn (default 0).
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
            "keepalive": keepalive,
            "disabled_algorithms": disabled_algorithms,
        }

        self.host = host
        self.username = username
        self.firmware_version = firmware_version
        self.firmware_file = firmware_file
        self.patch_version = patch_version
        self.patch_file = patch_file
        self.reconnect_timeout = reconnect_timeout
        self.reconnect_delay = reconnect_delay
        self.lock_timeout = lock_timeout
        self.lock_dir = lock_dir or os.path.join(
            tempfile.gettempdir(), "network_automation_huawei_vrp_locks"
        )
        self.force_downgrade = force_downgrade
        self.i_understand_downgrade_risk = i_understand_downgrade_risk
        self.upload_timeout = upload_timeout
        self.upload_retries = upload_retries
        self.health_check_mode = health_check_mode
        self.health_check_cpu_threshold = health_check_cpu_threshold
        self.health_check_memory_threshold = health_check_memory_threshold
        self.health_check_max_down_interfaces = health_check_max_down_interfaces

    def get_info(self, *, return_result: bool = False):
        """Read device info (version, ESN, startup config) for all stack units."""
        return read_info(self, return_result=return_result)

    def get_discovery_facts(self, *, return_result: bool = False):
        """
        Read serial number and base firmware version for CMDB sync (Device
        Discovery). Reuses get_info()'s connect/disconnect lifecycle.
        """
        result = self.get_info(return_result=True)
        facts = extract_discovery_facts(result.metadata["units"])
        if return_result:
            result.metadata.update(facts)
            return result
        return facts

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
    # Backup
    # -------------------------------------------------------

    def backup(
        self,
        name: str,
        *,
        return_result: bool = False,
        download_dir: str = ".",
    ):
        """Save a named configuration snapshot on the device and download it via SFTP."""
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
        """Reboot the device, confirming any interactive [y/n] prompt.

        VRP can print an indeterminate "Info: ... please wait" delay (e.g.
        comparing the pending startup software/patch versions) *before* the
        real "Continue? [y/n]:" prompt — observed live to pause long enough
        that send_command_timing()'s idle-time completion heuristic returns
        early, with output that doesn't yet contain the prompt. The old
        code's loop then read that as "no confirmation needed" and silently
        skipped sending "y" altogether, leaving the prompt dangling on the
        device — which discards it once the session disconnects, so the
        reboot never actually happened despite the run reporting success.

        Uses pattern-based send_command() for the initial "reboot" send,
        which waits for the prompt text itself (bounded by read_timeout)
        rather than for the channel to go idle, so it isn't fooled by a
        mid-response pause.

        Confirming with "y" is deliberately different: observed live to be
        followed by "Info: system is rebooting, please wait..." and then
        *nothing else* for over a minute, without the connection actually
        closing — pattern-matching that with send_command(read_timeout=300)
        polls read_channel() every ~10-30ms for however much of those 300s
        is left, flooding the log and blocking disconnect() for no benefit
        (there's no further prompt coming once the device is actually
        rebooting). send_command_timing()'s idle-time detection is the
        right tool for this step instead — it returns as soon as the
        device goes quiet, bounded by a short read_timeout as a ceiling,
        not a target. The device dropping the connection entirely during
        this is also treated as the expected success case, not an error.
        """
        self.logger.info(
            "Rebooting device... (typically several minutes; will wait up "
            "to %ds for it to reconnect)",
            self.reconnect_timeout,
        )

        # send_command output here is an interactive [y/n] confirmation
        # prompt, not command output to validate — the CLI-error check does
        # not apply to prompt-handling loops.
        debug_log(self, "send_command: %s", "reboot")
        output = self.conn.send_command(
            "reboot",
            expect_string=r"(?i)y/n|[\]>]",
            read_timeout=300,
            strip_prompt=False,
            strip_command=False,
        )
        debug_log(self, "send_command response: %s", output)

        for _ in range(3):
            if "y/n" not in output.lower():
                break
            debug_log(self, "send_command_timing: %s", "y")
            try:
                output = self.conn.send_command_timing("y", read_timeout=15)
                debug_log(self, "send_command_timing response: %s", output)
            except Exception as exc:
                debug_log(
                    self,
                    "send_command_timing raised while confirming reboot "
                    "(expected if the device is now actually rebooting): %s", exc,
                )
                output = ""
                break

        try:
            self.conn.disconnect()
        except Exception:
            pass

        self.conn = None

    def wait_for_reconnect(self):
        """
        Wait until the device is reachable via SSH and CLI is ready.

        All status/heartbeat logging here goes through
        BaseClient._safe_log_info() (best-effort, never raises) — see that
        method's docstring: a logger failure must never abort a reconnect
        wait that is itself succeeding.
        """

        self._safe_log_info("Waiting for %s to reconnect...", self.host)

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
                # Deliberately tolerant of garbled/incomplete output during
                # device boot and already retried on any exception below, so
                # the CLI-error check does not apply here.
                debug_log(self, "send_command: %s", "display version")
                out = conn.send_command(
                    "display version",
                    delay_factor=2,
                    read_timeout=10,
                )
                debug_log(self, "send_command response: %s", out)

                if "vrp" in out.lower():
                    self._safe_log_info("Device fully online (SSH + CLI ready).")
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
    # Firmware upgrade
    # -------------------------------------------------------

    def upgrade(self, *, return_result: bool = False):
        """
        Run the upgrade workflow (single-unit devices only): firmware, patch,
        or both, depending on the current vs. target versions.

        See network_automation/platforms/huawei_vrp/upgrade.py for scope
        and limitations.
        """
        return upgrade_helper(self, return_result=return_result)
