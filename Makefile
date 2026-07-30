SHELL := /bin/bash

.PHONY: full-regression e2e-prod-readonly

full-regression:
	@PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 bash scripts/tests/full-regression.sh

e2e-prod-readonly:
	@bash scripts/e2e/run-rag-v2-prod-readonly.sh
