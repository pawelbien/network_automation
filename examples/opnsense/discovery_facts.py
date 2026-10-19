# examples/opnsense/discovery_facts.py

"""
Example: read Device Discovery facts from an OPNsense device.

Prints the CMDB facts used by Device Discovery: serial and model from
SMBIOS (None when unavailable and always None on VMs) and the bare
software version ("26.1.11_10"), as matched against the SoftwareVersion
catalog.
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
        "device_type": "opnsense",
        "host": "10.0.0.1",
        "username": "testuser",
        "key_file": "~/.ssh/id_rsa_test",
        "passphrase": passphrase,
        "use_keys": True,
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
