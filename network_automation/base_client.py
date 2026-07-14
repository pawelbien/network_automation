# network_automation/base_client.py

import logging
import time
from network_automation.context import ExecutionContext
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from paramiko.ssh_exception import SSHException


def _classify_connect_failure(exc: Exception) -> str:
    """
    Classifies why a connection attempt failed, walking __context__ and
    __cause__ (Netmiko's own exceptions carry the underlying paramiko/
    socket error via __context__, not __cause__). Never raises; falls back
    to "may be offline" when nothing more specific is found.

    "Connection reset"/"refused" means the device actively responded and
    rejected the connection - reachable, unlike a genuine no-response
    timeout. A bare paramiko SSHException (e.g. "Invalid key", raised when
    a device rejects a public key's signature algorithm) is checked last
    since a reset/refused is itself raised as an SSHException and must be
    matched by the more specific wording first.
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

        # Netmiko's own exceptions subclass SSHException too - excluded so
        # this only fires for the real underlying paramiko exception.
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


def _summarize_reasons(reasons_by_attempt: list[tuple[int, str]]) -> str:
    """
    Reduces per-attempt classified reasons to one summary string. Different
    attempts can fail for different reasons, so the last attempt's reason
    alone isn't necessarily the most informative one - all distinct reasons
    are kept, labeled by attempt number, instead of only the last.
    """
    unique_reasons = []
    seen = set()
    for _, reason in reasons_by_attempt:
        if reason not in seen:
            seen.add(reason)
            unique_reasons.append(reason)

    if not unique_reasons:
        return "Connection timeout. Device may be offline."
    if len(unique_reasons) == 1:
        return unique_reasons[0]

    return " | ".join(
        f"attempt {n}: {reason}" for n, reason in reasons_by_attempt
    )


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
        reasons_by_attempt = []

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
                reason = _classify_connect_failure(exc)
                reasons_by_attempt.append((attempt, reason))
                self.logger.warning(reason)

            except NetmikoAuthenticationException:
                self.logger.error("Authentication failed.")
                raise

            except Exception as exc:
                self.logger.error(f"Unexpected connection error: {exc}")
                last_exc = exc
                reasons_by_attempt.append((attempt, _classify_connect_failure(exc)))

            if attempt < self.connect_retries:
                self.logger.info(
                    f"Retrying in {self.connect_delay} seconds..."
                )
                time.sleep(self.connect_delay)

            attempt += 1

        # Always surface NetmikoTimeoutException (existing callers branch on
        # this type), with the classified reason(s) in the message and the
        # real last exception chained as __cause__ instead of discarded.
        raise NetmikoTimeoutException(
            f"Unable to connect after {self.connect_retries} attempts. "
            f"{_summarize_reasons(reasons_by_attempt)}"
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
