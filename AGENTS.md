# AGENTS.md — Plateforme RAG pédagogique (Nexus)

> Fichier canonique pour tous les agents de codage (Claude Code, Codex, Windsurf, Kimi).
> Pour Claude Code, `CLAUDE.md` à la racine importe ce fichier via `@AGENTS.md`.
> Concis et impératif. Ce qui est *non négociable* est protégé par la CI, pas par ce fichier.
> **Ne pas réécrire ce fichier sans instruction explicite : il gouverne tous les lots.**

## Structure

```
services/rag-pedago/   — plan de contrôle : gouvernance, taxonomie, acquisition, PII, droits, releases
services/rag-engine/   — plan de données : PostgreSQL/pgvector, placements, Worker B, retrieval hybride, API v2
services/cockpit/      — SaaS Next.js + BFF Auth.js : agents UI par niveau/profil
packages/contracts/    — nexus-contracts : contrat RetrievalRequest → RetrievalResponse (source de vérité)
packages/release-chain/, packages/pdf-*  — chaîne de release et politique PDF partagées
governance/            — autorisations, décisions PII, revues de publication, ancres de confiance
corpus/                — référentiels-source (matière première d'ingestion)
scripts/               — CI locale, gardes de gouvernance, go-live, qualification
docs/adr/              — Architecture Decision Records
docs/runbooks/         — procédures opératoires (go-live, rollback, incident, staging)
docs/ROADMAP.md        — gates jusqu'à la production
```

Décision fondatrice : ADR-0001 (séparation plan de contrôle / plan de données / cockpit).
Les `AGENTS.md` de service précisent leur périmètre ; en cas de contradiction, ce fichier et les ADR
acceptés prévalent, et la contradiction est signalée dans le rapport de lot. Cette précédence est
une consigne de lecture, pas un mécanisme des outils : tous les fichiers d'instructions sont
chargés ensemble, et une contradiction se corrige à la source.

## Règles cross-service (impératives)

- Le cockpit ne parle qu'au contrat de retrieval (via l'API `rag-engine`). Il n'accède jamais directement à pgvector ni aux documents bruts.
- Toute évolution du contrat passe par `packages/contracts` versionné en SemVer + un ADR. Ne jamais redéfinir le contrat localement dans un service.
- Aucun agent ni worker n'écrit dans pgvector sans être passé par `quality → gate → review`. Aucune écriture directe.
- Aucun agent externe n'accède à PostgreSQL : l'accès externe passe par une API authentifiée qui parle le contrat de retrieval (voir `docs/agentic/EXTERNAL_AGENT_ACCESS.md`).
- Ne jamais passer un verrou `*_allowed` de `services/rag-pedago/configs/pedago_interface_contract.yml` à `true` par effet de bord. Toute activation suit `transition_authorization.yml` + un ADR.
- Un service n'importe jamais directement le code d'un autre service ; la communication passe par le contrat ou par API.
- Utiliser `git mv` pour tout déplacement de fichier ; préserver l'historique.
- Un lot = une branche = une PR = un rapport dans `docs/reports/lot_<n>_*.md`. Rien n'est commité sur `main` hors PR.
- Un lot travaille dans son propre git worktree ; ne jamais modifier le worktree ou la branche d'un autre lot actif.
- Ne jamais committer de secret (clés, tokens, identifiants, seeds de readiness) ni de PII élève. Ne jamais les afficher dans une sortie ou un rapport.
- Aucun chemin absolu machine-local dans le code versionné : dériver les racines de l'emplacement des fichiers, avec override par variable d'environnement.

## Faits : statique, scellé, live

Toute affirmation sur l'état du projet déclare sa catégorie :

- **STATIC** — architecture, invariants, procédures : lus dans le dépôt.
- **SEALED** — manifestes, SHA, ADR, releases, autorisations signées : recalculables depuis Git ; citer le SHA ou l'empreinte.
- **LIVE** — `main`, PR, CI, serveur, base, conteneurs, jobs : **relus à la source avant chaque décision**
  (`git fetch`, `gh`, sonde). Un instantané committé (README, `go_live_readiness_state.json`, rapport)
  n'est jamais l'état courant ; un souvenir d'agent non plus.

## Preuves et tests

- N'affirmer qu'un test, un contrôle ou une CI est passé que si on l'a exécuté ou relu sur le SHA exact ; citer la commande et le résultat.
- Un test synthétique ou une fixture ne prouve pas le scénario réel ; le dire explicitement.
- Toute vérification échoue fermée (fail-closed) : entrée manquante, ambiguë ou non vérifiable ⇒ refus, jamais succès par défaut.
- Une donnée produite (release, preuve, décision) porte sa provenance : source, SHA, commande, auteur de la décision.

## Go-live et opérations live

- `CI verte ≠ GO_LIVE_READY`. La seule garde de déploiement est
  `python3 scripts/go_live/check_go_live_readiness.py --assert-ready` exécuté en direct, complété par la
  définition de `docs/agentic/GO_LIVE_DEFINITION_OF_DONE.md`.
- Toute opération live (SSH, migration, publication staging, bascule `current`, déploiement, fusion ou
  fermeture de PR, révocation) exige une autorisation humaine explicite pour cette opération précise.
  Une autorisation passée ne couvre pas l'opération suivante.
- Avant toute opération live : préflight écrit (cible, SHA, commande, effet attendu, rollback), relecture
  de l'état live, puis arrêt au point d'autorisation humain défini par le runbook.

## Conventions

- Python ≥ 3.11. Qualité : `ruff` (lint), `mypy` (types), `pytest` (tests). Respecter les `pyproject.toml`/`Makefile` de chaque service.
- Documentation et contenu pédagogique en français.
- Nomenclature des tenants : `{population}_{niveau}` (`libre_terminale`, `aefe_seconde`, …).
- Messages de commit impératifs et scopés par service (`rag-engine: …`, `cockpit: …`).

## Commandes

Par service (depuis `services/<svc>`) :
- `make install` — installe `nexus-contracts` en éditable puis le service (disponible sur `rag-pedago` et `rag-engine`).
- `make lint`, `make typecheck`, `make test` — qualité et tests.
- `make smoke` — quand disponible (rag-engine) ; `make test-integration*` exige Docker.
- CI locale : `bash scripts/ci-local.sh` depuis la racine.
- Configuration agentique : `python3 -m pytest -q scripts/tests/test_claude_config.py` (voir `docs/agentic/`).

## Garde-fous CI (non négociables, vérifiés automatiquement)

- Aucun lot ne fait régresser les tests : aucun test vert ne passe au rouge. Un lot peut être livré avec des échecs **préexistants**, à condition qu'ils soient tracés dans `docs/reports/*_dettes.md` avec antériorité prouvée contre le commit parent.
- Test de contrat sur `nexus-contracts` (import + golden queries de `rag-pedago/tests/golden_queries/`).
- `scripts/check-governance-locks.sh` : comparaison clé par clé des verrous de gouvernance contre `scripts/governance-locks.baseline`. Aucune clé verrouillée ne peut passer à `true` sans ADR référencé sur une ligne ajoutée.
- La CI GitHub Actions (`.github/workflows/ci.yml`) fait foi sur le SHA exact de la PR puis de `main`. Si elle est indisponible, la CI locale (`scripts/ci-local.sh`) verte et consignée dans le rapport de lot tient lieu de garde-fou.

## Qualité des métriques

- Une métrique de couverture ou de complétude doit mesurer la **substance** (une ressource qui enseigne réellement la notion), jamais la simple présence d'une référence générique. Un contrôle de qualité doit s'exercer sur **tout** son périmètre, pas un échantillon. Tout « vert » non démontré sur son périmètre réel est suspect et doit être prouvé.

## Escalade

Si un lot exige de toucher une logique métier hors de son périmètre, ou de lever un verrou de gouvernance : s'arrêter et le signaler dans le rapport de lot. Ne pas l'implémenter de sa propre initiative.
