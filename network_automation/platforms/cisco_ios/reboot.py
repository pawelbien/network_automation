# network_automation/platforms/cisco_ios/reboot.py

import time

from netmiko import ConnectHandler


def reboot(client):
    """Reload the device, declining to save any pending config changes."""
    client.logger.info("Rebooting device...")

    out = client.conn.send_command_timing("reload")

    if "save?" in out.lower():
        out = client.conn.send_command_timing("no")

    if "confirm" in out.lower():
        client.conn.send_command_timing("\n")
    else:
        time.sleep(0.3)
        out2 = client.conn.send_command_timing("")
        if "confirm" in out2.lower():
            client.conn.send_command_timing("\n")
        else:
            client.logger.warning(
                "Reload confirmation prompt not detected — sending newline anyway."
            )
            client.conn.send_command_timing("\n")

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

            if "version" in out.lower():
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
