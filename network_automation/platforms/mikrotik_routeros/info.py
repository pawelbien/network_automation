# network_automation/platforms/mikrotik_routeros/info.py

"""
Mikrotik device information helpers.
"""

import re

from network_automation.results import OperationResult


def get_software_info(client):
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


def get_hardware_info(client):
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

def get_system_identity(client):
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


def read_info(client, *, return_result: bool = False):
    """
    Read device architecture, version, hardware information, and system identity as a workflow operation.
    Raises exceptions on failure.
    For external call.
    
    Returns:
        If return_result=True: OperationResult with metadata
        If return_result=False: dict with keys:
            - arch: architecture name
            - version: RouterOS version
            - name: device name (system identity)
            - serial: serial number (if available)
            - model: device model (if available)
            - bootloader_current_firmware: current bootloader firmware (if available)
            - bootloader_upgrade_firmware: upgrade bootloader firmware (if available)
    """

    result = OperationResult(
        success=True,
        operation="info",
    )

    result.mark_started()

    client.connect()
    try:
        info = get_software_info(client)

        # Persist on client (existing behavior pattern)
        client.arch = info["arch"]
        client.current_version = info["version"]

        # Start with software info
        return_dict = info.copy()
        result.metadata.update(info)
        
        # Get system identity (device name)
        identity_info = get_system_identity(client)
        return_dict.update(identity_info)
        result.metadata.update(identity_info)
        
        # Try to get hardware info (may not be available on CHR)
        try:
            hardware_info = get_hardware_info(client)
            return_dict.update(hardware_info)
            result.metadata.update(hardware_info)
        except RuntimeError:
            # Hardware info not available (e.g., CHR platform)
            result.metadata["hardware_info_available"] = False
        
        result.message = "System information read successfully"

        return result if return_result else return_dict

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
