# network_automation/platforms/juniper_junos/reboot.py

import time

from netmiko import ConnectHandler


def _is_reboot_prompt(out) -> bool:
    return "[yes,no]" in (out or "").lower()


def reboot(client):
    """
    Reboot the device with 'request system reboot', answering the
    "Reboot the system ? [yes,no] (no)" prompt with "yes" — the default
    answer is "no", so a bare newline would cancel the reboot.
    """
    client.logger.info("Rebooting device...")

    out = client.conn.send_command_timing("request system reboot")

    if _is_reboot_prompt(out):
        client.conn.send_command_timing("yes")
    else:
        time.sleep(0.3)
        out2 = client.conn.send_command_timing("")
        if _is_reboot_prompt(out2):
            client.conn.send_command_timing("yes")
        else:
            client.logger.warning(
                "Reboot confirmation prompt not detected — sending 'yes' anyway."
            )
            client.conn.send_command_timing("yes")

    try:
        client.conn.disconnect()
    except Exception:
        pass

    client.conn = None


def wait_for_reconnect(client):
    """Wait until the device is reachable via SSH and the CLI is ready."""
    client._safe_log_info("Waiting for %s to reconnect...", client.host)

    start = time.time()
    last_log = start

    while True:
        elapsed = time.time() - start

        if elapsed > client.reconnect_timeout:
            raise TimeoutError(
                f"Device did not reconnect within {client.reconnect_timeout} seconds."
            )

        conn = None
        try:
            conn = ConnectHandler(**client.device)
            time.sleep(1.0)

            out = conn.send_command("show version", delay_factor=2, read_timeout=10)

            if "junos" in out.lower():
                client._safe_log_info("Device fully online (SSH + CLI ready).")
                client.conn = conn
                return conn

        except Exception:
            pass

        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass

        now = time.time()
        if now - last_log > 60:
            client._safe_log_info(
                "Still waiting for %s to reconnect (%ds elapsed)",
                client.host,
                int(elapsed),
            )
            last_log = now

        time.sleep(client.reconnect_delay)
