# network_automation/platforms/cisco_ios/backup.py

from network_automation.results import OperationResult


def run_backup(client, name: str, *, return_result: bool = False, download_dir: str = "."):
    """
    Capture running-config over the existing SSH session and write it to a
    local file — no on-device file or SFTP transfer, since IOS/IOS-XE SCP/
    SFTP server support is not guaranteed to be enabled.
    """
    result = OperationResult(
        success=True,
        operation="backup",
        metadata={"backup_name": name},
    )

    result.mark_started()

    try:
        client.connect()

        client.logger.info("Reading running-config")
        config = client.conn.send_command("show running-config")

        local_path = f"{download_dir.rstrip('/')}/{name}.cfg"
        with open(local_path, "w") as f:
            f.write(config)

        result.metadata["local_path"] = local_path
        result.message = f"Backup written to {local_path}"

        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
