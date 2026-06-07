"""FFmpeg-backed implementation of the media processing port."""

from shotsight2.adapters.ffmpeg.adapter import FFmpegAdapter, FFmpegAdapterConfig
from shotsight2.adapters.ffmpeg.errors import (
    MediaDiagnostic,
    MediaErrorCategory,
    MediaProcessingError,
)

__all__ = [
    "FFmpegAdapter",
    "FFmpegAdapterConfig",
    "MediaDiagnostic",
    "MediaErrorCategory",
    "MediaProcessingError",
]
