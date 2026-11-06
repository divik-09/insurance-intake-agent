PY ?= python

install:
	$(PY) -m pip install -r requirements-dev.txt

run:
	$(PY) -m uvicorn app.main:create_app --factory --reload --port 8000

test:
	$(PY) -m pytest

eval:
	$(PY) -m evals.run_eval --provider heuristic

demo:
	$(PY) -m scripts.demo
