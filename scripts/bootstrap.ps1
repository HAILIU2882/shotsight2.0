$ErrorActionPreference = "Stop"

py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install --upgrade pip
./.venv/Scripts/python.exe -m pip install -e ".[vision,dev]"

Write-Output "ShotSight 2.0 environment created in .venv"

