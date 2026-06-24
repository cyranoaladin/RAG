# Rapport — Lot 0 : Fondations monorepo + contrat partagé

## Objectif

Réorganiser le dépôt en monorepo, extraire le contrat partagé `nexus-contracts`, adapter `rag-pedago`, corriger la dette doc de `rag-engine`, mettre en place la CI racine.

## Déplacements `git mv`

| Source | Destination |
|---|---|
| `rag-pedago/` | `services/rag-pedago/` |
| `rag-local/` | `services/rag-engine/` |
| `REFERENTIEL_CANDIDAT_LIBRE.md` | `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` |
| `Tronc_commun/` | `corpus/Tronc_commun/` |
| `Specialites/` | `corpus/Specialites/` |
| `docs/adr/ADR-0001-...` | déjà en place |

## Package `nexus-contracts` (v0.1.0)

Fichiers créés dans `packages/contracts/` :

- `pyproject.toml`
- `src/nexus_contracts/__init__.py`
- `src/nexus_contracts/document.py`
- `src/nexus_contracts/student_profile.py`
- `src/nexus_contracts/retrieval.py`

Exports publics : `RetrievalRequest`, `RetrievalResponse`, `RetrievalNeed`, `RetrievalOptions`, `RetrievalResult`, `Citation`, `StudentProfile`, `StatusDetail`, `DocumentMeta`, `ChunkMeta`, et toutes les enums (`Niveau`, `Voie`, `TypeDoc`, `Rights`, etc.).

## Ré-exports dans `rag-pedago`

Les fichiers `schema/{document,student_profile,retrieval}.py` de `rag-pedago` ont été remplacés par des ré-exports (`from nexus_contracts.<module> import *`). Les imports existants `from schema.retrieval import ...` continuent de fonctionner.

Dépendance ajoutée : `nexus-contracts` dans `pyproject.toml` (installé via `pip install -e ../../packages/contracts` en dev/CI).

## Correction du chemin `rag_pedago/paths.py`

`REPO_ROOT` et `RAG_LOCAL_ROOT` mis à jour pour refléter la nouvelle structure (`services/rag-pedago`, `services/rag-engine`).

## Résultat des suites de tests

### rag-pedago

| Métrique | Valeur |
|---|---|
| Total tests exécutés | 976 |
| Passed | 975 |
| Failed (pré-existant) | 1 (`test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail` — assertion sur valeur de statut, sans lien avec la restructuration) |
| Exclu (bug pytest pré-existant) | `test_real_draft_unlock_gate` — monkey-patch de `Path.exists()` provoque un INTERNALERROR pytest |

### Garde-fou gouvernance

- `allowed: false` count : **17** (avant) → **17** (après). Inchangé.
- Script `scripts/check-governance-locks.sh` : **PASS**.

### README rag-engine

- Mentions de ChromaDB comme stockage cible : **3** (avant) → **0** (après).
- Remplacé par `PostgreSQL + pgvector`.

## Fichiers de contexte agent

- `AGENTS.md` racine : créé (structure, règles cross-service, garde-fous).
- `CLAUDE.md` racine : créé, importe `@AGENTS.md`.
- `services/rag-engine/AGENTS.md` : créé.
- `services/cockpit/AGENTS.md` : créé.
- `services/rag-pedago/AGENTS.md` : conservé, chemins mis à jour.
- Aucun `SKILLS.md` créé.

## CI racine

`.github/workflows/ci.yml` avec 4 jobs : `contracts`, `rag-pedago`, `rag-engine`, `governance-locks`.

## Déviations

- `nexus-contracts` ne peut pas être déclaré comme dépendance `file://` relative dans `pyproject.toml` (limitation pip). Déclaré comme `nexus-contracts` simple, installé séparément via `pip install -e ../../packages/contracts` en CI et dev.
- 1 test pré-existant en échec (`test_real_draft_guard`), non lié au lot.
- 1 test exclu (`test_real_draft_unlock_gate`) à cause d'un bug pré-existant de monkey-patching.

## Aucune logique métier modifiée

Seuls des déplacements, ré-exports, corrections de chemins et documentation ont été effectués.
