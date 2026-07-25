# examples/opnsense/update.py

"""
Example: update an OPNsense device within its current release branch
(`configctl firmware update` — package update, optional base/kernel
update, reboot only if the backend decided one is required).

Progress is reported as a handful of stage messages (e.g. "Updating
repositories...", "Installing packages...") rather than raw CLI output —
see docs/architecture.md's "Progress Reporting for Long-Running Backend
Operations". debug_log_dir below is optional and off by default; set it
to capture every raw line, reconnect attempt, and exception to a local
per-device file for troubleshooting.
"""

import os
import logging
from network_automation.factory import get_client
from network_automation.platforms.opnsense.upgrade import update


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
        # skip_menu=True (default) assumes the SSH account lands directly
        # in a shell. Set skip_menu=False for accounts that still see
        # OPNsense's numbered console menu ("0) Logout" ... "8) Shell").

        # Detailed per-operation diagnostic log file - opt-in, off (None)
        # by default. Never forwarded to the logger configured above.
        "debug_log_dir": "./opnsense_debug_logs",
    }

    client = get_client(**params)

    result = update(client, return_result=True)

    if result.success:
        print(f"SUCCESS: {result.message}")
        if result.duration_seconds is not None:
            print(f"Duration: {result.duration_seconds:.1f}s")
        print("=" * 60)
        for key, value in result.metadata.items():
            if key == "log":
                print("--- log ---")
                print(value)
            else:
                print(f"{key}: {value}")
    else:
        print("FAILED")
        for err in result.errors:
            print(f"- {err}")


if __name__ == "__main__":
    main()
