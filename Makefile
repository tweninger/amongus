SHELL := /bin/bash

VENV ?= venv
PYTHON := $(abspath $(VENV))/bin/python
RUFF := $(abspath $(VENV))/bin/ruff
PYTEST := $(abspath $(VENV))/bin/pytest
UVICORN := $(abspath $(VENV))/bin/uvicorn
HOST ?= 127.0.0.1
PORT ?= 8011

REMOTE_USER ?= mbai
REMOTE_HOST ?= dsg7
REMOTE_PATH ?= /home/mbai/amongus
REMOTE_SERVICE ?= amongus

.PHONY: install install-dev install-browser check-browser-deps test lint run check-matchmaking deploy

install:
	$(PYTHON) -m pip install -e ./among-agents -e .

install-dev:
	$(PYTHON) -m pip install -e ./among-agents -e ".[dev]"

install-browser:
	PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers $(PYTHON) -m playwright install chromium

check-browser-deps:
	$(PYTHON) -m playwright install-deps chromium --dry-run

lint:
	$(RUFF) check .

test: lint
	$(PYTEST)

run:
	$(UVICORN) amongus_server.main:app --host $(HOST) --port $(PORT) --reload

check-matchmaking:
	PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers $(UVICORN) amongus_server.main:app --host $(HOST) --port $(PORT) > /tmp/amongus-uvicorn.log 2>&1 & \
	pid=$$!; \
	trap 'kill $$pid >/dev/null 2>&1 || true; wait $$pid >/dev/null 2>&1 || true' EXIT; \
	sleep 2; \
	PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers $(PYTHON) scripts/check_matchmaking.py http://$(HOST):$(PORT)/

deploy:
	ssh $(REMOTE_USER)@$(REMOTE_HOST) 'cd $(REMOTE_PATH) && git pull --ff-only && sudo systemctl restart $(REMOTE_SERVICE)'
