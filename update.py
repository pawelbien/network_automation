# network_automation/update.py

import os
import sys
import logging
from network_automation.factory import get_client

def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # --- required argument: version ---
    if len(sys.argv) != 2:
        print("Usage: python update.py <firmware_version>")
        print("Example: python update.py 7.18.2")
        sys.exit(1)

    firmware_version = sys.argv[1]

    # --- SSH key passphrase ---
    passphrase = os.environ.get("PASSPHRASE")
    if not passphrase:
        raise RuntimeError("Environment variable PASSPHRASE is not set.")

    params = {
        "device_type": "mikrotik_routeros",
        "host":     "10.0.0.100",
        "username": "testuser",
        "key_file": "~/.ssh/id_rsa_test",
        "passphrase": passphrase,
        "use_keys": True,
        "firmware_version": firmware_version,
    }

    client = get_client(**params)
    client.upgrade()

if __name__ == "__main__":
    main()
