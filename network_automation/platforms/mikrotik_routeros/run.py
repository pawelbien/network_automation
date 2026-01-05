# network_automation/platforms/mikrotik_routeros/run.py

"""
Mikrotik RouterOS command execution helpers.
"""

from network_automation.results import OperationResult


def run_commands(client, commands):
    """
    Execute one or more RouterOS commands on an active connection.

    This helper assumes:
    - client.conn is already connected
    - no connection lifecycle handling here
    """

    if isinstance(commands, str):
        commands = [commands]

    outputs = []

    for cmd in commands:
        client.logger.info("Running command: %s", cmd)

        output = client.conn.send_command(cmd)

        outputs.append(
            {
                "command": cmd,
                "output": output,
            }
        )

    return outputs


def run(
    client,
    commands,
    *,
    return_result: bool = False,
):
    """
    Run one or more commands as a full workflow operation.

    Behavior:
    - Connects to device
    - Executes commands
    - Disconnects
    - Returns raw output or OperationResult
    - Raises exceptions on failure
    """

    result = OperationResult(
        success=True,
        operation="run",
        metadata={
            "commands": commands,
        },
    )

    result.mark_started()

    try:
        client.connect()

        outputs = run_commands(client, commands)

        result.metadata["output"] = outputs
        result.message = "Commands executed successfully"

        return result if return_result else outputs

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()

