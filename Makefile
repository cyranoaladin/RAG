.PHONY: full-regression help

help:
	@echo "Targets: full-regression"

full-regression:
	bash scripts/tests/full-regression.sh
