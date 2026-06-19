#!/usr/bin/env sh
set -eu

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[vision,dev]"

printf '%s\n' "ShotSight 2.0 environment created in .venv"

