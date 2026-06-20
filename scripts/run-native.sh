#!/usr/bin/env sh
set -eu

SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "${SCRIPT_DIRECTORY}")
cd "${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

PYTHON_EXECUTABLE=${SHOTSIGHT_PYTHON_EXECUTABLE:-.venv/bin/python}
UVICORN_EXECUTABLE=${SHOTSIGHT_UVICORN_EXECUTABLE:-.venv/bin/uvicorn}
HOST=${SHOTSIGHT_HOST:-127.0.0.1}
PORT=${SHOTSIGHT_PORT:-4173}

if [ ! -x "${PYTHON_EXECUTABLE}" ] || [ ! -x "${UVICORN_EXECUTABLE}" ]; then
  printf '%s\n' "ShotSight environment is missing. Run the matching setup script first." >&2
  exit 1
fi

worker_pid=
web_pid=

stop_processes() {
  trap - EXIT INT TERM
  if [ -n "${web_pid}" ]; then
    kill "${web_pid}" 2>/dev/null || true
  fi
  if [ -n "${worker_pid}" ]; then
    kill "${worker_pid}" 2>/dev/null || true
  fi
  if [ -n "${web_pid}" ]; then
    wait "${web_pid}" 2>/dev/null || true
  fi
  if [ -n "${worker_pid}" ]; then
    wait "${worker_pid}" 2>/dev/null || true
  fi
}

trap stop_processes EXIT INT TERM

"${PYTHON_EXECUTABLE}" -m shotsight2.worker &
worker_pid=$!
"${UVICORN_EXECUTABLE}" shotsight2.main:app --host "${HOST}" --port "${PORT}" &
web_pid=$!

printf '%s\n' "ShotSight web: http://${HOST}:${PORT}"
printf '%s\n' "Analysis worker PID: ${worker_pid}"

exit_status=0
while kill -0 "${worker_pid}" 2>/dev/null && kill -0 "${web_pid}" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "${worker_pid}" 2>/dev/null; then
  wait "${worker_pid}" || exit_status=$?
else
  wait "${web_pid}" || exit_status=$?
fi
exit "${exit_status}"
