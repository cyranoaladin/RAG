SHELL := /bin/bash
VENVDIR ?= .venv

PY_SYS := $(shell command -v python3 2>/dev/null || echo python3)
PY_VENV := $(VENVDIR)/bin/python
ifeq ($(wildcard $(PY_VENV)),)
  PY ?= $(PY_SYS)
else
  PY ?= $(PY_VENV)
endif

.PHONY: venv install doctor project-doctor init scrape-official ingest ingest-official ingest-internal verify eval-retrieval watch api test lint format typecheck backup ledger-init ledger-doctor manifest-import-fixture manifest-dir-dry-run manifest-dir-import-fixture manifest-readiness manifest-coverage manifest-gate manifest-readiness-clean manifest-coverage-clean manifest-gate-clean manifest-controlled-import-clean manifest-controlled-import-problem review-package-clean-audited pilot-template-check pilot-compile-check pilot-rehearsal real-draft-guard-check human-unlock-check real-draft-unlock-gate-check metadata-preflight cleanup-dry-run cleanup-review cleanup-decision-draft make-target-safety-audit pilot-corpus-scope-audit retrieval-metadata-eval-audit pedago-interface-contract-audit source-admission-policy-audit human-source-review-audit controlled-readiness-audit transition-authorization-audit metadata-governance-chain-audit metadata-review-handoff-audit

venv:
	@if [ ! -x "$(PY_VENV)" ]; then \
		echo "-> create venv in $(VENVDIR)"; \
		$(PY_SYS) -m venv "$(VENVDIR)"; \
	fi

install: venv
	"$(PY_VENV)" -m pip install -r requirements.lock
	"$(PY_VENV)" -m pip install -e ../../packages/contracts --no-deps
	"$(PY_VENV)" -m pip install -e . --no-deps

doctor:
	$(PY) scripts/doctor.py

project-doctor:
	$(PY) -m rag_pedago.project_doctor

ledger-init:
	$(PY) -m rag_pedago.ledger.init_db

ledger-doctor:
	$(PY) -m rag_pedago.ledger.init_db --check

manifest-import-fixture:
	$(PY) -m rag_pedago.imports.import_manifest data/fixtures/manifests/sample_documents.jsonl

manifest-dir-dry-run:
	$(PY) -m rag_pedago.imports.import_manifest_dir data/fixtures/manifests/batch_001 --dry-run --batch-id batch-001-dry

manifest-dir-import-fixture:
	$(PY) -m rag_pedago.imports.import_manifest_dir data/fixtures/manifests/batch_001 --batch-id batch-001

manifest-readiness:
	$(PY) -m rag_pedago.imports.readiness_report data/fixtures/manifests/batch_001 --batch-id batch-001

manifest-coverage:
	$(PY) -m rag_pedago.imports.coverage_report data/fixtures/manifests/batch_001 --batch-id batch-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml

manifest-gate:
	$(PY) -m rag_pedago.imports.gate_report data/fixtures/manifests/batch_001 --batch-id batch-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml

manifest-readiness-clean:
	$(PY) -m rag_pedago.imports.readiness_report data/fixtures/manifests/batch_clean_001 --batch-id batch-clean-001

manifest-coverage-clean:
	$(PY) -m rag_pedago.imports.coverage_report data/fixtures/manifests/batch_clean_001 --batch-id batch-clean-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml

manifest-gate-clean:
	$(PY) -m rag_pedago.imports.gate_report data/fixtures/manifests/batch_clean_001 --batch-id batch-clean-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml

manifest-controlled-import-clean:
	$(PY) -m rag_pedago.imports.controlled_import_cli data/fixtures/manifests/batch_clean_001 --batch-id batch-clean-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml

manifest-controlled-import-problem:
	$(PY) -m rag_pedago.imports.controlled_import_cli data/fixtures/manifests/batch_001 --batch-id batch-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml

review-package-clean-audited:
	$(PY) -m rag_pedago.imports.review_package_cli data/fixtures/manifests/batch_official_profiles_clean --batch-id batch-official-profiles-clean --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml --audit-ledger data/ledger/rag_pedago.sqlite

pilot-template-check:
	$(PY) -m rag_pedago.imports.pilot_manifest_template docs/templates/pilot_math_terminale/pilot_manifest.template.yml

pilot-compile-check:
	$(PY) -m rag_pedago.imports.pilot_manifest_compiler data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml --check

pilot-rehearsal:
	$(PY) -m rag_pedago.imports.pilot_metadata_rehearsal data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml --tmp

real-draft-guard-check:
	$(PY) -m rag_pedago.imports.real_draft_guard data/fixtures/pilot_math_terminale/real_draft_guard/metadata_candidate.valid.jsonl

human-unlock-check:
	$(PY) -m rag_pedago.imports.human_unlock_guard data/fixtures/pilot_math_terminale/human_unlock/human_unlock.valid.json

real-draft-unlock-gate-check:
	$(PY) -m rag_pedago.imports.real_draft_unlock_gate \
	  data/fixtures/pilot_math_terminale/real_draft_unlock_gate/unlock.valid.json \
	  data/fixtures/pilot_math_terminale/real_draft_unlock_gate/draft.valid.jsonl

metadata-preflight:
	$(PY) -m rag_pedago.imports.metadata_preflight

cleanup-dry-run:
	$(PY) scripts/cleanup_dry_run.py

cleanup-review:
	$(PY) scripts/cleanup_review_package.py

cleanup-decision-draft:
	$(PY) scripts/cleanup_decision_draft.py

make-target-safety-audit:
	$(PY) scripts/make_target_safety_audit.py

pilot-corpus-scope-audit:
	$(PY) scripts/pilot_corpus_scope_audit.py

retrieval-metadata-eval-audit:
	$(PY) scripts/retrieval_metadata_eval_audit.py

pedago-interface-contract-audit:
	$(PY) scripts/pedago_interface_contract_audit.py

source-admission-policy-audit:
	$(PY) scripts/source_admission_policy_audit.py

human-source-review-audit:
	$(PY) scripts/human_source_review_audit.py

controlled-readiness-audit:
	$(PY) scripts/controlled_readiness_audit.py

transition-authorization-audit:
	$(PY) scripts/transition_authorization_audit.py

metadata-governance-chain-audit:
	$(PY) scripts/metadata_governance_chain_audit.py

metadata-review-handoff-audit:
	$(PY) scripts/metadata_review_handoff_audit.py

init:
	$(PY) scripts/init_db.py
	$(PY) scripts/init_qdrant.py

scrape-official:
	$(PY) scripts/scrape_official.py

ingest:
	$(PY) -m pipeline.run --all

ingest-official:
	$(PY) -m pipeline.run --source official

ingest-internal:
	$(PY) -m pipeline.run --source internal

verify:
	$(PY) -m pipeline.verify

eval-retrieval:
	$(PY) -m retrieval.eval

watch:
	$(PY) -m pipeline.watch

api:
	uvicorn services.api.main:app --host 127.0.0.1 --port 18001

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff format .

typecheck:
	$(PY) -m mypy schema pipeline retrieval services rag_pedago scrapers agents

backup:
	bash ops/backup/backup.sh
