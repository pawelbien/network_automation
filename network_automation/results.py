from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime, timezone


@dataclass
class OperationResult:
    """
    Generic result object for all operations.

    Semantics of the operation are expressed via fields,
    not via subclassing.
    """

    success: bool
    operation: str | None = None
    message: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    started_at: datetime | None = None
    finished_at: datetime | None = None

    def mark_started(self):
        self.started_at = datetime.now(timezone.utc)

    def mark_finished(self):
        self.finished_at = datetime.now(timezone.utc)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
