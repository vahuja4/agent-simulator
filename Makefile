UV := /opt/homebrew/bin/uv
PYTHON := .venv/bin/python
PYTHON_VERSION := 3.12.12

.PHONY: setup doctor test

setup:
	@test -x "$(UV)" || { echo "Missing $(UV). Install uv with: brew install uv"; exit 1; }
	$(UV) python install $(PYTHON_VERSION)
	$(UV) venv --clear --python $(PYTHON_VERSION) .venv
	$(UV) pip sync --python $(PYTHON) requirements.lock
	$(UV) pip install --python $(PYTHON) --no-deps -e .
	$(MAKE) doctor

doctor:
	@test -x "$(PYTHON)" || { echo "Missing $(PYTHON). Run: make setup"; exit 1; }
	@$(PYTHON) --version | grep -Fx "Python $(PYTHON_VERSION)"
	@$(PYTHON) -c "import readline; print('readline: OK')"
	@echo "environment: OK"

test: doctor
	$(PYTHON) -m pytest
