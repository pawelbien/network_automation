# network_automation/platforms/mikrotik_routeros/backup.py

"""
Mikrotik RouterOS backup helpers.
"""

from network_automation.results import OperationResult

def cleanup_old_backups(client):
    """
    Remove old RouterOS backup files created by network_automation.

    Only files with prefix 'nauto_' are removed.
    """
    client.logger.info("Cleaning up old network_automation backups on device")

    output = client.conn.send_command(
        '/file print detail where name~"nauto_.*.backup"'
    )

    for line in output.splitlines():
        if "name=" not in line:
            continue

        # RouterOS format: name=nauto_xxx.backup
        parts = line.split()
        name_part = next(
            (p for p in parts if p.startswith("name=")),
            None,
        )

        if not name_part:
            continue

        filename = name_part.split("=", 1)[1]

        client.logger.info("Removing old backup file: %s", filename)
        client.conn.send_command(
            f'/file remove "{filename}"'
        )


def run_backup(
    client,
    name: str,
    *,
    return_result: bool = False,
    download_dir: str = ".",
):
    """
    Run backup on RouterOS and optionally download the backup file.

    Behavior:
    - Creates a .backup file on the device
    - Downloads it locally via Paramiko SFTP
    - Raises exceptions on failure
    - Optionally returns OperationResult
    """

    result = OperationResult(
        success=True,
        operation="backup",
        metadata={
            "backup_name": name,
        },
    )

    result.mark_started()

    try:
        client.connect()

        cleanup_old_backups(client)

        backup_name = f"nauto_{name}"
        backup_file = f"{backup_name}.backup"

        client.logger.info(f"Creating backup '{backup_file}'")

        client.conn.send_command(
            f"/system backup save name={backup_name}",
            expect_string=r"\[.*\]",
        )

        result.metadata["remote_file"] = backup_file

        # ---- download backup file via Paramiko SFTP ----
        local_path = f"{download_dir.rstrip('/')}/{backup_file}"
        client.logger.info(f"Downloading backup to {local_path}")

        sftp = client.conn.remote_conn_pre.open_sftp()
        try:
            sftp.get(backup_file, local_path)
        finally:
            sftp.close()

        result.metadata["local_path"] = local_path
        result.message = f"Backup '{backup_file}' created and downloaded"

        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()


