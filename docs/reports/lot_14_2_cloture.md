# Rapport — Lot 14.2 : Clôture pgvector

## Corrections

1. **psycopg dans requirements.lock** : regeneré avec `psycopg==3.3.4` + `psycopg-binary==3.3.4`. `make install` neuf importe psycopg.

2. **DSN aligné sur compose** : défaut dérive de `PGVECTOR_PORT` (5433). `docker compose up` puis `python index_pgvector.py` fonctionne sans variable manuelle.

3. **Test rejet manifeste (sans DB)** : 4 tests — chunk non listé (not in manifest), sha divergent (≠), manifest loads correctly, manifest vide → bloque.

4. **DETTE-14-RAGENGINE** inscrite au BACKLOG : indexation doit migrer vers rag-engine avant exposition API.

## CI locale : 7/7 PASS, 9/9 index tests
