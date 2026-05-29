UV ?= uv
PYTHON ?= python3
UV_CACHE_DIR ?= .uv-cache

.PHONY: help sync test build clean check post-metrics post-metrics-dry-run

help:
	@echo "Available targets:"
	@echo "  make sync   - Sync project dependencies with uv"
	@echo "  make test   - Run test suite via uv"
	@echo "  make build  - Build wheel and sdist via uv"
	@echo "  make clean  - Remove build artifacts and caches"
	@echo "  make check  - Run test and build targets"

sync:
	@command -v $(UV) >/dev/null 2>&1 || { echo "uv is required but was not found. Install uv first: https://docs.astral.sh/uv/"; exit 1; }
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync --all-groups

test:
	@command -v $(UV) >/dev/null 2>&1 || { echo "uv is required but was not found. Install uv first: https://docs.astral.sh/uv/"; exit 1; }
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run $(PYTHON) -m unittest discover -s tests

build:
	@command -v $(UV) >/dev/null 2>&1 || { echo "uv is required but was not found. Install uv first: https://docs.astral.sh/uv/"; exit 1; }
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) build

clean:
	rm -rf build dist
	rm -rf .pytest_cache .mypy_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +

check: test build

