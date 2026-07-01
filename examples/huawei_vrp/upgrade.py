# examples/huawei_vrp/upgrade.py

"""
Example: firmware-only upgrade of a single-unit Huawei VRP device.

Uploads a local .cc firmware image, configures it as the next startup
image, reboots, and verifies the resulting firmware version. Stacks
(more than one unit) are rejected, not silently mis-handled.

Not covered by this workflow yet (see docs/architecture.md and
engineering_handbook/tmp/huawei_vrp_update.txt for the full target scope):
patch upgrades, MD5 verification, health checks, cleanup, rollback,
concurrency locking, forced downgrade.
"""

import os
import sys
import logging
from network_automation.factory import get_client


def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # --- required arguments: target version and local firmware file ---
    if len(sys.argv) != 3:
        print("Usage: python upgrade.py <firmware_version> <firmware_file>")
        print(
            "Example: python upgrade.py V300R024C00SPC100 "
            "/opt/firmware/huawei/AR650A_V300R024C00SPC100.cc"
        )
        sys.exit(1)

    firmware_version = sys.argv[1]
    firmware_file = sys.argv[2]

    # --- SSH key passphrase ---
    passphrase = os.environ.get("PASSPHRASE")
    if not passphrase:
        raise RuntimeError("Environment variable PASSPHRASE is not set.")

    # Huawei VRP may require disabling rsa-sha2-512 and rsa-sha2-256
    # in Paramiko/Netmiko when using RSA key authentication,
    # as some VRP SSH implementations only support ssh-rsa signatures.
    params = {
        "device_type": "huawei",
        "host": "10.0.0.100",
        "username": "testuser",
        "key_file": "~/.ssh/id_rsa_test",
        "passphrase": passphrase,
        "use_keys": True,
        "disabled_algorithms": {
            "pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]
        },
        "firmware_version": firmware_version,
        "firmware_file": firmware_file,
    }

    client = get_client(**params)

    try:
        result = client.upgrade(return_result=True)
    except Exception as exc:
        print(f"Upgrade failed: {exc}")
        sys.exit(2)

    if result.success:
        print(f"SUCCESS: {result.message}")
        if result.duration_seconds is not None:
            print(f"Duration: {result.duration_seconds:.1f}s")
    else:
        print("FAILED")
        for err in result.errors:
            print(f"- {err}")
        sys.exit(3)


if __name__ == "__main__":
    main()
