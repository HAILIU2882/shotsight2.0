"""Storage-neutral messages exchanged with the local analysis worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class QueueMessage:
    """Identifier-only payload for one durable analysis job."""

    job_id: str
    video_id: str
    run_id: str

    def __post_init__(self) -> None:
        """Reject empty identifiers at the process boundary."""
        if not self.job_id or not self.video_id or not self.run_id:
            raise ValueError("Queue message identifiers must not be empty")


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """A queue message currently owned by one worker."""

    message: QueueMessage
    worker_id: str
    claimed_at: datetime
