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
