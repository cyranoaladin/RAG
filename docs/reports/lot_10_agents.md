# Rapport — Lot 10 : Architecture multi-agents orchestrée

## ADR-0005

Architecture à 3 niveaux :
- **OrchestratorAgent** : dispatch par niveau, agrège, gouvernance
- **LevelAgent** (3e/2de/1re/Tle) : découvre taxonomies par glob, instancie SubjectAgents
- **SubjectAgent** (matière/niveau/statut) : connaît sa taxonomie, fetch par notion

## Classes créées

| Module | Rôle |
|---|---|
| `agents/base.py` | `AcquisitionAgent` (interface : plan/fetch/report, vérification verrous) |
| `agents/subject_agent.py` | Fetch par notion, dépôt staging, rapport found/not_found |
| `agents/level_agent.py` | Découverte taxonomies, orchestration séquentielle |
| `agents/orchestrator.py` | Dispatch niveaux, agrégation hiérarchique, CLI |

Zéro hardcoding de matière/notion — tout dérive de la taxonomie + registre.

## Registre de sources

`data/sources/registre_sources.yml` : 10 entrées (Wikipedia FR + Wikiversité FR) pour 8 matières, chacune avec licence vérifiée et statut robots.txt.

## Tests (3/3 PASS)

- `test_subject_agent_plan` : plan correct depuis taxonomie
- `test_subject_agent_refuses_when_staging_not_allowed` : verrou respecté
- `test_orchestrator_checks_ingestion_blocked` : ingestion=true → blocage

## Dettes BACKLOG intégrées

- DETTE-9.1-A : mono-mot ≥8 chars compté found_exact
- DETTE-9.1-B : headings structurels dans bo_only

## CI locale : 7/7 PASS, garde-fou 17/17, ingestion_allowed=false
