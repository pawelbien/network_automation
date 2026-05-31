# examples/mikrotik_routeros/read_info.py

"""
Example: read device information from a MikroTik RouterOS device.

Collects software, identity, and hardware information and prints a structured
summary of the single unit. Hardware fields are None on CHR.
"""

import os
import logging
from network_automation.factory import get_client
from network_automation.platforms.mikrotik_routeros.info import read_info


def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    passphrase = os.environ.get("PASSPHRASE")
    if not passphrase:
        raise RuntimeError("Environment variable PASSPHRASE is not set.")

    params = {
        "device_type": "mikrotik_routeros",
        "host": "10.0.0.100",
        "username": "testuser",
        "key_file": "~/.ssh/id_rsa_test",
        "passphrase": passphrase,
        "use_keys": True,
    }

    client = get_client(**params)

    result = read_info(client, return_result=True)

    for i, unit in enumerate(result.metadata["units"]):
        print(f"{'=' * 60}")
        print(f"  unit: {i}")
        for key, value in unit.items():
            print(f"      {key}: {value}")

    if result.duration_seconds is not None:
        print("=" * 60)
        print(f"Execution time: {result.duration_seconds:.2f}s")


if __name__ == "__main__":
    main()
