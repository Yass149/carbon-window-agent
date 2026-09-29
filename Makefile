PYTHON ?= python3.11

.PHONY: install test check fixtures run eval demo ui
install:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e '.[dev,anthropic,ui]'
test:
	.venv/bin/python -m pytest
check:
	.venv/bin/ruff check .
	.venv/bin/mypy src
	.venv/bin/python -m pytest --cov=cwa --cov-fail-under=80
fixtures:
	.venv/bin/python scripts/record_fixtures.py
run:
	.venv/bin/uvicorn cwa.api.main:create_app --factory --host 127.0.0.1 --port 8000
eval:
	.venv/bin/python -m evals.run_eval
demo:
	.venv/bin/python scripts/try_agent.py
ui:
	.venv/bin/streamlit run ui/streamlit_app.py
