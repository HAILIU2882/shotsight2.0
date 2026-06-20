#!/usr/bin/env sh
set -eu

SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "${SCRIPT_DIRECTORY}")

export SHOTSIGHT_PYTHON_EXECUTABLE="${PROJECT_ROOT}/.venv/bin/python"
export SHOTSIGHT_UVICORN_EXECUTABLE="${PROJECT_ROOT}/.venv/bin/uvicorn"
exec "${SCRIPT_DIRECTORY}/run-native.sh"
