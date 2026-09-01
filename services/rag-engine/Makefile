SHELL := /bin/bash
VENVDIR ?= .venv

# Detecte un Python de venv si disponible, sinon retombe sur python3
PY_SYS := $(shell command -v python3.11 || command -v python3.12 || command -v python3 2>/dev/null || echo python3)
PY_VENV := $(VENVDIR)/bin/python
ifeq ($(wildcard $(PY_VENV)),)
  PY := $(PY_SYS)
else
  PY := $(PY_VENV)
endif

RUFF   := $(PY) -m ruff
MYPY   := $(PY) -m mypy
PYTEST := $(PY) -m pytest

.PHONY: help venv install install-dev lint typecheck test test-integration \
    test-integration-hybrid test-governance-pg smoke \
    obs-up obs-down obs-smoke obs-quickcheck obs-restart obs-status \
    compose-test-up compose-test-down print-tools dev compose-up compose-down compose-restart \
    eval

help:
	@echo "Targets : venv | install-dev | lint | typecheck | test | test-integration | eval | smoke | obs-up | obs-smoke | obs-down | obs-restart | obs-status | compose-test-up | compose-test-down | print-tools | dev | compose-up | compose-down | compose-restart"

# Évaluation LOT 39 — métriques de retrieval sur golden set YAML
eval:
	@$(PY) eval/run_eval.py --json-output eval/last_eval_report.json

# Cree le venv si absent et met pip a jour

venv:
	@if [ ! -x "$(PY_VENV)" ]; then \
		echo "-> create venv in $(VENVDIR)"; \
		$(PY_SYS) -m venv "$(VENVDIR)"; \
		"$(PY_VENV)" -m pip install -U pip; \
	fi

# Installe depuis le lock, puis les editables sans re-résolution
install: venv
	"$(PY_VENV)" -m pip install -r requirements.lock
	"$(PY_VENV)" -m pip install -e ../../packages/contracts --no-deps
	"$(PY_VENV)" -m pip install -e ../../packages/pdf-page-policy --no-deps
	@$(MAKE) install-dev

install-dev: venv
	@if [ -f requirements.txt ]; then "$(PY)" -m pip install -r requirements.txt; fi
	@if [ -f requirements-dev.txt ]; then "$(PY)" -m pip install -r requirements-dev.txt; fi
	@for mod in ruff mypy pytest; do \
		$(PY) -c "import importlib; importlib.import_module('$$mod')" >/dev/null 2>&1 || { \
			echo "missing $$mod; update requirements.lock/requirements-dev.txt instead of implicit install"; \
			exit 1; \
		}; \
	done

lint: install-dev
	$(RUFF) check .

typecheck: install-dev
	$(MYPY) src

# Les suites importent ``nexus_contracts`` : elles dépendent donc de la cible
# qui l'installe. ``install-dev`` ne pose que l'outillage de développement et
# ne fournit pas le contrat ; une cible qui s'y arrêtait échouait par
# ModuleNotFoundError dès qu'elle n'était pas précédée d'un ``make install``
# manuel — ce qui était le cas du job « governance postgres ».
test: install
	PYTHONPATH=src $(PYTEST) -q -m "not integration"

test-integration: install
	PYTHONPATH=src $(PYTEST) tests/integration -q

test-integration-hybrid: install
	bash infra/scripts/test_hybrid_integration.sh

# Suites de gouvernance sur PostgreSQL REEL (G2). Perimetre volontairement
# etroit : uniquement les suites qui prouvent les invariants gouvernes
# (migration 013, LOT42-V2, attribution H2-F, rollbacks, concurrence).
# Le e2e Docker authority en est exclu : il construit une image et n'est pas
# dimensionne pour bloquer chaque PR.
# Chaque suite demarre son propre conteneur jetable et le supprime ; aucune
# base partagee, aucun credential durable, aucun secret CI necessaire.
# Deux barrières, parce qu'une seule laisserait une porte ouverte :
#  1. le préflight refuse avant même de lancer pytest, avec un message
#     identique en CI et en local (script partagé) ;
#  2. NEXUS_REQUIRE_DOCKER=1 transforme, DANS pytest, l'absence de Docker
#     en erreur de collecte — ce qui couvre une invocation directe de
#     pytest qui contournerait cette recette.
# La valeur est imposée ici et jamais héritée de l'appelant : un
# environnement mal configuré ne doit pas pouvoir désactiver la barrière.
test-governance-pg: install
	bash infra/scripts/require_docker.sh
	NEXUS_REQUIRE_DOCKER=1 PYTHONPATH=src $(PYTEST) -q \
	    tests/integration/test_lot42_v2_migration_013.py \
	    tests/integration/test_h2f_artifact_attribution_pg.py \
	    tests/integration/test_h2f_attribution_concurrency_pg.py \
	    tests/integration/test_lot42_publication_attestation.py \
	    tests/integration/test_lot44f_migration_rollback_rehearsal.py \
	    tests/integration/test_lot44f_migration_upgrade_paths.py \
	    tests/integration/test_lot44f_rollback_runner.py \
	    tests/integration/test_lot44e_worker_e2e.py

# Smoke RAG deja present (si votre repo inclut infra/scripts/smoke.sh)
smoke:
	@if [ -x infra/scripts/smoke.sh ]; then bash infra/scripts/smoke.sh; else echo "No infra/scripts/smoke.sh"; fi

# Observabilite (nomenclature compatible avec vos derniers commits)
# Utilise les profils Compose db,llm,api,obs + env file s'il existe
obs-up:
	@ENV_FILE="infra/.env"; [ -f infra/.env.ci ] && ENV_FILE="infra/.env.ci"; \
	echo "-> env: $$ENV_FILE"; \
	COMPOSE_PROFILES=db,llm,api,obs docker compose \
	  -f infra/docker-compose.yml \
	  -f infra/docker-compose.obs.yml \
	  -f infra/docker-compose.obs.override.yml \
	  --env-file "$$ENV_FILE" \
	  up -d --remove-orphans

obs-down:
	@ENV_FILE="infra/.env"; [ -f infra/.env.ci ] && ENV_FILE="infra/.env.ci"; \
	COMPOSE_PROFILES=db,llm,api,obs docker compose \
	  -f infra/docker-compose.yml \
	  -f infra/docker-compose.obs.yml \
	  -f infra/docker-compose.obs.override.yml \
	  --env-file "$$ENV_FILE" \
	  down --remove-orphans

obs-restart: obs-down obs-up


obs-status:
	@docker compose -f infra/docker-compose.yml ps || true

obs-smoke:
	@if [ -x infra/scripts/obs_smoke.sh ]; then bash infra/scripts/obs_smoke.sh; \
		else \
			echo "No infra/scripts/obs_smoke.sh"; \
		fi

obs-quickcheck:
	@if [ -x infra/scripts/metrics_quickcheck.sh ]; then \
		PROM_URL=$${PROM_URL:-http://127.0.0.1:19090} \
		TARGET_URL=$${TARGET_URL:-http://127.0.0.1:18001/metrics} \
		bash infra/scripts/metrics_quickcheck.sh; \
	else \
		echo "infra/scripts/metrics_quickcheck.sh manquant (non bloquant)"; \
	fi

compose-test-up:
	@docker compose -f infra/docker-compose.test.yml up -d --remove-orphans

dev:

compose-test-down:
	@docker compose -f infra/docker-compose.test.yml down --remove-orphans

print-tools:
	@echo "PY         = $(PY)"
	@$(PY) -c "import shutil; print('RUFF path  = ' + (shutil.which('ruff') or '(module)'))"
	@$(PY) -c "import shutil; print('MYPY path  = ' + (shutil.which('mypy') or '(module)'))"
	@$(PY) -c "import shutil; print('PYTEST path= ' + (shutil.which('pytest') or '(module)'))"

dev:
	python -V && pip -V

compose-up:
	docker compose -f infra/docker-compose.yml --env-file infra/.env up -d

compose-down:
	docker compose -f infra/docker-compose.yml --env-file infra/.env down --remove-orphans

compose-restart: compose-down compose-up

# ═══════════════════════════════════════════════
# RAG SERVICE v2 — TARGETS
# ═══════════════════════════════════════════════

COMPOSE_V2=docker compose -f infra/docker-compose.v2.yml --env-file infra/.env
# LOT44f (ADR-0031) : plan de contrôle d'ingestion gouvernée — strictement
# opt-in, jamais chargé par $(COMPOSE_V2) seul (cf. docker-compose.ingestion.yml).
COMPOSE_V2_INGESTION=docker compose -f infra/docker-compose.v2.yml -f infra/docker-compose.ingestion.yml --env-file infra/.env

.PHONY: v2-up v2-down v2-build v2-pull-models v2-test v2-security-check v2-logs v2-ingestion-up v2-ingestion-down

## v2: Démarrage complet
v2-up:
	$(COMPOSE_V2) up -d --build --wait
	@echo "✅ RAG Service v2 démarré"

## v2: Arrêt
v2-down:
	$(COMPOSE_V2) down

## v2-ingestion: Démarrage explicite du plan de contrôle d'ingestion gouvernée (opt-in, LOT44f/ADR-0031)
# Remédiation revue PR#90 (Cubic P1, revue incrémentale) : sans --wait, cette
# cible annonçait toujours succès dès que `up -d` retournait — y compris si
# migrator-ingestion-control avait déjà échoué (exit != 0) ou si
# ingestion-worker ne devenait jamais healthy (gate LOT44c refusé, DSN
# invalide, etc.) : `up -d` seul ne fait qu'émettre les commandes de
# démarrage, il n'attend ni ne vérifie leur issue. `--wait` fait
# explicitement attendre et vérifier : (1) migrator-ingestion-control est un
# job ponctuel (`restart: "no"`) dont ingestion-worker dépend via
# `service_completed_successfully` — `--wait` échoue avec un code non-nul si
# ce job se termine en erreur, jamais un succès silencieux ; (2)
# ingestion-worker porte un healthcheck (heartbeat file, docker-compose.
# ingestion.yml) — `--wait` échoue aussi si le worker ne devient jamais
# healthy, ce qui couvre transitivement le gate LOT44c (un worker dont le
# gate refuse le démarrage ne touche jamais son heartbeat, donc reste
# unhealthy). Comportement vérifié empiriquement (deux scénarios : migrator
# en échec, worker jamais healthy — les deux font échouer `up --wait` avec
# un code de sortie non-nul, jamais un succès rapporté à tort).
v2-ingestion-up:
	$(COMPOSE_V2_INGESTION) up -d --build --wait migrator-ingestion-control ingestion-worker
	@echo "✅ Plan de contrôle d'ingestion (migrator + worker) démarré et vérifié sain — reste fail-closed sans manifest approuvé"

## v2-ingestion: Arrêt
v2-ingestion-down:
	$(COMPOSE_V2_INGESTION) down

## v2: Build images
v2-build:
	$(COMPOSE_V2) build --parallel

## v2: Vérifier le prérequis du modèle d'embedding certifié
v2-pull-models:
	@echo "intfloat/multilingual-e5-large (1024d) doit être préparé avant tout démarrage v2."
	@echo "Aucun téléchargement ou fallback de modèle n'est effectué par cette cible."

## v2: Tests
v2-test:
	$(PYTEST) tests/test_hybrid_search.py -v
	@echo "ℹ️  Integration tests require DATABASE_URL_TEST to be set"

## v2: Vérification sécurité (ports, secrets)
v2-security-check:
	@echo "🔒 Vérification des ports exposés..."
	@ss -tlnp 2>/dev/null | grep -E '5433|5434|5544|8000|9005|9006' && \
		echo "⚠️  ATTENTION : ports exposés sur 0.0.0.0" || \
		echo "✅ Aucun port sensible exposé"
	@echo ""
	@echo "🔑 Vérification des secrets..."
	@grep -r "CHANGE_ME\|ci_token\|ci_mdp\|password123" infra/.env 2>/dev/null && \
		echo "🔴 SECRETS PAR DÉFAUT DÉTECTÉS — Modifier immédiatement" || \
		echo "✅ Pas de secrets par défaut détectés"

## v2: Logs
v2-logs:
	$(COMPOSE_V2) logs -f ingestor pgvector prometheus
