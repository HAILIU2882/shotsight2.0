#!/usr/bin/env python3
"""Serve a local browser tool for human shot-release annotation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import os
import subprocess
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

DEFAULT_VIDEO = Path("/Users/hailiu/Desktop/bball_pt2.mov")
MAX_REQUEST_BYTES = 2 * 1024 * 1024
VALID_OUTCOMES = frozenset({"MADE", "MISSED", "UNOBSERVABLE"})


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Metadata required for frame-accurate annotation controls."""

    duration_seconds: float
    fps: float
    frame_count: int
    sha256: str

    @property
    def max_frame_index(self) -> int:
        """Return the final valid zero-based frame index."""

        return max(0, self.frame_count - 1)

    def to_json(self) -> dict[str, object]:
        """Return browser-safe metadata."""

        return {
            "duration_seconds": self.duration_seconds,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ByteRange:
    """Inclusive byte range from an HTTP Range request."""

    start: int
    end: int


def parse_fraction(value: str) -> float:
    """Parse an ffprobe numeric or fractional value."""

    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(numerator)
    denominator_value = float(denominator)
    if denominator_value == 0:
        raise ValueError("Frame-rate denominator cannot be zero")
    return float(numerator) / denominator_value


def probe_video(video_path: Path, *, ffprobe: str = "ffprobe") -> VideoMetadata:
    """Read duration and frame rate with ffprobe and hash the source video."""

    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate,avg_frame_rate,nb_frames:format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        raise ValueError("ffprobe did not return a video stream")
    stream = streams[0]
    format_data = payload.get("format", {})
    if not isinstance(format_data, dict):
        raise ValueError("ffprobe did not return format metadata")
    fps = 0.0
    for value in (stream.get("r_frame_rate"), stream.get("avg_frame_rate")):
        try:
            candidate = parse_fraction(str(value))
        except ValueError:
            continue
        if math.isfinite(candidate) and candidate > 0:
            fps = candidate
            break
    duration = float(format_data.get("duration", 0.0))
    if not math.isfinite(fps) or not math.isfinite(duration) or fps <= 0 or duration <= 0:
        raise ValueError("Video duration and frame rate must be positive")
    frame_value = stream.get("nb_frames")
    frame_count = int(frame_value) if isinstance(frame_value, str) and frame_value.isdigit() else round(duration * fps)
    if frame_count <= 0:
        raise ValueError("Video frame count must be positive")
    return VideoMetadata(duration, fps, frame_count, sha256_file(video_path))


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return a streaming SHA-256 digest without loading the video into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def parse_range_header(header: str | None, file_size: int) -> ByteRange | None:
    """Parse one RFC 7233 byte range; reject malformed or multiple ranges."""

    if header is None:
        return None
    if not header.startswith("bytes=") or file_size <= 0:
        raise ValueError("Unsupported Range header")
    value = header.removeprefix("bytes=")
    if "," in value:
        raise ValueError("Multiple byte ranges are not supported")
    start_text, separator, end_text = value.partition("-")
    if not separator:
        raise ValueError("Malformed byte range")
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Suffix byte range must be positive")
        return ByteRange(max(0, file_size - suffix_length), file_size - 1)
    start = int(start_text)
    end = int(end_text) if end_text else file_size - 1
    if start < 0 or start >= file_size or end < start:
        raise ValueError("Byte range is outside the video")
    return ByteRange(start, min(end, file_size - 1))


def validate_annotation_document(payload: Any, metadata: VideoMetadata) -> dict[str, object]:
    """Validate and normalize a ground-truth document before persistence."""

    if not isinstance(payload, dict):
        raise ValueError("Annotation payload must be a JSON object")
    source = payload.get("source")
    if source is not None:
        if not isinstance(source, dict):
            raise ValueError("Annotation source must be an object")
        source_sha256 = source.get("sha256")
        if source_sha256 is not None and source_sha256 != metadata.sha256:
            raise ValueError("Annotation source does not match the selected video")
    attempts = payload.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("Annotation payload must contain an attempts list")
    normalized_attempts: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            raise ValueError(f"Attempt {index} must be an object")
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise ValueError(f"Attempt {index} must have a non-empty attempt_id")
        if attempt_id in seen_ids:
            raise ValueError(f"Duplicate attempt_id: {attempt_id}")
        seen_ids.add(attempt_id)
        release_value = attempt.get("release_seconds")
        if isinstance(release_value, bool) or not isinstance(release_value, int | float):
            raise ValueError(f"Attempt {attempt_id} must have numeric release_seconds")
        release_seconds = float(release_value)
        if not math.isfinite(release_seconds) or not 0 <= release_seconds <= metadata.duration_seconds:
            raise ValueError(f"Attempt {attempt_id} release_seconds is outside the video")
        frame_value = attempt.get("release_frame")
        if frame_value is None:
            release_frame = min(metadata.max_frame_index, round(release_seconds * metadata.fps))
        elif isinstance(frame_value, bool) or not isinstance(frame_value, int):
            raise ValueError(f"Attempt {attempt_id} release_frame must be an integer")
        else:
            release_frame = frame_value
        if not 0 <= release_frame <= metadata.max_frame_index:
            raise ValueError(f"Attempt {attempt_id} release_frame is outside the video")
        frame_seconds = release_frame / metadata.fps
        if abs(frame_seconds - release_seconds) > (0.5 / metadata.fps) + 1e-9:
            raise ValueError(f"Attempt {attempt_id} release time and frame disagree")
        outcome_value = attempt.get("outcome")
        if not isinstance(outcome_value, str) or outcome_value.upper() not in VALID_OUTCOMES:
            raise ValueError(f"Attempt {attempt_id} outcome must be MADE, MISSED, or UNOBSERVABLE")
        notes_value = attempt.get("notes", "")
        if not isinstance(notes_value, str):
            raise ValueError(f"Attempt {attempt_id} notes must be text")
        normalized_attempts.append(
            {
                "attempt_id": attempt_id,
                "release_seconds": round(frame_seconds, 9),
                "release_frame": release_frame,
                "outcome": outcome_value.upper(),
                "notes": notes_value,
            }
        )
    normalized_attempts.sort(key=lambda item: (cast(float, item["release_seconds"]), cast(str, item["attempt_id"])))
    return {
        "schema_version": "1.0",
        "source": {
            "sha256": metadata.sha256,
            "duration_seconds": metadata.duration_seconds,
            "fps": metadata.fps,
            "frame_count": metadata.frame_count,
        },
        "attempts": normalized_attempts,
    }


def ensure_output_outside_repository(output_path: Path, repository_root: Path) -> None:
    """Reject output inside the Git repository to prevent accidental label commits."""

    output = output_path.expanduser().resolve()
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        raise ValueError(f"Annotation output must be outside the repository: {repository}")


def write_annotations(path: Path, document: dict[str, object]) -> None:
    """Atomically write an annotation document to its configured local path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def empty_document(metadata: VideoMetadata) -> dict[str, object]:
    """Return an empty schema-compatible annotation document."""

    return validate_annotation_document({"attempts": []}, metadata)


def build_handler(
    video_path: Path,
    output_path: Path,
    metadata: VideoMetadata,
) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one video and one output document."""

    class AnnotationHandler(BaseHTTPRequestHandler):
        server_version = "ShotSightAnnotation/1.0"

        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/":
                self._send_bytes(HTTPStatus.OK, ANNOTATION_HTML.encode(), "text/html; charset=utf-8")
            elif route == "/metadata":
                payload = {
                    **metadata.to_json(),
                    "video_name": video_path.name,
                    "output_path": str(output_path),
                }
                self._send_json(HTTPStatus.OK, payload)
            elif route == "/annotations":
                if output_path.exists():
                    try:
                        document = validate_annotation_document(
                            json.loads(output_path.read_text(encoding="utf-8")), metadata
                        )
                    except (OSError, json.JSONDecodeError, ValueError) as error:
                        self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
                        return
                else:
                    document = empty_document(metadata)
                self._send_json(HTTPStatus.OK, document)
            elif route == "/video":
                self._serve_video(head_only=False)
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_HEAD(self) -> None:  # noqa: N802
            if urlparse(self.path).path == "/video":
                self._serve_video(head_only=True)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/annotations":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid Content-Length"})
                return
            if not 0 < content_length <= MAX_REQUEST_BYTES:
                self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Annotation payload is too large"})
                return
            try:
                payload = json.loads(self.rfile.read(content_length))
                document = validate_annotation_document(payload, metadata)
                write_annotations(output_path, document)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
                return
            self._send_json(HTTPStatus.OK, {"status": "saved", "output_path": str(output_path)})

        def log_message(self, format_string: str, *args: object) -> None:
            """Keep useful local request logs while satisfying the typed handler API."""

            print(f"{self.address_string()} - {format_string % args}")

        def _serve_video(self, *, head_only: bool) -> None:
            file_size = video_path.stat().st_size
            try:
                selected_range = parse_range_header(self.headers.get("Range"), file_size)
            except (TypeError, ValueError):
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return
            byte_range = selected_range or ByteRange(0, file_size - 1)
            status = HTTPStatus.PARTIAL_CONTENT if selected_range else HTTPStatus.OK
            length = byte_range.end - byte_range.start + 1
            self.send_response(status)
            content_type = mimetypes.guess_type(video_path.name)[0] or "application/octet-stream"
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if selected_range:
                self.send_header("Content-Range", f"bytes {byte_range.start}-{byte_range.end}/{file_size}")
            self.end_headers()
            if head_only:
                return
            with video_path.open("rb") as source:
                source.seek(byte_range.start)
                remaining = length
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)

        def _send_json(self, status: HTTPStatus, payload: object) -> None:
            self._send_bytes(status, json.dumps(payload).encode(), "application/json")

        def _send_bytes(self, status: HTTPStatus, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    return AnnotationHandler


def create_server(
    video_path: Path,
    output_path: Path,
    metadata: VideoMetadata,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Create, but do not start, the local annotation HTTP server."""

    return ThreadingHTTPServer((host, port), build_handler(video_path, output_path, metadata))


def main() -> int:
    """Run the annotation server until interrupted."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open the default browser")
    args = parser.parse_args()
    video_path = args.video.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[1]
    if not video_path.is_file():
        parser.error(f"Video does not exist: {video_path}")
    try:
        ensure_output_outside_repository(output_path, repository_root)
        metadata = probe_video(video_path)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        parser.error(str(error))
    server = create_server(video_path, output_path, metadata, host=args.host, port=args.port)
    url = f"http://{args.host}:{server.server_port}/"
    print(f"Annotating: {video_path}")
    print(f"Saving labels to: {output_path}")
    print(f"Open: {url}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAnnotation server stopped.")
    finally:
        server.server_close()
    return 0


ANNOTATION_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ShotSight Ground Truth</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; background: #111; color: #f4f4f4; }
    body { margin: 0; }
    header, main { width: min(1180px, calc(100% - 32px)); margin: 0 auto; }
    header { padding: 18px 0 10px; }
    h1 { font-size: 24px; margin: 0 0 6px; }
    .muted { color: #aaa; font-size: 13px; overflow-wrap: anywhere; }
    video { width: 100%; max-height: 62vh; background: #000; margin-top: 12px; }
    .toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; padding: 12px 0; }
    label { display: grid; gap: 4px; font-size: 12px; color: #bbb; }
    input, select, button {
      min-height: 36px; border: 1px solid #555; background: #202020; color: white; padding: 6px 9px;
    }
    button { cursor: pointer; }
    button:hover { background: #303030; }
    .made { border-color: #55b86a; }
    .missed { border-color: #e56b62; }
    .unknown { border-color: #d6aa4c; }
    .save { margin-left: auto; background: #1f5f8b; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
    th, td { border-bottom: 1px solid #333; padding: 7px 5px; text-align: left; }
    td input, td select { width: calc(100% - 20px); }
    .status { min-height: 24px; color: #8fd49e; }
  </style>
</head>
<body>
  <header>
    <h1>ShotSight Ground-Truth Annotation</h1>
    <div id="source" class="muted"></div>
    <div id="output" class="muted"></div>
  </header>
  <main>
    <video id="video" src="/video" controls preload="metadata"></video>
    <div class="toolbar">
      <button id="back10" title="Back 10 frames">-10f</button>
      <button id="back1" title="Back one frame">-1f</button>
      <button id="forward1" title="Forward one frame">+1f</button>
      <button id="forward10" title="Forward 10 frames">+10f</button>
      <label>Time (seconds)<input id="time" type="number" min="0" step="0.000001"></label>
      <label>Frame<input id="frame" type="number" min="0" step="1"></label>
      <button class="made" data-outcome="MADE">Record MADE</button>
      <button class="missed" data-outcome="MISSED">Record MISSED</button>
      <button class="unknown" data-outcome="UNOBSERVABLE">Record UNOBSERVABLE</button>
      <button id="save" class="save">Save JSON</button>
    </div>
    <div id="status" class="status"></div>
    <table>
      <thead>
        <tr><th>ID</th><th>Release seconds</th><th>Frame</th><th>Outcome</th><th>Notes</th><th>Actions</th></tr>
      </thead>
      <tbody id="attempts"></tbody>
    </table>
  </main>
  <script>
    const video = document.querySelector('#video');
    const timeInput = document.querySelector('#time');
    const frameInput = document.querySelector('#frame');
    const rows = document.querySelector('#attempts');
    const status = document.querySelector('#status');
    let metadata;
    let attempts = [];

    const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
    const escapeAttribute = value => String(value)
      .replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    const frameAt = seconds => clamp(Math.round(seconds * metadata.fps), 0, metadata.frame_count - 1);
    const secondsAt = frame => frame / metadata.fps;
    const seek = seconds => {
      video.pause();
      video.currentTime = clamp(seconds, 0, metadata.duration_seconds);
      syncPosition();
    };
    const syncPosition = () => {
      if (!metadata) return;
      timeInput.value = video.currentTime.toFixed(6);
      frameInput.value = String(frameAt(video.currentTime));
    };
    const nextId = () => {
      const used = new Set(attempts.map(item => item.attempt_id));
      let number = 1;
      while (used.has(`shot-${String(number).padStart(3, '0')}`)) number += 1;
      return `shot-${String(number).padStart(3, '0')}`;
    };
    const render = () => {
      attempts.sort((a, b) => a.release_seconds - b.release_seconds || a.attempt_id.localeCompare(b.attempt_id));
      rows.replaceChildren(...attempts.map((attempt, index) => {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td><input data-field="attempt_id" value="${escapeAttribute(attempt.attempt_id)}"></td>
          <td><input data-field="release_seconds" type="number" min="0" step="0.000001"
            value="${attempt.release_seconds.toFixed(6)}"></td>
          <td><input data-field="release_frame" type="number" min="0" step="1" value="${attempt.release_frame}"></td>
          <td><select data-field="outcome">
            <option>MADE</option><option>MISSED</option><option>UNOBSERVABLE</option>
          </select></td>
          <td><input data-field="notes" value=""></td>
          <td><button data-action="seek">Seek</button> <button data-action="delete">Delete</button></td>`;
        row.querySelector('[data-field="outcome"]').value = attempt.outcome;
        row.querySelector('[data-field="notes"]').value = attempt.notes || '';
        row.addEventListener('change', event => {
          const field = event.target.dataset.field;
          if (field === 'release_frame') {
            attempt.release_frame = clamp(Math.round(Number(event.target.value)), 0, metadata.frame_count - 1);
            attempt.release_seconds = secondsAt(attempt.release_frame);
          } else if (field === 'release_seconds') {
            attempt.release_frame = frameAt(Number(event.target.value));
            attempt.release_seconds = secondsAt(attempt.release_frame);
          }
          else if (field) attempt[field] = event.target.value;
          render();
        });
        row.querySelector('[data-action="seek"]').onclick = () => seek(attempt.release_seconds);
        row.querySelector('[data-action="delete"]').onclick = () => { attempts.splice(index, 1); render(); };
        return row;
      }));
    };
    const record = outcome => {
      const releaseFrame = frameAt(video.currentTime);
      attempts.push({
        attempt_id: nextId(), release_seconds: secondsAt(releaseFrame), release_frame: releaseFrame, outcome, notes: ''
      });
      render();
      status.textContent = `${outcome} recorded at frame ${releaseFrame}. Save when ready.`;
    };
    const save = async () => {
      const response = await fetch('/annotations', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({attempts})
      });
      const payload = await response.json();
      status.textContent = response.ok ? `Saved to ${payload.output_path}` : `Not saved: ${payload.error}`;
    };

    const fetchJson = async path => {
      const response = await fetch(path);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
      return payload;
    };
    Promise.all([fetchJson('/metadata'), fetchJson('/annotations')])
      .then(([loadedMetadata, annotationDocument]) => {
        metadata = loadedMetadata;
        attempts = annotationDocument.attempts || [];
        const sourceSummary = `${metadata.video_name} | ${metadata.fps.toFixed(3)} fps | `
          + `${metadata.duration_seconds.toFixed(3)}s`;
        document.querySelector('#source').textContent = sourceSummary;
        document.querySelector('#output').textContent = `Output: ${metadata.output_path}`;
        timeInput.max = metadata.duration_seconds;
        frameInput.max = metadata.frame_count - 1;
        render(); syncPosition();
      })
      .catch(error => { status.textContent = `Unable to load annotations: ${error.message}`; });
    video.addEventListener('timeupdate', syncPosition);
    video.addEventListener('seeked', syncPosition);
    timeInput.addEventListener('change', () => seek(Number(timeInput.value)));
    frameInput.addEventListener('change', () => seek(secondsAt(Number(frameInput.value))));
    document.querySelector('#back10').onclick = () => seek(video.currentTime - 10 / metadata.fps);
    document.querySelector('#back1').onclick = () => seek(video.currentTime - 1 / metadata.fps);
    document.querySelector('#forward1').onclick = () => seek(video.currentTime + 1 / metadata.fps);
    document.querySelector('#forward10').onclick = () => seek(video.currentTime + 10 / metadata.fps);
    document.querySelectorAll('[data-outcome]').forEach(button => {
      button.onclick = () => record(button.dataset.outcome);
    });
    document.querySelector('#save').onclick = save;
    document.addEventListener('keydown', event => {
      if (event.target.matches('input, select')) return;
      if (event.key === 'ArrowLeft') seek(video.currentTime - 1 / metadata.fps);
      if (event.key === 'ArrowRight') seek(video.currentTime + 1 / metadata.fps);
      if (event.key.toLowerCase() === 'm') record('MADE');
      if (event.key.toLowerCase() === 'x') record('MISSED');
      if (event.key.toLowerCase() === 'u') record('UNOBSERVABLE');
    });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
