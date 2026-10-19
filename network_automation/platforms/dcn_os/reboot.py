# network_automation/platforms/dcn_os/reboot.py

import time

_MAX_PROMPT_ROUNDS = 3


def _is_save_prompt(out) -> bool:
    return "save" in (out or "").lower()


def _is_confirm_prompt(out) -> bool:
    text = (out or "").lower()
    return "[y/n]" in text or "(y/n)" in text or "confirm" in text


def reboot(client):
    """
    Reload the device with 'reload', declining to save pending config
    changes. The exact DCN OS dialog is not pinned down, so prompts are
    matched loosely: a question mentioning "save" is answered "N", a
    [Y/N] / confirm prompt is answered "Y". When no confirmation prompt
    shows up, "Y" is sent anyway after a warning.
    """
    client.logger.info("Rebooting device...")

    out = client.conn.send_command_timing("reload")
    confirmed = False

    for _ in range(_MAX_PROMPT_ROUNDS):
        if _is_save_prompt(out):
            out = client.conn.send_command_timing("N")
            continue
        if _is_confirm_prompt(out):
            client.conn.send_command_timing("Y")
            confirmed = True
            break
        time.sleep(0.3)
        out = client.conn.send_command_timing("")

    if not confirmed:
        client.logger.warning(
            "Reload confirmation prompt not detected — sending 'Y' anyway."
        )
        client.conn.send_command_timing("Y")

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
            conn = client._open_connection()
            time.sleep(1.0)

            out = conn.send_command("show version", delay_factor=2, read_timeout=10)

            if "software package version" in out.lower():
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
