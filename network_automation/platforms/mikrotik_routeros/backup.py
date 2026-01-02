# network_automation/platforms/mikrotik_routeros/backup.py

"""
Mikrotik RouterOS backup helpers.
"""

from network_automation.results import OperationResult


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

        backup_file = f"{name}.backup"
        client.logger.info(f"Creating backup '{backup_file}'")

        # Create backup on RouterOS
        client.conn.send_command(
            f"/system backup save name={name}",
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
