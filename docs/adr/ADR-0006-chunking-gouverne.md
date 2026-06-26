# ADR-0006 — Chunking gouverné

- **Statut** : Accepté
- **Date** : 2026-06-26
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0004 (ingestion agentique), ADR-0005 (multi-agents)

## Contexte

16 notions de contenu propre sont en staging (chrome éliminé, prouvé 0/16). Le chunking est la prochaine étape avant embedding et indexation. Il doit être gouverné (gated) comme le parsing.

## Décision

- `chunking_allowed: true` — scope : découpage en chunks du contenu propre en staging.
- N'autorise PAS les embeddings (`embeddings_allowed` reste false) ni l'ingestion corpus (`ingestion_allowed` reste false).
- Le script de chunking vérifie le verrou avant d'agir (gating réel, exit 1 sinon).
- Les chunks préservent intégralement les métadonnées (notion_id, matiere, niveau, voie, statut_enseignement, audience, source, rights) pour le retrieval filtré.

## Conséquences

- Les chunks sont des artefacts versionnés (`data/chunks/`), révisables avant embedding.
- Le chunking est déterministe (deux exécutions = même résultat).
