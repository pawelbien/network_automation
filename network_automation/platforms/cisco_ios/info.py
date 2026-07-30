# network_automation/platforms/cisco_ios/info.py

import re

from network_automation.results import OperationResult

_HOSTNAME_RE = re.compile(r"^(\S+) uptime is", re.MULTILINE)
_VERSION_RE = re.compile(r"[Vv]ersion (\S+),")
_MODEL_RE = re.compile(r"[Cc]isco (\S+) \(")
_SERIAL_RE = re.compile(r"Processor board ID (\S+)")


def _parse_show_version(output: str) -> dict:
    hostname = _HOSTNAME_RE.search(output)
    if not hostname:
        raise ValueError("Hostname not found in 'show version' output")

    version = _VERSION_RE.search(output)
    if not version:
        raise ValueError("Version not found in 'show version' output")

    model = _MODEL_RE.search(output)
    if not model:
        raise ValueError("Model not found in 'show version' output")

    serial = _SERIAL_RE.search(output)
    if not serial:
        raise ValueError("Serial number not found in 'show version' output")

    return {
        "name": hostname.group(1),
        "version": version.group(1),
        "model": model.group(1),
        "serial": serial.group(1),
    }


def get_info(client):
    client.logger.info("Reading system info...")
    output = client.conn.send_command("show version")
    parsed = _parse_show_version(output)

    client.current_version = parsed["version"]

    unit = {
        "id": 0,
        "role": "master",
        "version": parsed["version"],
        "name": parsed["name"],
        "serial": parsed["serial"],
        "model": parsed["model"],
    }
    return {"units": [unit]}


def read_info(client, *, return_result: bool = False):
    result = OperationResult(success=True, operation="info")
    result.mark_started()

    client.connect()
    try:
        info = get_info(client)
        result.metadata.update(info)
        result.message = "Info retrieved successfully."
    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise
    finally:
        result.mark_finished()
        client.disconnect()

    return result if return_result else info
