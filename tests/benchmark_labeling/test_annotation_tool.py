from __future__ import annotations

import json
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import cast

import pytest

from scripts.annotate_shots import (
    ANNOTATION_HTML,
    ByteRange,
    VideoMetadata,
    build_handler,
    ensure_output_outside_repository,
    parse_range_header,
    validate_annotation_document,
)


def test_annotation_document_uses_frame_as_the_stable_release_position() -> None:
    metadata = VideoMetadata(duration_seconds=2.0, fps=10.0, frame_count=20, sha256="video-hash")

    document = validate_annotation_document(
        {
            "source": {"sha256": "video-hash"},
            "attempts": [
                {
                    "attempt_id": "shot-001",
                    "release_seconds": 0.51,
                    "release_frame": 5,
                    "outcome": "made",
                    "notes": "clean view",
                }
            ],
        },
        metadata,
    )

    assert document["attempts"] == [
        {
            "attempt_id": "shot-001",
            "release_seconds": 0.5,
            "release_frame": 5,
            "outcome": "MADE",
            "notes": "clean view",
        }
    ]


def test_annotation_document_rejects_wrong_video_and_inconsistent_frame() -> None:
    metadata = VideoMetadata(duration_seconds=2.0, fps=10.0, frame_count=20, sha256="video-hash")

    with pytest.raises(ValueError, match="does not match"):
        validate_annotation_document({"source": {"sha256": "other"}, "attempts": []}, metadata)
    with pytest.raises(ValueError, match="time and frame disagree"):
        validate_annotation_document(
            {
                "attempts": [
                    {
                        "attempt_id": "shot-001",
                        "release_seconds": 1.5,
                        "release_frame": 5,
                        "outcome": "MISSED",
                    }
                ]
            },
            metadata,
        )


def test_annotation_output_must_be_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()

    with pytest.raises(ValueError, match="outside the repository"):
        ensure_output_outside_repository(repository / "labels.json", repository)
    ensure_output_outside_repository(tmp_path / "labels.json", repository)


def test_range_parser_supports_browser_video_requests() -> None:
    assert parse_range_header("bytes=2-5", 10) == ByteRange(2, 5)
    assert parse_range_header("bytes=-3", 10) == ByteRange(7, 9)
    assert parse_range_header("bytes=8-", 10) == ByteRange(8, 9)
    with pytest.raises(ValueError, match="outside"):
        parse_range_header("bytes=10-", 10)


def test_local_server_streams_video_and_persists_annotations(tmp_path: Path) -> None:
    video = tmp_path / "fixture.mov"
    video.write_bytes(b"0123456789")
    output = tmp_path / "labels" / "fixture.json"
    metadata = VideoMetadata(duration_seconds=1.0, fps=10.0, frame_count=10, sha256="video-hash")
    handler = build_handler(video, output, metadata)

    response = _request(handler, b"GET /video HTTP/1.1\r\nHost: localhost\r\nRange: bytes=2-5\r\n\r\n")
    headers, body = response.split(b"\r\n\r\n", maxsplit=1)
    assert f" {HTTPStatus.PARTIAL_CONTENT.value} ".encode() in headers.splitlines()[0]
    assert b"Content-Range: bytes 2-5/10" in headers
    assert body == b"2345"

    body = json.dumps(
        {
            "attempts": [
                {
                    "attempt_id": "shot-001",
                    "release_seconds": 0.5,
                    "release_frame": 5,
                    "outcome": "UNOBSERVABLE",
                    "notes": "rim hidden",
                }
            ]
        }
    ).encode()
    response = _request(
        handler,
        b"POST /annotations HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body,
    )
    assert f" {HTTPStatus.OK.value} ".encode() in response.splitlines()[0]

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["source"]["sha256"] == "video-hash"
    assert saved["attempts"][0]["outcome"] == "UNOBSERVABLE"


def test_page_loads_annotation_document_without_shadowing_browser_document() -> None:
    assert "annotationDocument.attempts" in ANNOTATION_HTML
    assert "[metadata, document]" not in ANNOTATION_HTML
    assert 'data-outcome="UNOBSERVABLE"' in ANNOTATION_HTML


def _request(handler: type[BaseHTTPRequestHandler], request: bytes) -> bytes:
    client, server = socket.socketpair()
    try:
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        handler(server, ("127.0.0.1", 1), cast(HTTPServer, object()))
        server.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while chunk := client.recv(4096):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        client.close()
        server.close()
