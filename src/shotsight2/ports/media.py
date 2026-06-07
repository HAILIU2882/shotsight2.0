"""Port for probing, normalizing, extracting, clipping, and encoding media."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from shotsight2.domain.media import (
    ClipRequest,
    ClipResult,
    EncodeResult,
    FrameExtractionRequest,
    FrameExtractionResult,
    MediaMetadata,
    MediaToolStatus,
    OverlayEncodeRequest,
    ProxyRequest,
    ProxyResult,
    RenderedFramesEncodeRequest,
)


class MediaTool(Protocol):
    """Media operations required by ingestion, analysis, and rendering."""

    def status(self) -> MediaToolStatus:
        """Report FFmpeg and ffprobe availability and versions."""

    def probe(self, source: Path) -> MediaMetadata:
        """Read normalized metadata for a decodable media source."""

    def create_proxy(self, request: ProxyRequest) -> ProxyResult:
        """Create an orientation-normalized constant-frame-rate proxy."""

    def extract_frame(self, request: FrameExtractionRequest) -> FrameExtractionResult:
        """Extract one image at the requested timestamp."""

    def create_clip(self, request: ClipRequest) -> ClipResult:
        """Create an encoded replay clip, clamped to source duration."""

    def encode_rendered_frames(self, request: RenderedFramesEncodeRequest) -> EncodeResult:
        """Encode a numbered image sequence and optional source audio."""

    def encode_overlay(self, request: OverlayEncodeRequest) -> EncodeResult:
        """Composite an overlay video over a source video."""
