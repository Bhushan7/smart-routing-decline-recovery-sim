PY ?= python3

.PHONY: setup test lint eval demo eval-final eval-agent-stub eval-agent-claude

setup:
	$(PY) -m pip install -r requirements-dev.txt

lint:
	ruff check .

test:
	$(PY) -m pytest -q

eval:
	$(PY) evals/run_evals.py

demo:
	streamlit run src/app/dashboard.py

eval-final:
	$(PY) evals/run_evals.py --phase5

eval-agent-stub:
	$(PY) evals/run_evals.py --agent --seeds 2

eval-agent-claude:
	$(PY) evals/run_agent_claude.py
