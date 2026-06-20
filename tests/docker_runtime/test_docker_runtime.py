"""Protect the optional CPU container deployment from configuration regressions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_image_installs_cpu_vision_runtime_without_local_source_copy() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'pip install --no-cache-dir ".[vision]"' in dockerfile
    assert "COPY migrations" not in dockerfile
    assert "ffmpeg" in dockerfile
    assert "USER shotsight" in dockerfile
    assert "COPY . ." not in dockerfile


def test_build_context_excludes_local_state_and_model_weights() -> None:
    ignored = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert {".venv*", "worktrees", "vendor", "data"} <= ignored
    assert {"*.pt", "*.pth", "*.onnx", "*.safetensors"} <= ignored
    assert {"*.mp4", "*.mov", "*.avi", "*.mkv"} <= ignored


def test_compose_runs_web_and_standard_worker_with_shared_storage() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  web:\n" in compose
    assert "  worker:\n" in compose
    assert 'command: ["shotsight-worker"]' in compose
    assert "--handler" not in compose
    assert compose.count("shotsight-data:/app/data") == 2
    assert "sqlite:////app/data/database/shotsight2.db" in compose
    assert compose.count("healthcheck:") == 2


def test_smoke_script_accepts_compose_plugin_or_standalone_command() -> None:
    smoke_script = (ROOT / "scripts" / "docker-smoke.sh").read_text(encoding="utf-8")

    assert "docker compose version" in smoke_script
    assert "command -v docker-compose" in smoke_script
    assert "up --detach --wait --wait-timeout 120" in smoke_script
