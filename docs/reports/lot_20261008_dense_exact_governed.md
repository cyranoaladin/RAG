# Lot 2026-10-08 — rappel dense exact sur le périmètre gouverné

## Fait et décision

La sonde staging mixte V4/V5 référencée dans l'ADR-0065 trouve douze visites
chunk–scope manquantes : leur vecteur stocké est pourtant au rang un en SQL
exact. L'index HNSW global choisissait le préfixe avant que le scope gouverné
ne soit entièrement établi. Le canal dense matérialise maintenant les chunks
admissibles avant de calculer la distance exacte et de limiter le préfixe à
201 lignes. La projection des citations, la limite de sortie 200, les filtres
de droits et de placement et le refus d'égalité à la frontière 200/201 restent
en place. Le canal lexical et le contrat API ne changent pas.

## Vérification de ce lot

Code testé au commit `3e22c0f2337f7092e35e34a0ab76ebca33fce211`, arbre
`services/rag-engine` `c18cc677e9c4eab34a0b4620d7218e3f93b38fa3`.
Depuis `services/rag-engine`, les commandes et résultats étaient :

```bash
PYTHONPATH=src /tmp/nexus-exact-retrieval-venv-3cef/bin/pytest -q \
  tests/test_retrieval_pg_v2.py tests/test_retrieval_hybrid_v2.py \
  tests/test_retrieval_v2_endpoint.py
# 261 tests collectés, 261 réussis ; exit 0
/tmp/nexus-exact-retrieval-venv-3cef/bin/ruff check \
  src/ingestor/retrieval_pg_v2.py tests/test_retrieval_pg_v2.py \
  tests/test_retrieval_v2_endpoint.py \
  tests/integration/test_lot40_hybrid_pgvector.py
# All checks passed! ; exit 0
/tmp/nexus-exact-retrieval-venv-3cef/bin/mypy src/ingestor/retrieval_pg_v2.py
# Success: no issues found in 1 source file ; exit 0
git diff --check 96f7506af14847c8084f07ed597995e029f5c63d \
  3e22c0f2337f7092e35e34a0ab76ebca33fce211
# exit 0
```

Le nouveau test
`test_dense_materializes_governed_eligible_rows_before_exact_distance`
a d'abord échoué (`ValueError: substring not found` sur la CTE absente),
puis est passé après le correctif. Les commandes ci-dessus portent sur le même
arbre de code ; le présent complément documentaire ne modifie pas cet arbre.
Le test `test_dense_exact_channel_skips_inert_hnsw_setup` a également échoué
avant suppression du `SET LOCAL hnsw.iterative_scan`, puis est passé ; cette
suppression retire une requête de préparation sans changer le SQL dense.

- L'agrégat exact de la sonde staging qui a motivé le lot est archivé dans
  `docs/reports/evidence/retrieval_probe_mixed_diagnostic_20261008.json` ;
  son digest et sa commande de génération figurent dans l'ADR-0065.
- Au commit `00b03a6f2bf813206139bd863ba615156d7d7eee`, une base pgvector
  éphémère migrée de 001 à 005 a servi le seul chunk autorisé
  en présence de cent chunks hors scope au même vecteur. La citation source
  était présente et le plan `EXPLAIN` n'utilisait pas
  `idx_rag_chunks_vector`. Le conteneur éphémère a été supprimé.
- L'assertion PostgreSQL réelle du runner hybride compare désormais le top 50
  sous `hnsw.ef_search=1` à l'oracle exact et vérifie le plan sans index HNSW.
  Son exécution complète reste une condition de la CI : le runner local a
  échoué avant collecte sur les dépendances de l'API historique dans
  `tests/integration/conftest.py`. L'installation du lock intégral a épuisé
  l'espace disque disponible et son venv partiel a été supprimé.

## Conditions encore ouvertes

La fusion de ce lot ne démontre ni la qualité des onze collections ni la
capacité C0. Rejouer la sonde dense complète sur le staging final : zéro
manque sur les scopes servis, aucun résultat hors scope, refus d'égalité
rapportés séparément. Rejouer ensuite la golden liée aux manifests finaux et
la charge C0 aux budgets fixés dans l'ADR-0065. Aucune preuve locale de ce
lot ne remplace ces mesures au SHA final.
