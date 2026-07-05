# Guardian AI — single entry point for all development tasks.
# Run `make help` for the list of targets.

SHELL := /bin/bash
.DEFAULT_GOAL := help

DART_PACKAGES := packages/dart/guardian_core packages/dart/guardian_api_client packages/dart/guardian_ui
FLUTTER_APPS  := mobile dashboard
PY_TESTS      := ai/tests edge/tests backend/tests packages/python/guardian_common/tests
COMPOSE       := docker compose -f docker/compose.yaml

# ---------------------------------------------------------------- setup ----

.PHONY: setup
setup: ## Install toolchain (uv, hooks) and sync all workspaces
	./scripts/setup.sh

.PHONY: sync
sync: ## Sync Python workspace dependencies
	uv sync --all-packages

# ----------------------------------------------------------- lint/format ----

.PHONY: lint
lint: lint-python lint-dart ## Lint everything

.PHONY: lint-python
lint-python: ## Ruff + mypy over all Python components
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy ai/guardian_ai edge/guardian_edge backend/app packages/python/guardian_common/guardian_common

.PHONY: lint-dart
lint-dart: ## Analyze + format-check all Dart packages and Flutter apps
	@for dir in $(DART_PACKAGES) $(FLUTTER_APPS); do \
		echo "==> $$dir"; \
		(cd $$dir && flutter pub get --offline 2>/dev/null || flutter pub get) || exit 1; \
		(cd $$dir && dart format --output=none --set-exit-if-changed .) || exit 1; \
		(cd $$dir && flutter analyze --no-pub) || exit 1; \
	done

.PHONY: format
format: ## Auto-format all code
	uv run ruff format .
	uv run ruff check --fix .
	@for dir in $(DART_PACKAGES) $(FLUTTER_APPS); do (cd $$dir && dart format .); done

# ----------------------------------------------------------------- test ----

.PHONY: test
test: test-python test-dart ## Run all tests

.PHONY: test-python
test-python: ## Run Python tests for ai, edge, backend, guardian_common
	uv run pytest $(PY_TESTS)

.PHONY: test-dart
test-dart: ## Run Dart/Flutter tests where present
	@for dir in $(DART_PACKAGES) $(FLUTTER_APPS); do \
		if [ -d $$dir/test ] && [ -n "$$(ls -A $$dir/test 2>/dev/null)" ]; then \
			echo "==> $$dir"; (cd $$dir && flutter test) || exit 1; \
		else echo "==> $$dir (no tests yet, skipping)"; fi; \
	done

.PHONY: test-backend
test-backend: ## Backend tests only
	uv run pytest backend/tests

.PHONY: test-edge
test-edge: ## Edge runtime tests only
	uv run pytest edge/tests

.PHONY: test-ai
test-ai: ## AI/training tests only
	uv run pytest ai/tests

# ---------------------------------------------------------- local stack ----

.PHONY: stack-up
stack-up: ## Start local infrastructure (PostgreSQL, Redis, RabbitMQ)
	$(COMPOSE) up -d --wait

.PHONY: stack-down
stack-down: ## Stop local infrastructure (data volumes preserved)
	$(COMPOSE) down

.PHONY: stack-logs
stack-logs: ## Tail local infrastructure logs
	$(COMPOSE) logs -f

# -------------------------------------------------------------- codegen ----

.PHONY: codegen
codegen: ## Regenerate clients/schemas from contracts/ (no-op until contracts exist)
	./scripts/codegen.sh

# ---------------------------------------------------------------- vision ----

.PHONY: model-yolox
model-yolox: ## Download and install YOLOX-tiny into ./models (ADR-0003)
	uv run python -m guardian_edge.tools.install_yolox --dest models

.PHONY: demo-vision
demo-vision: ## Live RTSP -> detections -> browser demo (needs cameras.yaml + models)
	uv run python -m guardian_edge.tools.live_demo --cameras edge/config/cameras.yaml --models models

.PHONY: bench
bench: ## Run performance benchmarks (requires make model-yolox first)
	uv run pytest edge/tests -q -m benchmark -rs

RECORD_FLAGS ?= --tracking

.PHONY: sprint-video
sprint-video: ## Record a 30s sprint demo (make sprint-video VIDEO=Sprint-NN-Topic.mp4)
	uv run python -m guardian_edge.tools.record_demo \
		--cameras edge/config/cameras.yaml --models models \
		--duration 30 --output $(VIDEO) $(RECORD_FLAGS)

# --------------------------------------------------------------- deploy ----

.PHONY: install
install: ## One-command Guardian Edge Box install (deploy/install.sh)
	./deploy/install.sh

.PHONY: stress
stress: ## Long-running stability/stress simulations (accelerated 24h)
	uv run pytest edge/tests -q -m stress -rs

.PHONY: release
release: ## Package a release into dist/ (wheel + build metadata + dependency manifest)
	rm -rf dist && mkdir -p dist
	uv build --package guardian-edge --out-dir dist
	uv export --package guardian-edge --no-dev --no-emit-project --no-hashes > dist/requirements-lock.txt
	@printf '{\n  "version": "%s",\n  "git_commit": "%s",\n  "git_branch": "%s",\n  "built_utc": "%s",\n  "built_on": "%s"\n}\n' \
		"$$(uv run guardianctl version | cut -d' ' -f2)" \
		"$$(git rev-parse HEAD)" \
		"$$(git rev-parse --abbrev-ref HEAD)" \
		"$$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
		"$$(uname -sm)" > dist/build-info.json
	@echo "release artifacts:" && ls -la dist/

# ---------------------------------------------------------------- misc ----

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
	find . -type d -name __pycache__ -not -path "./.git/*" -exec rm -rf {} +

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
