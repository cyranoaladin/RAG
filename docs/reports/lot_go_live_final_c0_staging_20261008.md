# Lot go-live : charge C0 du staging final

Le banc `scripts/go_live/staging_c0_load.py` exerce la vraie route `POST /search/v2` du staging final sous identité teacher signée, avec les 33 requêtes positives des 11 collections du registre mixte V4/V5. Il vérifie chaque résultat (collection, source de référence, citation) et mesure les connexions du rôle `rag_reader` sur `ragdb_profile_gate_v4`. Les secrets restent dans les fichiers d'environnement opérateur ; le rapport contient seulement les empreintes de requêtes et les statuts.

Le budget historique reste intact, car son empreinte est liée à une preuve antérieure. `docs/reports/go_live/concurrency_load_budget_final_v4_v5.json` fixe avant mesure les mêmes seuils numériques pour la nouvelle population : 8 clients, 240 requêtes, p50 ≤ 3000 ms, p95 ≤ 6000 ms, p99 ≤ 7500 ms, zéro erreur, zéro timeout et au plus 10 connexions de retrieval. Le mandat opérateur du 8 octobre nomme explicitement **C0** ce profil de 8 clients et 240 requêtes ; il remplace la nomenclature de l'ancien plan, où C0 était séquentiel et C1 concurrent. Le nouveau budget est distinct : il ne ferme pas l'ancien C1 et ne revendique pas ses vérifications de résidus après arrêt du moteur, car le service staging reste en marche. Le runner refuse un checkout différent du `main` **interrogé en direct sur origin**, un registre mixte divergent, une suite ou un budget hors des chemins canoniques, une API autre que le loopback staging et une base autre que `ragdb_profile_gate_v4`.

Commande sur l'hôte staging, dans un venv propre créé depuis le checkout exact de `main` après fusion de la suite finale et qualification du runtime API (variables secrètes chargées hors journal) :

```bash
python scripts/go_live/staging_c0_load.py \
  --suite services/rag-engine/tests/fixtures/final_v4_v5_acceptance.json \
  --budget docs/reports/go_live/concurrency_load_budget_final_v4_v5.json \
  --api-url http://127.0.0.1:18003 \
  --output /srv/nexus-staging/qualification/final-c0-20261008.json
```

Cette PR dépend de la fixture finale apportée par #291. Elle livre le banc, **pas un verdict de charge**. Le seul verdict opposable sera le rapport issu du staging final après publication des 74 jobs V5 et après preuve de l'identité du conteneur API, de sa base et du registre V4/V5. Le rapport est écrit atomiquement dans un répertoire privé et ne remplace jamais une mesure antérieure. Une citation sans page reste valide selon le contrat ; le contrôle détaillé des bornes de pages appartient à la qualification de contenu. Aucun seuil ne sera déplacé pour rendre une mesure rouge verte.

Validation locale de l'implémentation : `cd services/rag-engine && PYTHONPATH=src pytest -q tests/test_staging_c0_load.py` (12 tests), Ruff et `git diff --check` verts. La mesure live reste à exécuter.
