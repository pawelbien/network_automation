# network_automation/base_client.py

import logging
import time
from network_automation.context import ExecutionContext
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from paramiko.ssh_exception import SSHException


def _classify_connect_failure(exc: Exception) -> str:
    """
    Best-effort, human-readable classification of why a connection attempt
    failed, for a log message closer to the truth than a blanket "may be
    offline". Netmiko's own exceptions were found (empirically, against a
    real legacy-SSH Huawei VRP device) to carry the underlying paramiko/
    socket error via __context__, not __cause__ - both are checked here.
    Never raises; falls back to the original "may be offline" wording when
    nothing more specific is found in the chain.

    A "Connection reset"/"Connection refused" means something on the other
    end actively responded and rejected the connection - i.e. the device
    IS reachable - which is a meaningfully different situation from a
    genuine timeout (no response of any kind, e.g. a truly offline host).

    A bare paramiko SSHException that is neither of those (observed
    empirically as SSHException("Invalid key") when a legacy VRP device
    rejects a public key's signature algorithm during auth) is *more*
    diagnostic than a reset/refused, not less - it means the device
    responded and completed enough of the SSH/auth exchange to actively
    reject this specific attempt, rather than merely tearing down the TCP
    session afterwards. Checked after the reset/refused text match since
    "Error reading SSH protocol banner...Connection reset by peer" is
    itself raised as an SSHException and must be classified by that more
    specific wording first.
    """
    node = exc
    seen = set()

    while node is not None and id(node) not in seen:
        seen.add(id(node))
        text = str(node)

        if isinstance(node, ConnectionResetError) or "connection reset" in text.lower():
            return (
                "Connection reset by peer. Device is reachable but actively "
                "rejected the connection (e.g. an SSH auth/algorithm "
                "mismatch, or a temporary lockout after a failed login)."
            )

        if isinstance(node, ConnectionRefusedError) or "connection refused" in text.lower():
            return (
                "Connection refused. Device is reachable but nothing "
                "accepted the connection on this port (SSH may be down, "
                "or wrong port)."
            )

        # NetmikoTimeoutException/NetmikoAuthenticationException are
        # themselves SSHException subclasses (Netmiko's own hierarchy) -
        # excluded here so this branch only fires for the *real* underlying
        # paramiko exception found deeper in the chain, not Netmiko's own
        # outer wrapper.
        if isinstance(node, SSHException) and not isinstance(
            node, (NetmikoTimeoutException, NetmikoAuthenticationException)
        ):
            return (
                f"SSH protocol/authentication rejected during connection "
                f"setup ({text!r}). Device is reachable and responded - "
                f"this is not a network timeout. A common cause on older "
                f"devices is an unsupported public key signature algorithm "
                f"(see disabled_algorithms)."
            )

        node = node.__context__ or node.__cause__

    return "Connection timeout. Device may be offline."


class BaseClient:
    """
    BaseClient provides common connection handling and logging.

    Platform-specific clients should inherit from this class
    and provide platform-specific attributes (e.g. self.device).
    """

    def __init__(
        self,
        *,
        context: ExecutionContext | None = None,
        connect_retries: int = 1,
        connect_delay: int = 1,
    ):
        # Execution context (always present)
        self.context = context or ExecutionContext()

        # Logger resolved from execution context
        self.logger = self.context.logger or logging.getLogger(__name__)

        # Connection retry configuration
        self.connect_retries = connect_retries
        self.connect_delay = connect_delay

        # Netmiko connection handle
        self.conn = None

    # -------------------------------------------------------
    # Connection handling (shared)
    # -------------------------------------------------------

    def connect(self):
        """
        Establish a Netmiko connection with retry logic.

        Expects subclass to define:
          - self.device (Netmiko connection parameters)
        """
        attempt = 1
        last_exc = None
        last_reason = "Connection timeout. Device may be offline."

        while attempt <= self.connect_retries:
            self.logger.info(
                f"Connecting to device (attempt {attempt}/{self.connect_retries})..."
            )

            try:
                self.conn = ConnectHandler(**self.device)
                self.logger.info("Connected successfully.")
                return

            except NetmikoTimeoutException as exc:
                last_exc = exc
                last_reason = _classify_connect_failure(exc)
                self.logger.warning(last_reason)

            except NetmikoAuthenticationException:
                self.logger.error("Authentication failed.")
                raise

            except Exception as exc:
                self.logger.error(f"Unexpected connection error: {exc}")
                last_exc = exc
                last_reason = _classify_connect_failure(exc)

            if attempt < self.connect_retries:
                self.logger.info(
                    f"Retrying in {self.connect_delay} seconds..."
                )
                time.sleep(self.connect_delay)

            attempt += 1

        # Retries exhausted. Always surface NetmikoTimeoutException (existing
        # callers branch on this type), but with the classified reason from
        # the last attempt in the message (not just "may be offline" for
        # every failure mode) and the real last exception chained as
        # __cause__ instead of discarded, so a caller inspecting str(exc) or
        # exc.__cause__ can tell a "device actively rejected us" failure
        # apart from a genuine "no response at all" timeout.
        raise NetmikoTimeoutException(
            f"Unable to connect after {self.connect_retries} attempts. {last_reason}"
        ) from last_exc

    def disconnect(self):
        """Close Netmiko connection if open."""
        if self.conn:
            try:
                self.conn.disconnect()
            except Exception:
                pass
            self.conn = None

    def _safe_log_info(self, msg, *args):
        """
        Best-effort self.logger.info(): swallows any exception the logger
        itself raises.

        Nautobot's Job logger runs a DB query on every call, with no
        try/except of its own — a transient DB error there can take down an
        otherwise-successful operation. Status/heartbeat logging is an
        observability concern and must never abort an operation that is
        itself succeeding — used by wait_for_reconnect() implementations and
        long-transfer progress callbacks for that reason.
        """
        try:
            self.logger.info(msg, *args)
        except Exception:
            pass
