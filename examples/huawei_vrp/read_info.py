# examples/huawei_vrp/read_info.py

"""
Example: read device information from a Huawei VRP device.

Runs three commands (display version, display esn, display startup)
and prints a structured summary of each unit (slot) found.
"""

import os
import logging
from network_automation.factory import get_client


def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    passphrase = os.environ.get("PASSPHRASE")
    if not passphrase:
        raise RuntimeError("Environment variable PASSPHRASE is not set.")

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
    }

    client = get_client(**params)

    result = client.get_info(return_result=True)

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
