# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

.PHONY: help test test-integration test-device test-all install install-deps setup start ui restart stop status build-ui doctor smoke-mock smoke-sim clean precommit-install precommit lint format typecheck quality-ratchet

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

start: ## One-click start Apollo Showcase UI and auto-open browser
	@bash start.sh

ui: ## Launch the unified Showcase UI & Admin Console in browser
	@uv run apollo ui --open

restart: ## Restart running Apollo Web UI & server
	@uv run apollo restart

stop: ## Stop running Apollo Web UI & server
	@uv run apollo stop

status: ## Display Apollo Web UI & server status
	@uv run apollo status

build-ui: ## Build the Showcase UI Angular frontend
	@echo "🎨 Building Showcase UI..."
	@cd apps/showcase_ui && npm install && npm run build

doctor: ## Run system, device, and toolchain diagnostics
	@uv run apollo doctor

smoke-mock: ## Run a Flash task against the mock driver with a fake LLM (no device, no API key)
	@APOLLO_MOCK_DRIVER=1 APOLLO_FAKE_LLM=1 GOOGLE_API_KEY=test-placeholder uv run apollo run "Open Settings" --profile flash --standalone --device-serial mock-device

smoke-sim: ## Boot an iPhone simulator, run the driver smoke and a fake-LLM Flash task on it (no API key)
	@udid=$$(uv run python scripts/ci_boot_simulator.py) && \
	APOLLO_SIM_UDID=$$udid GOOGLE_API_KEY="$${GOOGLE_API_KEY:-test-placeholder}" uv run pytest tests/integration/test_ios_simulator_smoke.py tests/integration/test_sdk_ios_simulator.py -m ios_sim -q -o faulthandler_timeout=300 && \
	APOLLO_FAKE_LLM=1 GOOGLE_API_KEY="$${GOOGLE_API_KEY:-test-placeholder}" uv run apollo run "Open Settings" --profile flash --standalone --device-serial $$udid

test: ## Run deterministic tests that need no device, credentials, or private services
	@echo "🧪 Running deterministic tests..."
	@GOOGLE_API_KEY="$${GOOGLE_API_KEY:-test-placeholder}" uv run pytest

test-integration: ## Run non-device integration tests (may require configured model credentials)
	@echo "🧪 Running integration tests..."
	@uv run pytest tests/integration tests/tools -m "integration and not android and not cloud and not manual"

test-device: ## Run device-bound and end-to-end tests explicitly (needs a booted simulator)
	@echo "📱 Running device and end-to-end tests..."
	@uv run pytest tests/integration tests/e2e -m "ios_sim or e2e"

test-all: ## Run every test tree; external prerequisites must be available
	@echo "🧪 Running the complete test tree..."
	@uv run pytest tests packages/apollo-client/tests -m "integration or not integration"

install: ## Install python dependencies via uv
	@echo "📦 Installing python dependencies..."
	@uv sync --dev

install-deps: ## One-click install system dependencies (Xcode CLT check, ffmpeg, go-ios, optional idb, uv)
	@echo "⚡ Running one-click dependency installer..."
	@bash scripts/install_deps.sh

setup: ## Setup project (install dependencies + pre-commit hooks + build UI)
	@echo "🚀 Setting up project..."
	@$(MAKE) install
	@$(MAKE) build-ui
	@$(MAKE) precommit-install
	@echo ""
	@echo "✅ Setup complete! You're ready to start developing."

lint: ## Run linting checks
	@echo "🔍 Running linting checks..."
	@uv run ruff format --check
	@uv run ruff check
	@uv run python scripts/quality_ratchet.py

format: ## Format code
	@echo "✨ Formatting code..."
	@uv run ruff format
	@uv run ruff check --fix

typecheck: ## Run type checking
	@echo "🔍 Running type checks..."
	@uv run pyright --project pyright-core.json

quality-ratchet: ## Prevent broad exception and type-ignore debt from increasing
	@uv run python scripts/quality_ratchet.py

precommit-install: ## Install pre-commit hooks
	@echo "🔧 Installing pre-commit hooks..."
	@uv run pre-commit install
	@echo "✅ Pre-commit hooks installed successfully!"
	@echo ""
	@echo "Pre-commit will now run automatically on every commit."
	@echo "To run manually: make precommit"

precommit: ## Run pre-commit hooks manually on all files
	@echo "🔍 Running pre-commit checks..."
	@uv run pre-commit run --all-files

clean: ## Clean up generated files, caches, and traces
	@echo "🧹 Cleaning up caches and temporary files..."
	@rm -rf .pytest_cache .ruff_cache .apollo_paused traces scratch .venv apps/showcase_ui/.angular build dist
	@find . -type d -name "outputs" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name ".apollo_paused" -delete 2>/dev/null || true
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.py[cod]" -delete 2>/dev/null || true
	@echo "✅ Cleanup complete"
