UV ?= uv
PYTHON ?= python3
UV_CACHE_DIR ?= .uv-cache

METRICS_RUN_ID ?= manual-$$(date +%s)
METRICS_STATUS ?= success
METRICS_JOB_TYPE ?= Manual metrics submission
METRICS_ITEM_NAME ?= manual
METRICS_ITEMS_DISCOVERED ?= 0
METRICS_ITEMS_FAILED ?= 0
METRICS_ITEMS_SUCCEEDED ?= 0
METRICS_RUN_DURATION_MS ?= 0
METRICS_TOKEN_USAGE ?= 0
METRICS_API_CALLS_COUNT ?= 0

.PHONY: help sync test build clean check post-metrics post-metrics-dry-run

help:
	@echo "Available targets:"
	@echo "  make sync   - Sync project dependencies with uv"
	@echo "  make test   - Run test suite via uv"
	@echo "  make build  - Build wheel and sdist via uv"
	@echo "  make clean  - Remove build artifacts and caches"
	@echo "  make check  - Run test and build targets"
	@echo "  make post-metrics - Post Codex run metrics to Metrics API v1"
	@echo "  make post-metrics-dry-run - Print metrics payload without posting"
	@echo "  make post-metrics-from-file - Post metrics JSON payload from METRICS_PAYLOAD_FILE"
	@echo "  make post-metrics-from-file-dry-run - Print payload from METRICS_PAYLOAD_FILE"

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

post-metrics:
	@echo "METRICS_POST: start (target=post-metrics run_id=$(METRICS_RUN_ID))"
	@$(PYTHON) tools/metrics_api_v1.py \
		--run-id "$(METRICS_RUN_ID)" \
		--status "$(METRICS_STATUS)" \
		--job-type "$(METRICS_JOB_TYPE)" \
		--item-name "$(METRICS_ITEM_NAME)" \
		--items-discovered $(METRICS_ITEMS_DISCOVERED) \
		--items-failed $(METRICS_ITEMS_FAILED) \
		--items-succeeded $(METRICS_ITEMS_SUCCEEDED) \
		--run-duration-ms $(METRICS_RUN_DURATION_MS) \
		--token-usage $(METRICS_TOKEN_USAGE) \
		--api-calls-count $(METRICS_API_CALLS_COUNT); \
	rc=$$?; \
	if [ $$rc -eq 0 ]; then \
		echo "METRICS_POST_RESULT: SUCCESS"; \
	else \
		echo "METRICS_POST_RESULT: FAILED (exit=$$rc)"; \
		exit $$rc; \
	fi

post-metrics-dry-run:
	@echo "METRICS_POST: start (target=post-metrics-dry-run run_id=$(METRICS_RUN_ID))"
	@$(PYTHON) tools/metrics_api_v1.py \
		--run-id "$(METRICS_RUN_ID)" \
		--status "$(METRICS_STATUS)" \
		--job-type "$(METRICS_JOB_TYPE)" \
		--item-name "$(METRICS_ITEM_NAME)" \
		--items-discovered $(METRICS_ITEMS_DISCOVERED) \
		--items-failed $(METRICS_ITEMS_FAILED) \
		--items-succeeded $(METRICS_ITEMS_SUCCEEDED) \
		--run-duration-ms $(METRICS_RUN_DURATION_MS) \
		--token-usage $(METRICS_TOKEN_USAGE) \
		--api-calls-count $(METRICS_API_CALLS_COUNT) \
		--dry-run; \
	rc=$$?; \
	if [ $$rc -eq 0 ]; then \
		echo "METRICS_POST_RESULT: SUCCESS (dry-run)"; \
	else \
		echo "METRICS_POST_RESULT: FAILED (dry-run, exit=$$rc)"; \
		exit $$rc; \
	fi

post-metrics-from-file:
	@test -n "$(METRICS_PAYLOAD_FILE)" || { echo "METRICS_PAYLOAD_FILE is required"; exit 1; }
	@echo "METRICS_POST: start (target=post-metrics-from-file payload=$(METRICS_PAYLOAD_FILE))"
	@$(PYTHON) tools/metrics_api_v1.py --payload-file "$(METRICS_PAYLOAD_FILE)"; \
	rc=$$?; \
	if [ $$rc -eq 0 ]; then \
		echo "METRICS_POST_RESULT: SUCCESS"; \
	else \
		echo "METRICS_POST_RESULT: FAILED (exit=$$rc)"; \
		exit $$rc; \
	fi

post-metrics-from-file-dry-run:
	@test -n "$(METRICS_PAYLOAD_FILE)" || { echo "METRICS_PAYLOAD_FILE is required"; exit 1; }
	@echo "METRICS_POST: start (target=post-metrics-from-file-dry-run payload=$(METRICS_PAYLOAD_FILE))"
	@$(PYTHON) tools/metrics_api_v1.py --payload-file "$(METRICS_PAYLOAD_FILE)" --dry-run; \
	rc=$$?; \
	if [ $$rc -eq 0 ]; then \
		echo "METRICS_POST_RESULT: SUCCESS (dry-run)"; \
	else \
		echo "METRICS_POST_RESULT: FAILED (dry-run, exit=$$rc)"; \
		exit $$rc; \
	fi
