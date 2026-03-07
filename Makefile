VENV=.venv
PYTHON=$(VENV)/bin/python
PIP=$(VENV)/bin/pip

.PHONY: venv install test lint clean

venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel

install: venv
	$(PIP) install -e .
	$(PIP) install -r requirements-dev.txt

test: venv
	$(VENV)/bin/pytest -q

lint: venv
	$(VENV)/bin/flake8 .

clean:
	rm -rf $(VENV) build dist *.egg-info

