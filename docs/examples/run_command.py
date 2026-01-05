# network_automation/examples/run_command.py

"""
Example: run arbitrary commands on Mikrotik RouterOS (CLI style).
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

    # --- required arguments: one or more commands ---
    if len(sys.argv) < 2:
        print("Usage: python run_command.py <command> [<command> ...]")
        print('Example:')
        print('  python run_command.py "/system resource print"')
        print('  python run_command.py "/ip address print" "/interface print"')
        sys.exit(1)

    commands = sys.argv[1:]

    # --- SSH key passphrase ---
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
        # firmware_version not required here
    }

    client = get_client(**params)

    # --- run commands ---
    result = client.run(commands, return_result=True)

    # --- print output ---
    for entry in result.metadata["output"]:
        print("=" * 60)
        print(f"COMMAND: {entry['command']}")
        print("-" * 60)
        print(entry["output"])

    if result.duration_seconds is not None:
        print("=" * 60)
        print(f"Execution time: {result.duration_seconds:.2f}s")


if __name__ == "__main__":
    main()
