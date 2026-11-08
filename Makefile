PY ?= python3

.PHONY: setup test lint eval demo

setup:
	$(PY) -m pip install -r requirements-dev.txt

lint:
	ruff check .

test:
	$(PY) -m pytest -q

eval:
	$(PY) evals/run_evals.py

demo:
	@echo "Dashboard arrives in Phase 5. Nothing to demo yet."
