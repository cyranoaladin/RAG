# Lot go-live — adoption V2 bornée aux collections du successeur (ADR-0062)

## Constat (staging, 2026-10-02)

`successor_sealed_ingestion_or_binding` a été refusé par `adopt-predecessor-release`, avant toute écriture :

> `ADOPTION_REFUSED: the successor and the acquired placements are not in bijection: 0 prescribed but never acquired, 405 acquired but not prescribed — an adoption covers the whole release or nothing`

Vérifié ensuite en lecture seule : 0 adoption, 0 attestation successeur, 958 jobs inchangés, schéma de contrôle à 020.

## Cause

`load_acquired_rows(release_id=V4)` charge **tous** les placements acquis de V4 : 479 sur onze collections. `plan_adoption`
les compare aux 74 que le successeur HGGSP prescrit. Les 74 sont tous retrouvés (0 « prescribed but never acquired »),
mais les 405 autres, qui appartiennent aux neuf collections que V4 garde (ADR-0062), sont rejetés comme orphelins.
Le défaut n'est pas la bijection : c'est le **domaine** sur lequel elle est calculée.

Les épreuves précédentes réduisaient le prédécesseur à ce que le successeur prescrit
(`if row.content_sha256 in contents`, côté Python) : la sélection réelle n'était jamais exercée.

## Correctif

Une adoption V2 complémentaire est tout-ou-rien **dans les collections que le successeur possède**, pas sur toutes celles du prédécesseur.

- `load_acquired_rows(..., collections=None)` : sans `collections`, comportement historique inchangé (V1) ; avec, contrainte SQL `r.collection = ANY(%s)`. Une liste vide refuse.
- `successor_scope_collections(prescrits)` : le périmètre est **dérivé exclusivement des placements scellés du successeur**
  (refus s'il n'y en a aucun ou si l'un ne nomme pas de collection).
- `load_acquired_rows_in_successor_scope(...)` : la sélection que le CLI V2 utilise.
- `attest_publication_cli adopt-predecessor-release` : V2 seulement ; V1 garde la release entière.
- **Aucune option opérateur** : ni `--collection`, ni liste d'identifiants, ni sous-ensemble libre (testé sur le parseur).
- `plan_adoption` est inchangé. Seul le message change : « an adoption covers the whole predecessor scope selected by the successor's collections, or nothing ».

Le fail-closed est conservé **dans** le périmètre : 75 acquis pour 74 prescrits, 73, un `placement_id` ou un SHA divergent, un fait invariant divergent, un doublon refusent toute l'adoption.

## `OPERATOR_ID`

`worker()` reconstruit la commande distante avec `$*` ; une valeur avec espaces était coupée en plusieurs arguments.
`arg_shell()` (`printf %q`) l'échappe aux deux seuls sites (`--adopted-by`, `--bound-by`) : la valeur d'audit reste exactement
`Alaeddine Ben Rhouma`, sans guillemets stockés, comme **un seul argv**. L'identité est validée avant le premier appel distant.

## Provenance : le correctif est embarqué dans l'image Worker B

`sealed_release_adoption.py` et `attest_publication_cli.py` sont copiés dans l'image `rag-multilevel-worker-production`, qui exécute
`python -m ingestor.ingestion_worker.attest_publication_cli`. **Fusionner ce lot ne suffit pas** : il faut reconstruire l'image par le workflow
`production-image-provenance`, puis amender l'activation HGGSP (digest épinglé dans #270 et dans la readiness signée). Aucun
`PYTHONPATH` ni bind-mount du checkout n'est utilisé pour contourner la provenance.

## Qualification

| Preuve | Résultat |
|---|---|
| V4 acquis physiques | 479 (11 collections) |
| acquis V4 dans les collections du successeur | 74 |
| placements prescrits par le successeur | 74 |
| adoptions V2 écrites | 74 (74 ressources et 74 artefacts de contrôle successeurs distincts) |
| placements V4 hors périmètre, ressources et artefacts | 405, état identique avant et après |
| rejeu | `written=0`, `already_present=74`, aucune 75e adoption |
| 75 acquis / 73 acquis / placement divergent / fait divergent | refusés, **sans écriture** |
| `load_adopted_rows` | 74 identités successeur V2, aucune identité V4 |
| `bind_publication_authorities` | 74 liaisons, deux collections, 0 pour V4 |
| ancienne sélection sur PostgreSQL réel | refuse bien « 405 acquired but not prescribed » |

Commandes exécutées sur ce code :

- `pytest tests/integration/test_adoption_v2_collection_scope_pg.py` : 5 passed (PostgreSQL jetable, 479 placements) ;
- `pytest tests/integration/test_migration_018_sealed_release_adoption.py tests/integration/test_migration_020_successor_control_identity.py` : 20 passed (V1 et migration 020 inchangés) ;
- `pytest` des 7 fichiers unitaires d'adoption : 87 passed ; `mypy` des deux sources : propre ; `ruff` : propre ;
- `pytest scripts/qualification/tests/test_staging_hggsp_{orchestrator,chain,authorization}.py test_worker_b_guard.py` : 136 passed, 3 skipped
  (`test_premerge_run_fails_before_ssh` écarté : dette connue, non hermétique).

Limites : `verify_v2_lineage` (script) n'est pas rejoué sur ce schéma complet ; il est couvert par `test_real_postgres_148_historical_jobs_74_governed`
sur un schéma réduit. Les tests PostgreSQL utilisent des autorisations et des attributions de test ; ils ne prouvent pas le comportement sur le staging réel.
Aucun serveur n'a été utilisé.
