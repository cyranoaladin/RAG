# Lot go-live : import de la sonde HGGSP sur le staging final

Le 8 octobre, après les 74 jobs successeurs V5 réussis, le préflight indépendant a confirmé la base dédiée `ragdb_profile_gate_v4`, les anciens jobs HGGSP V4 inchangés, le sous-ensemble V5 `2/52/74/2590` et l'union `11/315/479/8268`. L'étape de sonde s'est arrêtée avant toute requête : `ModuleNotFoundError: No module named 'ingestor'`, puis `No module named 'identity_v2'`. Aucun compte de retrieval ne découle de cette tentative.

L'image de sonde épinglée contient les modules à plat sous `/app` mais ne définit pas `PYTHONPATH`. `python /repo/scripts/go_live/staging_retrieval_probe.py` ne place pas `/app` sur le chemin d'import. Le lancement V4 existant fournissait déjà `-e PYTHONPATH=/app` ; ce lot applique exactement ce paramètre au lancement HGGSP, sans changer l'image, le scope, la base ni l'algorithme. Un import direct des cinq modules concernés dans la même image et avec ce paramètre a réussi sur l'hôte staging.

La preuve recherchée reste la sortie réelle de `successor_independent_verification` sur le nouveau `main`, suivie d'une qualification HTTP et DB finale. Le préflight réussi ne vaut pas preuve de retrieval 11/11.
