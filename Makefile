PYTHON ?= python3.11

.PHONY: install test check fixtures
install:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'
test:
	.venv/bin/python -m pytest
check:
	.venv/bin/ruff check .
	.venv/bin/mypy src
	.venv/bin/python -m pytest --cov=cwa --cov-fail-under=80
fixtures:
	.venv/bin/python scripts/record_fixtures.py
