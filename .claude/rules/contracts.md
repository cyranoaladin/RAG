---
paths:
  - "packages/contracts/**"
  - "packages/release-chain/**"
---

# Contrat partagé `nexus-contracts`

- Source de vérité unique du contrat `RetrievalRequest → RetrievalResponse` ;
  aucun service ne le redéfinit localement.
- Toute modification publique : version SemVer dans `pyproject.toml` (rupture ⇒
  majeure), ADR, et schémas régénérés :
  `python packages/contracts/scripts/export_schemas.py --output packages/contracts/schema`
  puis `--check` vert.
- Les consommateurs (rag-pedago, rag-engine, cockpit, scripts) se recensent par
  `grep` avant tout changement ; leurs tests tournent dans le même lot.
- Les golden queries de `services/rag-pedago/tests/golden_queries/` restent vertes.
- Le futur accès des agents externes consomme ce contrat, jamais la base
  (`docs/agentic/EXTERNAL_AGENT_ACCESS.md`).
