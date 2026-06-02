SHELL := /bin/bash

VENV ?= venv
PYTHON := $(abspath $(VENV))/bin/python
RUFF := $(abspath $(VENV))/bin/ruff
PYTEST := $(abspath $(VENV))/bin/pytest
PYTHONPATH := $(abspath among-agents):$(abspath human_trials):$(abspath .)

REMOTE_USER ?= mbai
REMOTE_HOST ?= dsg7
REMOTE_PATH ?= /home/mbai/amongus
REMOTE_SERVICE ?= amongus

.PHONY: test lint run deploy

lint:
	$(RUFF) check human_trials among-agents

test: lint
	$(PYTEST) -q tests

run:
	cd human_trials && PYTHONPATH=$(PYTHONPATH) UVICORN_HOST=127.0.0.1 UVICORN_PORT=8011 $(PYTHON) server.py

deploy:
	ssh $(REMOTE_USER)@$(REMOTE_HOST) 'cd $(REMOTE_PATH) && git pull --ff-only && sudo systemctl restart $(REMOTE_SERVICE)'
