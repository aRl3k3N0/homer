# Homer — Makefile
#
# Таргеты:
#   make install         — установить основные зависимости
#   make install-dev     — установить dev-зависимости
#   make test            — запустить pytest
#   make test-cov        — pytest с покрытием
#   make lint            — ruff + flake8
#   make typecheck       — mypy
#   make format          — ruff format + isort
#   make check           — lint + typecheck + test
#   make docs            — сгенерировать API-документацию (Sphinx)
#   make docs-serve      — локальный сервер документации
#   make clean           — убрать артефакты сборки и кэши
#   make run             — запустить homer без аргументов (список команд)
#   make shell           — REPL

PY ?= python3
PIP ?= $(PY) -m pip
PYTEST ?= $(PY) -m pytest
RUFF ?= $(PY) -m ruff
MYPY ?= $(PY) -m mypy
FLAKE8 ?= $(PY) -m flake8
SPHINX ?= $(PY) -m sphinx

SRC_LIB = lib
SRC_TESTS = tests
DOCS_DIR = docs/api-generated
DOCS_BUILD = $(DOCS_DIR)/_build

SHELL := /bin/bash
SCRIPTS := scripts
PY ?= python3

.PHONY: help bootstrap install install-dev \
        lint typecheck test test-cov test-fast benchmark \
        docs docs-serve package publish docker release release-dry \
        check pre-commit-install pre-commit-run pre-commit-update clean run shell

help:
	@echo "Установка:"
	@echo "  make bootstrap          — dev-зависимости (scripts/bootstrap.sh)"
	@echo "  make install            — только prod"
	@echo "  make install-dev        — prod + dev"
	@echo ""
	@echo "Проверки:"
	@echo "  make lint               — ruff + flake8 + pre-commit"
	@echo "  make typecheck          — mypy"
	@echo "  make test               — pytest"
	@echo "  make test-cov           — pytest с покрытием"
	@echo "  make test-fast          — pytest быстрый (FAST=1)"
	@echo "  make benchmark          — pytest-benchmark"
	@echo "  make check              — lint + typecheck + test"
	@echo ""
	@echo "Артефакты:"
	@echo "  make docs               — Sphinx build"
	@echo "  make docs-serve         — локальный сервер документации"
	@echo "  make package            — wheel + sdist"
	@echo "  make docker             — docker build"
	@echo "  make docker-push        — docker build + push"
	@echo "  make publish            — twine upload"
	@echo "  make release            — semantic-release"
	@echo "  make release-dry        — semantic-release dry-run"
	@echo ""
	@echo "Прочее:"
	@echo "  make pre-commit-install — установить git-хуки"
	@echo "  make pre-commit-run     — прогнать все хуки"
	@echo "  make clean              — убрать артефакты"
	@echo "  make run                — homer (список команд)"
	@echo "  make shell              — homer shell"

bootstrap:
	@./$(SCRIPTS)/bootstrap.sh

install:
	@MODE=prod ./$(SCRIPTS)/bootstrap.sh

install-dev:
	@MODE=dev ./$(SCRIPTS)/bootstrap.sh

lint:
	@./$(SCRIPTS)/lint.sh

typecheck:
	@./$(SCRIPTS)/typecheck.sh

test:
	@./$(SCRIPTS)/test.sh

test-cov:
	@COVERAGE=1 ./$(SCRIPTS)/test.sh

test-fast:
	@FAST=1 ./$(SCRIPTS)/test.sh

benchmark:
	@./$(SCRIPTS)/benchmark.sh

docs:
	@./$(SCRIPTS)/docs.sh

docs-serve:
	@SERV=1 ./$(SCRIPTS)/docs.sh

package:
	@./$(SCRIPTS)/package.sh

publish:
	@./$(SCRIPTS)/publish.sh

docker:
	@./$(SCRIPTS)/docker.sh

docker-push:
	@PUSH=1 LOGIN=1 ./$(SCRIPTS)/docker.sh

release:
	@./$(SCRIPTS)/release.sh

release-dry:
	@DRY=1 ./$(SCRIPTS)/release.sh

check: lint typecheck test

pre-commit-install:
	@$(PY) -m pip install pre-commit
	@$(PY) -m pre_commit install
	@$(PY) -m pre_commit install --hook-type commit-msg

pre-commit-run:
	@$(PY) -m pre_commit run --all-files

pre-commit-update:
	@$(PY) -m pre_commit autoupdate

clean:
	@rm -rf dist/ build/ htmlcov/ .coverage coverage.xml coverage.lcov
	@rm -rf .benchmarks/ benchmark.json
	@rm -rf docs/api-generated/_build/
	@rm -rf .pytest_cache .mypy_cache .ruff_cache
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

run:
	@./homer

shell:
	@./homer shell

install:
	$(PIP) install -r requirements.txt

install-dev: install
	$(PIP) install -r requirements-dev.txt

test:
	$(PYTEST) -q

test-cov:
	$(PYTEST) --cov=lib --cov-report=term-missing --cov-report=html:htmlcov

lint:
	$(RUFF) check $(SRC_LIB) $(SRC_TESTS)
	$(FLAKE8) $(SRC_LIB) $(SRC_TESTS)

typecheck:
	$(MYPY) $(SRC_LIB)

format:
	$(RUFF) format $(SRC_LIB) $(SRC_TESTS)
	$(RUFF) check --fix $(SRC_LIB) $(SRC_TESTS)

check: lint typecheck test

docs:
	$(SPHINX) -b html $(DOCS_DIR) $(DOCS_BUILD)/html -W --keep-going
	@echo "Документация: file://$(CURDIR)/$(DOCS_BUILD)/html/index.html"

docs-serve:
	$(PY) -m http.server 8000 --directory $(DOCS_BUILD)/html

clean:
	rm -rf $(DOCS_BUILD)
	rm -rf htmlcov .coverage .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

run:
	./homer

shell:
	./homer shell

# ─────────── Pre-commit ───────────

pre-commit-install:
	$(PIP) install pre-commit
	$(PY) -m pre_commit install
	$(PY) -m pre_commit install --hook-type commit-msg
	@echo "✔ Pre-commit установлен. Хуки будут запускаться на git commit."

pre-commit-run:
	$(PY) -m pre_commit run --all-files

pre-commit-update:
	$(PY) -m pre_commit autoupdate

# ─────────── Benchmark ───────────

benchmark:
	$(PYTEST) benchmarks/ \
		--benchmark-only \
		--benchmark-autosave \
		--benchmark-storage=.benchmarks \
		--benchmark-columns=min,max,mean,stddev,median,ops

benchmark-compare:
	$(PYTEST) benchmarks/ \
		--benchmark-only \
		--benchmark-compare \
		--benchmark-storage=.benchmarks

# ─────────── Docker ───────────

docker-build:
	docker build -t homer:local .

docker-run:
	docker run --rm -it \
		-v $(PWD)/config.yml:/app/config.yml:ro \
		-v $(PWD)/var:/app/var \
		-v $(PWD)/logs:/app/logs \
		homer:local

# ─────────── Release ───────────

release-dry:
	semantic-release version --print

webui-start:
	./homer webui:start

webui-stop:
	./homer webui:stop

webui-restart:
	./homer webui:restart

webui-reload:
	./homer webui:reload

webui-status:
	./homer webui:status

scheduler-start:
	./homer scheduler:start

scheduler-stop:
	./homer scheduler:stop

scheduler-restart:
	./homer scheduler:restart

scheduler-reload:
	./homer scheduler:reload

scheduler-status:
	./homer scheduler:status

services:
	./homer services

services-stop:
	./homer webui:stop || true
	./homer scheduler:stop || true

services-start:
	./homer scheduler:start
	./homer webui:start
