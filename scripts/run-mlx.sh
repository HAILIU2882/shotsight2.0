#!/usr/bin/env sh
set -eu

SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "${SCRIPT_DIRECTORY}")
cd "${PROJECT_ROOT}"

if [ ! -x .venv-mlx/bin/uvicorn ]; then
  printf '%s\n' "Run ./scripts/setup-mlx.sh first." >&2
  exit 1
fi

# Use the current checkout even though setup also installs non-editable copies
# so Python 3.13 does not depend on hidden editable-install .pth hooks.
export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}/vendor/mlx_sam3${PYTHONPATH:+:${PYTHONPATH}}"

if ! (
  cd "${TMPDIR:-/tmp}"
  "${PROJECT_ROOT}/.venv-mlx/bin/python" -c "import sam3; import shotsight2; from pathlib import Path; asset = Path(sam3.__file__).resolve().parent.parent / 'assets' / 'bpe_simple_vocab_16e6.txt.gz'; assert asset.is_file()"
); then
  printf '%s\n' "MLX SAM 3 source or tokenizer asset is unavailable. Run ./scripts/setup-mlx.sh again." >&2
  exit 1
fi

export SHOTSIGHT_ENABLE_SAM3=true
export SHOTSIGHT_TRACKING_BACKEND=mlx-sam3

exec "${PROJECT_ROOT}/.venv-mlx/bin/uvicorn" \
  shotsight2.main:app --host 127.0.0.1 --port 4173 --reload
