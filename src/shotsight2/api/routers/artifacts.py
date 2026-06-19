"""Safe artifact streaming route with range-request support."""

from __future__ import annotations

import re
from collections.abc import Generator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from shotsight2.api.deps import get_artifact_store
from shotsight2.domain.artifacts import ArtifactId
from shotsight2.ports.artifacts import ArtifactStore, ArtifactStoreError, InvalidArtifactIdError, UnknownArtifactError

router = APIRouter(tags=["artifacts"])

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)$")
_CHUNK = 64 * 1024  # 64 KiB streaming chunks


@router.get("/artifacts/{artifact_id:path}")
def stream_artifact(
    artifact_id: str,
    store: Annotated[ArtifactStore, Depends(get_artifact_store)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> StreamingResponse:
    """Stream an artifact with optional HTTP range-request support.

    Returns 200 for full content, 206 for a satisfied range, 416 for an
    unsatisfiable range, and 404 when the artifact does not exist.
    The artifact_id is validated by the store — no path-traversal is possible.
    """
    artifact_id_obj = ArtifactId(artifact_id)
    try:
        metadata = store.metadata(artifact_id_obj)
    except InvalidArtifactIdError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid artifact identifier: {exc}") from exc
    except UnknownArtifactError:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id!r} not found") from None
    except ArtifactStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    total = metadata.size_bytes
    media_type = metadata.media_type or "application/octet-stream"

    if range_header is not None:
        m = _RANGE_RE.match(range_header.strip())
        if m is None:
            raise HTTPException(status_code=416, detail="Invalid Range header format")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else total - 1
        if start > end or end >= total:
            raise HTTPException(
                status_code=416,
                detail="Range not satisfiable",
                headers={"Content-Range": f"bytes */{total}"},
            )
        length = end - start + 1
        return StreamingResponse(
            _ranged_stream(store, artifact_id_obj, start, length),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(length),
                "Accept-Ranges": "bytes",
            },
        )

    return StreamingResponse(
        _full_stream(store, artifact_id_obj),
        status_code=200,
        media_type=media_type,
        headers={
            "Content-Length": str(total),
            "Accept-Ranges": "bytes",
        },
    )


def _full_stream(store: ArtifactStore, artifact_id: ArtifactId) -> Generator[bytes, None, None]:
    with store.open_read(artifact_id) as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            yield chunk


def _ranged_stream(
    store: ArtifactStore, artifact_id: ArtifactId, start: int, length: int
) -> Generator[bytes, None, None]:
    remaining = length
    with store.open_read(artifact_id) as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(_CHUNK, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)
