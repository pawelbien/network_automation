# examples/juniper_junos/discovery_facts.py

"""
Example: read Device Discovery facts from a Juniper Junos device.

Prints the CMDB facts used by Device Discovery: the chassis serial, the
model from 'show version' ("ex4600-40f") and the full software version
including the build number ("21.4R9-S9.9"), as matched against the
SoftwareVersion catalog.
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

    result = client.get_discovery_facts(return_result=True)

    print("=" * 60)
    print(f"  serial:           {result.metadata['serial']}")
    print(f"  software_version: {result.metadata['software_version']}")
    print(f"  model:            {result.metadata['model']}")

    if result.duration_seconds is not None:
        print("=" * 60)
        print(f"Execution time: {result.duration_seconds:.2f}s")


if __name__ == "__main__":
    main()
