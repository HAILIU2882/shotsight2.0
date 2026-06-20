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

The OpenCV fallback and Apple Silicon MLX SAM 3 paths are implemented. Official
SAM 3.1 CUDA validation remains optional and requires a compatible NVIDIA host.

### Apple Silicon MLX SAM 3

The MLX port requires Python 3.13, so it uses a dedicated environment rather
than the default Python 3.12 `.venv`. Set it up and run ShotSight with:

```sh
./scripts/setup-mlx.sh
./scripts/run-mlx.sh
```

The first real inference downloads approximately 3.5 GB of public weights from
`mlx-community/sam3-image`. The installed distribution is named `mlx-sam3`,
but its Python import is `sam3`; ShotSight's backend probe accounts for that
upstream naming difference. The setup script keeps a pinned, ignored checkout
under `vendor/mlx_sam3` because the upstream wheel currently omits a required
tokenizer asset. Python 3.13 can skip executable editable-install hooks inside
the Finder-hidden `.venv-mlx`, so the setup validation and run script export
the project `src` directory and pinned MLX source explicitly. This makes imports
reliable from outside the repository without depending on `.pth` processing.
Neither the ignored checkout nor downloaded model weights are committed. Rerun
setup after moving the repository or changing dependencies.
The MLX port performs image inference on sampled video frames, while ShotSight
owns temporal identity and trajectory filtering.

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

Use `http://127.0.0.1:4173/health` for web-process liveness. It intentionally
returns HTTP 200 even when the separate analysis worker is absent, so process
supervisors do not restart a healthy web server in a loop. Use
`http://127.0.0.1:4173/ready` for product readiness: it returns HTTP 200 only
when SQLite and the queue are available and at least one non-stopped worker has
a heartbeat newer than `SHOTSIGHT_WORKER_READINESS_STALE_SECONDS` (30 seconds
by default). Missing, stale, stopped, or unknown worker state returns HTTP 503
with structured database, queue, and worker details.

Both native launchers supervise two processes: the FastAPI web server and the
independent analysis worker. Stop them together with `Ctrl-C`. For debugging,
the equivalent manual two-terminal commands are:

```sh
PYTHONPATH=src .venv/bin/python -m shotsight2.worker
PYTHONPATH=src .venv/bin/uvicorn shotsight2.main:app --host 127.0.0.1 --port 4173
```

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
