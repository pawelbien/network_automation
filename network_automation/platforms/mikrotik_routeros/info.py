# network_automation/platforms/mikrotik_routeros/info.py

"""
Mikrotik device information helpers.
"""

import re

from network_automation.results import OperationResult


def _get_software_info(client):
    """Read system architecture and version."""
    client.logger.info("Reading system info...")

    output = client.conn.send_command("/system resource print")

    arch = None
    version = None

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("architecture-name:"):
            arch = line.split(":", 1)[1].strip()
        elif line.startswith("version:"):
            version = line.split(":", 1)[1].strip()

    if not arch:
        raise ValueError("Architecture not found in system resource output.")
    if not version:
        raise ValueError("Version not found in system resource output.")

    return {"arch": arch, "version": version}


def _get_hardware_info(client):
    """
    Read hardware information from RouterBOARD.
    
    Returns dict with:
    - serial: serial number
    - model: device model
    - current_firmware: current bootloader firmware version
    - upgrade_firmware: available bootloader firmware upgrade version
    
    Raises RuntimeError if RouterBOARD is not supported (e.g. CHR).
    """
    client.logger.info("Reading hardware info...")
    
    output = client.conn.send_command("/system routerboard print")
    
    # CHR case - RouterBOARD not supported
    if "bad command name" in output.lower():
        raise RuntimeError(
            "Hardware info not supported on this platform (RouterBOARD not available)"
        )
    
    serial = None
    model = None
    bootloader_current_firmware = None
    bootloader_upgrade_firmware = None
    
    for line in output.splitlines():
        line = line.strip()
        
        if line.startswith("serial-number:"):
            serial = line.split(":", 1)[1].strip()
        elif line.startswith("model:"):
            model = line.split(":", 1)[1].strip()
        elif line.startswith("current-firmware:"):
            bootloader_current_firmware = line.split(":", 1)[1].strip()
        elif line.startswith("upgrade-firmware:"):
            bootloader_upgrade_firmware = line.split(":", 1)[1].strip()
    
    # Validate required fields
    if not serial:
        raise ValueError("Serial number not found in routerboard output.")
    if not model:
        raise ValueError("Model not found in routerboard output.")
    if not bootloader_current_firmware:
        raise ValueError("Current firmware not found in routerboard output.")
    if not bootloader_upgrade_firmware:
        raise ValueError("Upgrade firmware not found in routerboard output.")
    
    return {
        "serial": serial,
        "model": model,
        "bootloader_current_firmware": bootloader_current_firmware,
        "bootloader_upgrade_firmware": bootloader_upgrade_firmware,
    }

def _get_system_identity(client):
    """
    Read RouterOS system identity (device name).
    
    Returns dict with:
    - name: device name
    
    Raises ValueError if name not found in output.
    """
    client.logger.info("Reading system identity...")
    
    output = client.conn.send_command("/system identity print")

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            return {
                "name": line.split(":", 1)[1].strip()
            }

    raise ValueError("System identity name not found")

def normalize_version(v):
    """Normalize RouterOS version string to tuple."""
    v = v.strip().lower()
    m = re.search(r"\d+(?:\.\d+){0,2}", v)
    if not m:
        raise ValueError(f"Cannot extract numeric version from: {v}")
    parts = m.group(0).split(".")
    parts += ["0"] * (3 - len(parts))
    return tuple(int(p) for p in parts)


def is_newer_version(current_version, new_version):
    """Return True if new_version > current_version."""
    return normalize_version(new_version) > normalize_version(current_version)


def get_info(client):
    """
    Collect device information and return a unified unit structure.

    Returns dict:
    {
        "units": [
            {
                "id":                          int,        # always 0
                "role":                        str,        # always "master"
                "arch":                        str,
                "version":                     str,
                "name":                        str,
                "serial":                      str | None, # None on CHR
                "model":                       str | None, # None on CHR
                "bootloader_current_firmware": str | None, # None on CHR
                "bootloader_upgrade_firmware": str | None, # None on CHR
            }
        ]
    }
    """
    client.logger.info("Reading device info...")

    software = _get_software_info(client)
    client.arch = software["arch"]
    client.current_version = software["version"]

    identity = _get_system_identity(client)

    unit = {
        "id": 0,
        "role": "master",
        "arch": software["arch"],
        "version": software["version"],
        "name": identity["name"],
        "serial": None,
        "model": None,
        "bootloader_current_firmware": None,
        "bootloader_upgrade_firmware": None,
    }

    try:
        hardware = _get_hardware_info(client)
        unit["serial"] = hardware["serial"]
        unit["model"] = hardware["model"]
        unit["bootloader_current_firmware"] = hardware["bootloader_current_firmware"]
        unit["bootloader_upgrade_firmware"] = hardware["bootloader_upgrade_firmware"]
    except RuntimeError:
        pass  # CHR: RouterBOARD not available

    return {"units": [unit]}


def read_info(client, *, return_result: bool = False):
    """
    Read device information as a full workflow operation (connect → collect → disconnect).

    Returns:
        return_result=False: dict {"units": [...]}
        return_result=True:  OperationResult with metadata["units"]
    """
    result = OperationResult(
        success=True,
        operation="info",
    )

    result.mark_started()

    client.connect()
    try:
        info = get_info(client)
        result.metadata.update(info)
        result.message = "System information read successfully"

        return result if return_result else info

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
