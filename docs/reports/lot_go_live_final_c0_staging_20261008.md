# Lot go-live : charge C0 du staging final

Le banc `scripts/go_live/staging_c0_load.py` exerce la vraie route `POST /search/v2` du staging final sous identité teacher signée, avec les 33 requêtes positives des 11 collections du registre mixte V4/V5. Il vérifie la collection, la citation et l'identité de contenu de chaque résultat, puis exige qu'au moins un résultat porte la source attendue. Il mesure les connexions du rôle `rag_reader` sur `ragdb_profile_gate_v4`. Les secrets restent dans les fichiers d'environnement opérateur ; le rapport contient les empreintes des requêtes, collections, scopes, statuts, latences et détails d'erreur.

Le budget historique reste intact, car son empreinte est liée à une preuve antérieure. `docs/reports/go_live/concurrency_load_budget_final_v4_v5.json` fixe avant mesure les mêmes seuils numériques pour la nouvelle population : 8 clients, 240 requêtes, p50 ≤ 3000 ms, p95 ≤ 6000 ms, p99 ≤ 7500 ms, zéro erreur, zéro timeout et au plus 10 connexions de retrieval. Le mandat opérateur du 8 octobre nomme explicitement **C0** ce profil de 8 clients et 240 requêtes ; il remplace la nomenclature de l'ancien plan, où C0 était séquentiel et C1 concurrent. Le nouveau budget est distinct : il ne ferme pas l'ancien C1 et ne revendique pas ses vérifications de résidus après arrêt du moteur, car le service staging reste en marche. Le runner refuse un checkout différent du `main` **interrogé en direct sur origin**, un registre mixte divergent, une suite ou un budget hors des chemins canoniques, une API autre que le loopback staging et une base autre que `ragdb_profile_gate_v4`.

Commande sur l'hôte staging, dans un venv propre créé depuis le checkout exact de `main` après fusion de la suite finale et qualification du runtime API (variables secrètes chargées hors journal) :

```bash
python scripts/go_live/staging_c0_load.py \
  --suite services/rag-engine/tests/fixtures/final_v4_v5_acceptance.json \
  --budget docs/reports/go_live/concurrency_load_budget_final_v4_v5.json \
  --api-url http://127.0.0.1:18003 \
  --output /srv/nexus-staging/qualification/final-c0-20261008.json
```

La fixture finale apportée par #291 est présente sur `main` `96f7506af14847c8084f07ed597995e029f5c63d` ; le runner vérifie ce fichier versionné avant toute requête. Cette PR livre le banc, **pas un verdict de charge**. Le seul verdict opposable sera le rapport issu du staging final après preuve des 74 jobs V5 réussis et de l'identité du conteneur API, de sa base et du registre V4/V5. Le rapport est écrit atomiquement dans un répertoire privé et ne remplace jamais une mesure antérieure. Une citation sans page reste valide selon le contrat ; le contrôle détaillé des bornes de pages appartient à la qualification de contenu. Aucun seuil ne sera déplacé pour rendre une mesure rouge verte.

Validation locale du code et des tests au SHA `b59d705b95fd7a080a1b4f434e3ff068609fe2dd` (tree `05d4e21d038dfb758501165a89436443f9ccbeee`, base `main` `96f7506af14847c8084f07ed597995e029f5c63d`) :

| Commande | Résultat |
| --- | --- |
| `/tmp/nexus-c0-venv-ec7429b6/bin/python -m pytest -q services/rag-engine/tests/test_staging_c0_load.py` | exit 0 ; 12 tests réussis |
| `ruff check services/rag-engine/tests/test_staging_c0_load.py scripts/go_live/staging_c0_load.py` | exit 0 ; `All checks passed!` |
| `python -m json.tool docs/reports/go_live/concurrency_load_budget_final_v4_v5.json >/dev/null` | exit 0 |
| `git diff --check` | exit 0 |

Le test du répertoire permissif force maintenant le mode `0755` indépendamment du `umask`. La mesure live reste à exécuter ; ce tableau ne constitue pas une preuve de charge.
