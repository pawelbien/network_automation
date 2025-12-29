"""
Mikrotik backup helpers.
"""

import time


def run_backup(client, name):
    """Create system backup on device."""
    client.logger.info(f"Creating backup '{name}'...")
    client.conn.send_command(f"/system backup save name={name}")
    time.sleep(1)
