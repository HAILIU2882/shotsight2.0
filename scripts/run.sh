#!/usr/bin/env sh
set -eu

.venv/bin/uvicorn shotsight2.main:app --host 127.0.0.1 --port 4173 --reload

