.PHONY: install dev test lint run

install:
	python -m pip install -e .

dev:
	python -m pip install -e ".[vision,dev]"

test:
	pytest

lint:
	ruff check .
	mypy src

run:
	uvicorn shotsight2.main:app --host 127.0.0.1 --port 4173 --reload

