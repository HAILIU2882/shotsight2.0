# ShotSight 2.0

ShotSight 2.0 is a new local-first Python application for analyzing uploaded
basketball videos. The intended product reports shot attempts, makes, misses,
shooting percentage, shot locations, per-shot replays, and an annotated full
video.

The repository now contains the local FastAPI application, SQLite persistence,
filesystem artifact storage, upload/reanalysis/review/deletion services,
server-rendered bilingual UI, OpenCV fallback tracking contracts, and tested
analysis pipeline boundaries.

Some model-quality gates are intentionally still blocked until approved local
model runtimes and ground-truth labels are available. See
`doc/reports/blocked.md` and `doc/tasks/progress.md` for the current release
status.

## Requirements

- Python 3.12
- FFmpeg available on `PATH`
- Optional Docker
- Optional SAM/MLX model runtimes and authorized weights for advanced tracking
  validation.

The OpenCV fallback path and backend interfaces are implemented. Real MLX/SAM
benchmark validation remains blocked without the optional runtime/weights.

## Local Setup

macOS/Linux:

```sh
cp .env.example .env
./scripts/bootstrap.sh
./scripts/run.sh
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
./scripts/bootstrap.ps1
./scripts/run.ps1
```

Open `http://127.0.0.1:4173/health`.

Run the quality gates:

```sh
PYTHONPATH=src .venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80
PYTHONPATH=src .venv/bin/mypy --strict src tests
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
```

## Documentation

- [Product proposal](doc/proposal.md)
- [Architecture notes](doc/architecture.md)
- [Detailed design](doc/detailed-design.md)
- [Progress and release gates](doc/tasks/progress.md)
- [Blocked work](doc/reports/blocked.md)
