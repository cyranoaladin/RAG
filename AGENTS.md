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

Par service (depuis `services/<svc>`) :
- `make install` — installe `nexus-contracts` en éditable puis le service (disponible sur `rag-pedago` et `rag-engine`).
- `make lint`, `make typecheck`, `make test` — qualité et tests.
- `make smoke` — quand disponible (rag-engine).
- CI locale : `bash scripts/ci-local.sh` depuis la racine.

## Garde-fous CI (non négociables, vérifiés automatiquement)

- Aucun lot ne fait régresser les tests : aucun test vert ne passe au rouge. Un lot peut être livré avec des échecs **préexistants**, à condition qu'ils soient tracés dans `docs/reports/*_dettes.md` avec antériorité prouvée contre le commit parent.
- Test de contrat sur `nexus-contracts` (import + golden queries de `rag-pedago/tests/golden_queries/`).
- `scripts/check-governance-locks.sh` : comparaison clé par clé des verrous de gouvernance contre `scripts/governance-locks.baseline`. Aucune clé verrouillée ne peut passer à `true` sans ADR référencé sur une ligne ajoutée.
- Tant que GitHub Actions est indisponible, la CI locale (`scripts/ci-local.sh`) verte et consignée dans le rapport de lot tient lieu de garde-fou.

## Qualité des métriques

- Une métrique de couverture ou de complétude doit mesurer la **substance** (une ressource qui enseigne réellement la notion), jamais la simple présence d'une référence générique. Un contrôle de qualité doit s'exercer sur **tout** son périmètre, pas un échantillon. Tout « vert » non démontré sur son périmètre réel est suspect et doit être prouvé.

## Escalade

Si un lot exige de toucher une logique métier hors de son périmètre, ou de lever un verrou de gouvernance : s'arrêter et le signaler dans le rapport de lot. Ne pas l'implémenter de sa propre initiative.
