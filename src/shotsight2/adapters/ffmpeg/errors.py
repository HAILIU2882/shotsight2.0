"""Structured errors raised by the FFmpeg media adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaErrorCategory(StrEnum):
    """Stable failure categories suitable for application error handling."""

    DEPENDENCY_MISSING = "dependency_missing"
    INVALID_REQUEST = "invalid_request"
    SOURCE_NOT_FOUND = "source_not_found"
    DESTINATION_EXISTS = "destination_exists"
    UNSUPPORTED_OR_CORRUPT = "unsupported_or_corrupt"
    DISK_SPACE = "disk_space"
    TIMEOUT = "timeout"
    SUBPROCESS_FAILED = "subprocess_failed"
    OUTPUT_INVALID = "output_invalid"


@dataclass(frozen=True, slots=True)
class MediaDiagnostic:
    """Machine-readable diagnostics for a failed media operation."""

    category: MediaErrorCategory
    operation: str
    message: str
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    stderr: str = ""


class MediaProcessingError(RuntimeError):
    """Media operation failure with structured diagnostics."""

    def __init__(self, diagnostic: MediaDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
