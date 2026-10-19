# examples/dcn_os/discovery_facts.py

"""
Example: read Device Discovery facts from a DCN OS switch.

Prints the CMDB facts used by Device Discovery: the serial, the model from
'show version' ("S5750E-28X-SI"), the SoftWare (Package) Version
("V700R001C001B001"), as matched against the SoftwareVersion catalog, and
the 'show vendor' DevType ID ("360"), compared with the device type's
dcn_firmware_devtype_id.
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
        "device_type": "dcn_os",
        "host": "10.0.0.100",
        "username": "testuser",
        "key_file": "~/.ssh/id_rsa_test",
        "passphrase": passphrase,
        "use_keys": True,
        # The DCN OS SSH server accepts only ssh-rsa signatures for RSA keys.
        "disabled_algorithms": {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
    }

    client = get_client(**params)

    result = client.get_discovery_facts(return_result=True)

    print("=" * 60)
    print(f"  serial:           {result.metadata['serial']}")
    print(f"  software_version: {result.metadata['software_version']}")
    print(f"  model:            {result.metadata['model']}")
    print(f"  devtype_id:       {result.metadata['devtype_id']}")

    if result.duration_seconds is not None:
        print("=" * 60)
        print(f"Execution time: {result.duration_seconds:.2f}s")


if __name__ == "__main__":
    main()
