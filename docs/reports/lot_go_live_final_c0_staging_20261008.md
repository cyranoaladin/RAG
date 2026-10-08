# Lot go-live : charge C0 du staging final

Le banc `scripts/go_live/staging_c0_load.py` exerce la vraie route `POST /search/v2` du staging final sous identité teacher signée, avec les 33 requêtes positives des 11 collections du registre mixte V4/V5. Il vérifie chaque résultat (collection, source de référence, citation) et mesure les connexions du rôle `rag_reader` sur `ragdb_profile_gate_v4`. Les secrets restent dans les fichiers d'environnement opérateur ; le rapport contient seulement les empreintes de requêtes et les statuts.

Le profil et les seuils numériques de `docs/reports/go_live/concurrency_load_budget.json` sont inchangés : 8 clients, 240 requêtes, p50 ≤ 3000 ms, p95 ≤ 6000 ms, p99 ≤ 7500 ms, zéro erreur, zéro timeout et au plus 10 connexions de retrieval. Seule la désignation de la suite de requêtes est remplacée par la fixture finale V4/V5, avant sa mesure. Le runner refuse un checkout différent de `origin/main`, un registre mixte divergent, une API autre que le loopback staging et une base autre que `ragdb_profile_gate_v4`.

Commande sur l'hôte staging, après fusion de la suite finale et qualification du runtime API (variables secrètes chargées hors journal) :

```bash
python scripts/go_live/staging_c0_load.py \
  --suite services/rag-engine/tests/fixtures/final_v4_v5_acceptance.json \
  --budget docs/reports/go_live/concurrency_load_budget.json \
  --api-url http://127.0.0.1:8001 \
  --output /srv/nexus-staging/qualification/final-c0-20261008.json
```

Cette PR livre le banc, **pas un verdict de charge**. Le seul verdict opposable sera le rapport issu du staging final après publication des 74 jobs V5 et après preuve de l'identité du conteneur API, de sa base et du registre V4/V5. Aucun seuil ne sera déplacé pour rendre une mesure rouge verte.

Validation locale de l'implémentation : `cd services/rag-engine && PYTHONPATH=src pytest -q tests/test_staging_c0_load.py` (6 tests), Ruff et `git diff --check` verts. La mesure live reste à exécuter.
