# Rapport — Lot 12 : Chunking gouverné

## Levée tracée

`chunking_allowed: true # ADR-0006` dans le contrat, transition_authorization, et baseline. ADR-0006 versionné. `embeddings_allowed`, `qdrant_allowed`, `ingestion_allowed` restent false. Garde-fou 17/17.

## Stratégie de chunking

- **Cible** : ~750 tokens par chunk (600-900 range)
- **Overlap** : ~12% (préserve le contexte entre chunks adjacents)
- **Frontières** : paragraphes et phrases (pas de coupure mid-mot/mid-phrase)
- **Gating** : `check_chunking_allowed()` vérifié avant exécution, exit 1 sinon

## Résultats

| Matière | Notions | Chunks | Moy. chunks/notion |
|---|---|---|---|
| mathematiques | 5 | 54 | 10.8 |
| nsi | 5 | 21 | 4.2 |
| philosophie | 4 | 46 | 11.5 |
| grand_oral | 2 | 2 | 1.0 |
| **Total** | **16** | **123** | **7.7** |

## Validation substance

- 123/123 chunks : `navigation_suspected=False`
- 123/123 chunks : longueur ≥ 50 chars (pas de chunk trivial)
- 123/123 chunks : toutes les métadonnées requises présentes (notion_id, matiere, niveau, voie, statut_enseignement, audience, source, rights)
- Déterminisme : deux exécutions = chunks identiques

## Tests (9/9 PASS)

- Gating : false→blocked, true→allowed, vide→blocked, absent→blocked
- Chunks : exist, metadata complètes, pas trivial, pas de chrome, déterministe

## Dettes BACKLOG

- DETTE-11.5-A/B inscrites + périmètre acquisition documenté

## CI locale : 7/7 PASS
