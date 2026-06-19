#!/usr/bin/env sh
set -eu

SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "${SCRIPT_DIRECTORY}")
cd "${PROJECT_ROOT}"

MLX_SAM3_REVISION="d9a92badb6000a93135e01b89cd81a54e7ff9825"
MLX_SAM3_REPOSITORY="https://github.com/Deekshith-Dade/mlx_sam3.git"
MLX_SAM3_SOURCE="vendor/mlx_sam3"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  printf '%s\n' "MLX SAM 3 requires an Apple Silicon Mac." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv python install 3.13
if [ ! -x .venv-mlx/bin/python ]; then
  uv venv --python 3.13 .venv-mlx
fi
uv pip install --python .venv-mlx/bin/python ".[vision,dev]"

# The upstream wheel currently omits its top-level tokenizer asset. An editable
# pinned checkout keeps that required file available beside the `sam3` package.
if [ ! -d "${MLX_SAM3_SOURCE}/.git" ]; then
  mkdir -p vendor
  git clone "${MLX_SAM3_REPOSITORY}" "${MLX_SAM3_SOURCE}"
  git -C "${MLX_SAM3_SOURCE}" checkout --detach "${MLX_SAM3_REVISION}"
fi

installed_revision="$(git -C "${MLX_SAM3_SOURCE}" rev-parse HEAD)"
if [ "${installed_revision}" != "${MLX_SAM3_REVISION}" ]; then
  printf '%s\n' \
    "${MLX_SAM3_SOURCE} is at ${installed_revision}; expected ${MLX_SAM3_REVISION}." >&2
  printf '%s\n' "Move that checkout aside and rerun this script." >&2
  exit 1
fi

uv pip install --python .venv-mlx/bin/python "${MLX_SAM3_SOURCE}"

PROJECT_SOURCE="${PROJECT_ROOT}/src"
MLX_SAM3_ABSOLUTE_SOURCE="${PROJECT_ROOT}/${MLX_SAM3_SOURCE}"

# Python 3.13 skips `.pth` processing when the virtual-environment directory is
# Finder-hidden. Validate the explicit source paths used by run-mlx.sh.
(
  cd "${TMPDIR:-/tmp}"
  env \
    PYTHONPATH="${PROJECT_SOURCE}:${MLX_SAM3_ABSOLUTE_SOURCE}" \
    "${PROJECT_ROOT}/.venv-mlx/bin/python" -c "import mlx; import sam3; import shotsight2; from pathlib import Path; asset = Path(sam3.__file__).resolve().parent.parent / 'assets' / 'bpe_simple_vocab_16e6.txt.gz'; assert asset.is_file(), f'Missing tokenizer asset: {asset}'; print('MLX SAM 3 runtime is ready')"
)
