# ShotSight 2.0

ShotSight 2.0 is a new local-first Python application for analyzing uploaded
basketball videos. The intended product reports shot attempts, makes, misses,
shooting percentage, shot locations, per-shot replays, and an annotated full
video.

The repository currently contains the approved product proposal and a minimal,
cross-platform engineering scaffold. The computer-vision pipeline is not yet
implemented. SAM 3.1 is the preferred research candidate, subject to a local
hardware and accuracy proof of concept.

## Requirements

- Python 3.12
- FFmpeg available on `PATH`
- Optional Docker
- A CUDA-compatible GPU is currently required by the official SAM 3 video
  implementation. CPU, Apple Silicon, and non-NVIDIA support require a fallback
  backend or a different tracker.

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

## Documentation

- [Product proposal](doc/proposal.md)
- [Architecture notes](doc/architecture.md)

