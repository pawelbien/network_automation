import re

"""
Mikrotik device information helpers.
"""

def get_info(client):
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

    return arch, version

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
