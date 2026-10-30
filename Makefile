PYTHON ?= python3

.PHONY: install lint test experiments receipts verify clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	ruff check src tests experiments tools

test:
	$(PYTHON) -m pytest --junitxml=junit.xml --cov=src/openloop --cov-report=json --cov-report=term

experiments:
	$(PYTHON) experiments/e1_null.py
	$(PYTHON) experiments/e2_stall.py
	$(PYTHON) experiments/e3_sweep.py
	$(PYTHON) experiments/e4_sim_vs_wall.py

receipts:
	$(PYTHON) tools/collect_metrics.py --skip-tests
	$(PYTHON) tools/check_numbers.py

verify: lint test experiments receipts

clean:
	rm -rf .pytest_cache .ruff_cache .coverage coverage.json coverage.xml junit.xml
