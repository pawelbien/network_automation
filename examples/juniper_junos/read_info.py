# examples/juniper_junos/read_info.py

"""
Example: read device information from a Juniper Junos device.

Runs 'show version' and 'show chassis hardware' and prints a structured
summary of the single unit.
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
        "device_type": "juniper_junos",
        "host": "10.0.0.100",
        "username": "testuser",
        "key_file": "~/.ssh/id_rsa_test",
        "passphrase": passphrase,
        "use_keys": True,
        # Junos 15.1 and older (OpenSSH 6.9) reject rsa-sha2-256/512
        # signatures; uncomment for RSA keys on those releases.
        # "disabled_algorithms": {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
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
