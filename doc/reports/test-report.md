# Test Report

## Baseline

- Date: 2026-06-07
- Platform: macOS on Apple Silicon
- Python: 3.12
- Result before environment resynchronization:
  - `mypy --strict`: passed.
  - `ruff check`: passed.
  - `pytest`: collection blocked because the editable package link was missing.
  - `ruff format --check`: seven existing Python files required formatting.
- Corrective environment actions:
  - `uv sync --all-extras`
  - `uv pip install --python .venv/bin/python -e '.[vision,dev]'`
- Rerun result:
  - `mypy --strict`: passed.
  - `ruff check`: passed.
  - `pytest` and coverage: still blocked because the generated editable `.pth`
    file is present but is not added to `sys.path` by this local Python
    environment.
  - `ruff format --check`: the same seven initial scaffold files require
    formatting.

The first owning foundation module must repair the package/test configuration
and baseline formatting before its module can pass the quality gate.

## Environment Validation

- Docker CLI `29.5.3` and Colima `0.10.3` installed successfully with Homebrew.
- Colima started with 4 CPUs, 8 GB memory, and a 40 GB requested disk profile.
- Baseline Docker image `shotsight2:baseline` built successfully.
- Temporary container health response on port `4174`:
  `{"status":"ok","environment":"development","sam3_enabled":false}`.

## Required Real-Video Fixture

- Path: `/Users/hailiu/Desktop/bball_pt2.mov`
- Container: QuickTime/MOV
- Video codec: H.264
- Resolution: 640x360
- Frame rate: 60 FPS
- Duration: 91.228 seconds
- Size: 44,784,379 bytes
- Repository policy: external fixture; never copied or committed.

## Completed Module Validation

### Artifact Store

- Merged to `main` on 2026-06-07.
- 17 module tests passed.
- Independent coverage result: 94.41%.
- `mypy --strict`, Ruff lint, and module formatting checks passed.
- Diff and filesystem safety behavior were reviewed before merge.

### Media Processing

- Merged to `main` on 2026-06-07.
- 22 module tests passed against generated FFmpeg fixtures.
- Independent coverage result: 93.84%.
- `mypy --strict`, Ruff lint, and module formatting checks passed.
- FFmpeg subprocess, atomic-output, and diagnostic behavior were reviewed
  before merge.
