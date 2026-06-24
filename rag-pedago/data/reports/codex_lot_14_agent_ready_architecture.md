# Rapport Codex — Lot 14 : agent-ready architecture

## Objectif

Rendre le projet clair, maintenable et exploitable par des agents ou LLM de
développement, sans ajouter d'ingestion documentaire ni ouvrir de `source_uri`.

## Fichiers créés

- `docs/ARCHITECTURE.md`
- `docs/WORKFLOWS.md`
- `docs/LOT_STATUS.md`
- `docs/contracts/README.md`
- `docs/contracts/pipeline_contract.yml`
- `docs/contracts/runtime_artifacts.yml`
- `docs/contracts/commands.yml`
- `docs/contracts/invariants.yml`
- `rag_pedago/project_doctor.py`
- `schema/README.md`
- `rag_pedago/imports/README.md`
- `rag_pedago/ledger/README.md`
- `rag_pedago/reference/README.md`
- `taxonomy/README.md`
- `data/fixtures/README.md`
- `data/reference/README.md`
- `data/reports/README.md`
- `tests/README.md`
- `tests/unit/test_project_contracts.py`
- `tests/unit/test_project_doctor.py`

## Fichiers modifiés

- `README.md`
- `AGENTS.md`
- `Makefile`

## Tests

- `python3 -m pytest tests/unit/test_project_contracts.py tests/unit/test_project_doctor.py -q`
- `make doctor`
- `make test`
- `make project-doctor`
- `make ledger-init`
- `make ledger-doctor`

## Résultats

- Documentation racine réécrite pour décrire l'état réel du projet.
- Guide agent ajouté avec ordre de travail, interdictions et règles de lot.
- Architecture et workflows documentés.
- Contrats YAML machine-readable ajoutés.
- `project-doctor` ajouté pour vérifier docs, contrats, `.gitignore`, secrets
  évidents, imports réseau interdits et absence de pattern d'ouverture
  `source_uri`.
- README locaux ajoutés dans les dossiers critiques.

## Limites

- Aucun parsing PDF.
- Aucune ouverture de `source_uri`.
- Aucun appel réseau.
- Aucune connexion Qdrant ou PostgreSQL.
- Aucun LLM runtime.
- Aucune ingestion documentaire réelle.

## Prochaine étape recommandée

Créer un lot d'export ou tableau de bord de l'audit ledger avant tout futur lot
d'ingestion documentaire contrôlée.
