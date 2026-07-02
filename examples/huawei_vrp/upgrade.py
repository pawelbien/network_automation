# examples/huawei_vrp/upgrade.py

"""
Example: firmware and/or patch upgrade of a single-unit Huawei VRP device.

Uploads the local .cc firmware image (and, optionally, a .pat patch
package), configures next-boot startup accordingly, reboots if needed, and
verifies the resulting firmware/patch. Stacks (more than one unit) are
rejected, not silently mis-handled.

Shows every HuaweiVRP constructor parameter and every ExecutionContext
parameter accepted by get_client() (logger/device_name/job_id/metadata/
dry_run/debug_log), each with an explanatory comment — most are left at
their library defaults here so the example stays runnable as-is; adjust
per your environment.

Not covered by this workflow yet (see docs/architecture.md for details):
automatic rollback after a failed post-reboot validation, and
multi-unit/stack upgrades.
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

    # --- required: target firmware version + local .cc file ---
    # --- optional: target patch version + local .pat file (both or neither) ---
    if len(sys.argv) not in (3, 5):
        print(
            "Usage: python upgrade.py <firmware_version> <firmware_file> "
            "[<patch_version> <patch_file>]"
        )
        print(
            "Example: python upgrade.py V300R024C00SPC100 "
            "/opt/firmware/huawei/AR650A_V300R024C00SPC100.cc"
        )
        print(
            "Example with patch: python upgrade.py V300R024C00SPC100 "
            "/opt/firmware/huawei/AR650A_V300R024C00SPC100.cc "
            "SPH1b0 /opt/firmware/huawei/AR650A_V300R024SPH1b0.pat"
        )
        sys.exit(1)

    firmware_version = sys.argv[1]
    firmware_file = sys.argv[2]
    patch_version = sys.argv[3] if len(sys.argv) == 5 else None
    patch_file = sys.argv[4] if len(sys.argv) == 5 else None

    # --- SSH key passphrase (key-based auth — see "authentication" below) ---
    passphrase = os.environ.get("PASSPHRASE")
    if not passphrase:
        raise RuntimeError("Environment variable PASSPHRASE is not set.")

    params = {
        "device_type": "huawei",

        # --- connection ---
        "host": "10.0.0.100",
        "username": "testuser",
        "port": 22,
        "connect_retries": 2,  # BaseClient.connect() retry count
        "connect_delay": 2,    # seconds between connect retries

        # --- authentication: password OR key-based (use_keys=True) ---
        # "password": os.environ.get("HUAWEI_PASSWORD"),  # alternative to key auth
        "key_file": "~/.ssh/id_rsa_test",
        "passphrase": passphrase,
        "use_keys": True,
        # Huawei VRP may require disabling rsa-sha2-512 and rsa-sha2-256
        # in Paramiko/Netmiko when using RSA key authentication, as some
        # VRP SSH implementations only support ssh-rsa signatures.
        "disabled_algorithms": {
            "pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]
        },

        # --- target firmware (required) / optional target patch ---
        "firmware_version": firmware_version,
        "firmware_file": firmware_file,
        "patch_version": patch_version,
        "patch_file": patch_file,

        # --- reconnect polling after reboot ---
        "reconnect_timeout": 300,  # seconds to wait for SSH to come back
        "reconnect_delay": 10,     # polling interval while waiting

        # --- exclusive per-device lock (one upgrade() at a time) ---
        "lock_timeout": 3600,  # seconds before a dead holder's lock is reclaimed
        "lock_dir": None,      # defaults to a subdir of the system temp dir

        # --- forced downgrade — both required together, off by default ---
        "force_downgrade": False,
        "i_understand_downgrade_risk": False,

        # --- firmware/patch transfer: retry + per-attempt timeout ---
        "upload_timeout": 120,  # seconds per SFTP transfer attempt
        "upload_retries": 3,

        # --- pre-upgrade health check (CPU/memory/alarms/interfaces) ---
        "health_check_mode": "abort",  # "abort" (default) or "warn"
        "health_check_cpu_threshold": 80.0,
        "health_check_memory_threshold": 80.0,
        "health_check_max_down_interfaces": 0,

        # --- execution context: logging, dry-run, debug diagnostics ---
        # (get_client() builds an ExecutionContext from these; pass a
        # pre-built context= instead if you need more control)
        "logger": logging.getLogger("huawei_vrp_upgrade_example"),
        "device_name": "10.0.0.100",
        "job_id": None,
        "metadata": {},
        "dry_run": False,    # True: compute + report the plan, make no changes
        "debug_log": False,  # True: verbose DEBUG logs (raw CLI I/O, step
                              # timing, full result.metadata) — off by default,
                              # never changes behavior at the default log level
    }

    client = get_client(**params)

    try:
        result = client.upgrade(return_result=True)
    except Exception as exc:
        print(f"Upgrade failed: {exc}")
        sys.exit(2)

    if result.success:
        print(f"SUCCESS: {result.message}")
        if result.duration_seconds is not None:
            print(f"Duration: {result.duration_seconds:.1f}s")
    else:
        print("FAILED")
        for err in result.errors:
            print(f"- {err}")
        sys.exit(3)


if __name__ == "__main__":
    main()
