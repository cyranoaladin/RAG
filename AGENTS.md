# AGENTS.md — Plateforme RAG pédagogique (Nexus)

> Fichier canonique pour tous les agents de codage (Claude Code, Codex, Windsurf, Kimi).
> Pour Claude Code, `CLAUDE.md` à la racine importe ce fichier via `@AGENTS.md`.
> Concis et impératif. Ce qui est *non négociable* est protégé par la CI, pas par ce fichier.
> **Ne pas réécrire ce fichier sans instruction explicite : il gouverne tous les lots.**

## Structure

```
services/rag-pedago/   — plan de contrôle : gouvernance, taxonomie, ingestion agentique
services/rag-engine/   — plan de données : pgvector, retrieval hybride (ex rag-local)
services/cockpit/      — SaaS Next.js : agents UI par niveau/profil
packages/contracts/    — nexus-contracts : contrat RetrievalRequest → RetrievalResponse (source de vérité)
corpus/                — référentiels-source (matière première d'ingestion)
docs/adr/              — Architecture Decision Records
docs/ROADMAP.md        — plan de phases et de lots
```

Décision fondatrice : ADR-0001 (séparation plan de contrôle / plan de données / cockpit).

## Règles cross-service (impératives)

- Le cockpit ne parle qu'au contrat de retrieval (via l'API `rag-engine`). Il n'accède jamais directement à pgvector ni aux documents bruts.
- Toute évolution du contrat passe par `packages/contracts` versionné en SemVer + un ADR. Ne jamais redéfinir le contrat localement dans un service.
- Aucun agent ni worker n'écrit dans pgvector sans être passé par `quality → gate → review`. Aucune écriture directe.
- Ne jamais passer un verrou `*_allowed` de `services/rag-pedago/configs/pedago_interface_contract.yml` à `true` par effet de bord. Toute activation suit `transition_authorization.yml` + un ADR.
- Un service n'importe jamais directement le code d'un autre service ; la communication passe par le contrat ou par API.
- Utiliser `git mv` pour tout déplacement de fichier ; préserver l'historique.
- Un lot = une branche = une PR = un rapport dans `docs/reports/lot_<n>_*.md`. Rien n'est commité sur `main` hors PR.
- Ne jamais committer de secret (clés, tokens, identifiants) ni de PII élève.
- Aucun chemin absolu machine-local dans le code versionné : dériver les racines de l'emplacement des fichiers, avec override par variable d'environnement.

## Conventions

- Python ≥ 3.11. Qualité : `ruff` (lint), `mypy` (types), `pytest` (tests). Respecter les `pyproject.toml`/`Makefile` de chaque service.
- Documentation et contenu pédagogique en français.
- Nomenclature des tenants : `{population}_{niveau}` (`libre_terminale`, `aefe_seconde`, …).
- Messages de commit impératifs et scopés par service (`rag-engine: …`, `cockpit: …`).

## Commandes

Par service (depuis `services/<svc>`) : `make install` (installe le contrat puis le service), `make lint`, `make typecheck`, `make test`, `make smoke` quand disponible.

## Garde-fous CI (non négociables, vérifiés automatiquement)

- Suites de tests de `rag-pedago` et `rag-engine` vertes sur le runner CI (pas seulement en local).
- Test de contrat sur `nexus-contracts` (import + golden queries de `rag-pedago/tests/golden_queries/`).
- `scripts/check-governance-locks.sh` : le compte de `allowed: false` dans `pedago_interface_contract.yml` ne diminue pas sans ADR référencé.

## Escalade

Si un lot exige de toucher une logique métier hors de son périmètre, ou de lever un verrou de gouvernance : s'arrêter et le signaler dans le rapport de lot. Ne pas l'implémenter de sa propre initiative.
