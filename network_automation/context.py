# network_automation/context.py

from dataclasses import dataclass, field
from typing import Any
import logging


@dataclass
class ExecutionContext:
    """
    ExecutionContext carries execution-scoped information and dependencies.

    It is intentionally framework-agnostic and does not depend on Nautobot,
    Celery, or CLI specifics.
    """

    logger: logging.Logger | None = None
    device_name: str | None = None
    job_id: str | None = None
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
