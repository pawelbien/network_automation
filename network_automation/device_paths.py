# network_automation/device_paths.py

"""
Shared helpers for building on-device file names that stay within a
platform's own command-length limit.

Some platform CLIs hard-reject a command once the file name/path argument
exceeds a certain length (confirmed live on Huawei VRP: 64 chars for
`flash:/<file>` in `save`, see huawei_vrp/backup.py's
MAX_FLASH_PATH_LENGTH). Each platform module owns its own named limit
constant and passes it in here — this module only holds the shared
fallback mechanism, not the limit values themselves.
"""

import hashlib


def safe_device_name(name: str, *, prefix: str, suffix: str = "", max_length: int, path_prefix: str = "") -> str:
    """
    Build '<prefix><name><suffix>', falling back to a short, deterministic
    hash of `name` if len(path_prefix + prefix + name + suffix) would
    exceed max_length.

    The on-device name is purely an internal implementation detail —
    callers should always expose the original, caller-supplied `name` to
    the end user/metadata, never this function's return value, so trading
    readability for a guaranteed-short, collision-resistant name here
    (only when actually needed) is safe.
    """
    candidate = f"{prefix}{name}{suffix}"
    if len(f"{path_prefix}{candidate}") <= max_length:
        return candidate

    digest = hashlib.md5(name.encode()).hexdigest()[:16]
    return f"{prefix}{digest}{suffix}"
