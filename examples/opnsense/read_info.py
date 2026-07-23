# examples/opnsense/read_info.py

"""
Example: read device information from an OPNsense device.

Collects hostname, OPNsense version, FreeBSD version, and uptime, and
prints a structured summary of the single unit.
"""

import os
import logging
from network_automation.factory import get_client
from network_automation.platforms.opnsense.info import read_info


def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    password = os.environ.get("OPNSENSE_PASSWORD")
    if not password:
        raise RuntimeError("Environment variable OPNSENSE_PASSWORD is not set.")

    params = {
        "device_type": "opnsense",
        "host": "10.0.0.1",
        "username": "testuser",
        "password": password,
        # skip_menu=True (default) assumes the SSH account lands directly
        # in a shell. Set skip_menu=False for accounts that still see
        # OPNsense's numbered console menu ("0) Logout" ... "8) Shell").
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
