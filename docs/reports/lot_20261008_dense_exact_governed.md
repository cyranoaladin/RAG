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

- TDD : le nouveau test `test_dense_materializes_governed_eligible_rows_before_exact_distance`
  a échoué sur l'absence de CTE admissible, puis est passé après le correctif.
- Les suites ciblées `test_retrieval_pg_v2.py`, `test_retrieval_hybrid_v2.py` et
  `test_retrieval_v2_endpoint.py` passent dans le venv isolé pointant vers ce
  worktree. Ruff sur les fichiers modifiés, mypy sur le module SQL et
  `git diff --check` passent.
- Une base pgvector éphémère migrée de 001 à 005 a servi le seul chunk autorisé
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
