# network_automation/platforms/opnsense/reboot.py

"""
OPNsense reboot and post-reboot reconnect workflow.

reboot() and wait_for_reconnect() are two independent concepts, kept
decoupled on purpose:

- reboot() is a directly-callable, explicit "make the device reboot now"
  operation - analogous to Huawei/MikroTik's reboot(). It is never called
  by upgrade.py's update()/upgrade()/check_updates() workflows.
- wait_for_reconnect() is a general-purpose "wait until SSH+CLI answer
  again" poll, reusable regardless of who/what triggered the reboot. It
  is used both after an explicit reboot() call and inside upgrade.py after
  a `***REBOOT***` marker is found in a firmware operation's log - in that
  second case the reboot itself is a side effect of the already-running
  configctl firmware backend job (`rc.reboot`, detached from this SSH
  session), not something reboot() initiates.
"""

import time

from netmiko import ConnectHandler

from network_automation.platforms.opnsense.debug_log import debug_log


def reboot(client):
    """
    Reboot the device via a direct shell command.

    No interactive confirmation is expected (unlike Huawei/MikroTik's CLI
    reboot prompts) - `shutdown -r now` in a root shell reboots
    immediately. The connection dropping mid-command (or failing to
    return before OPNsense tears it down) is treated as the expected
    success case, not an error - same treatment as Huawei's reboot().
    """
    client.logger.info("Rebooting device...")

    command = "/sbin/shutdown -r now"
    debug_log(client, "send_command_timing: %s", command)
    try:
        client.conn.send_command_timing(command)
    except Exception:
        pass

    try:
        client.conn.disconnect()
    except Exception:
        pass
    client.conn = None


def wait_for_reconnect(client):
    """
    Wait until the device is reachable via SSH and its shell is ready.

    All status/heartbeat logging here goes through
    BaseClient._safe_log_info() (best-effort, never raises) - see that
    method's docstring: a logger failure must never abort a reconnect
    wait that is itself succeeding.

    On success, sets client.conn to the new connection and returns it.
    """
    client._safe_log_info("Waiting for %s to reconnect...", client.host)

    start = time.time()
    last_log = start

    while True:
        elapsed = time.time() - start

        if elapsed > client.reconnect_timeout:
            raise TimeoutError(
                f"Device did not reconnect within "
                f"{client.reconnect_timeout} seconds."
            )

        conn = None
        try:
            # ---- attempt SSH connection ----
            conn = ConnectHandler(**client.device)

            # ---- give OPNsense time to initialize the shell ----
            time.sleep(1.0)

            # ---- land in a shell (handles skip_menu=False consoles too) ----
            client.conn = conn
            client._ensure_shell()

            # ---- probe CLI readiness (bounded, must not hang) ----
            out = conn.send_command(
                "opnsense-version",
                delay_factor=2,
                read_timeout=10,
            )

            if out.strip():
                client._safe_log_info(
                    "Device fully online (SSH + CLI ready)."
                )
                return conn   # SUCCESS - do NOT disconnect

        except Exception:
            # retry silently; heartbeat will indicate progress
            pass

        # ---- cleanup only failed attempt ----
        client.conn = None
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass

        # ---- heartbeat INFO every 60s ----
        now = time.time()
        if now - last_log > 60:
            client._safe_log_info(
                "Still waiting for %s to reconnect (%ds elapsed)",
                client.host,
                int(elapsed),
            )
            last_log = now

        time.sleep(client.reconnect_delay)
