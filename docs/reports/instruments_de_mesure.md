# Les instruments construits pendant l'audit

> Liste tenue parce qu'un instrument oublié ne vaut pas mieux qu'un instrument absent.
> Le 2026-09-01, un état a été déclaré irrécupérable alors que l'instrument capable de le
> trouver existait depuis deux jours, écrit pour une autre question.

**À consulter avant de déclarer une absence, une impossibilité, ou une équivalence.**

| instrument | ce qu'il répond | où |
|---|---|---|
| **balayage par empreinte de contenu** | ce contenu existe-t-il quelque part dans le dépôt, sous n'importe quel nom, y compris dans un objet orphelin ? | `git cat-file --batch-all-objects` + sha256 de chaque blob |
| **`--qui-atteste`** | quelles chaînes portent ce fichier ? à appeler AVANT toute écriture | `reseal_release_authorities.py` |
| **outil de rescellement, dix faces** | rescelller en refusant motif générique, autorité absente, chaîne hors portée, sauvegarde impossible | idem |
| **comparaison d'échecs par NOMS** | deux suites de même cardinal ont-elles les mêmes échecs ? | `comm` sur les listes `FAILED` triées |
| **contrôle à deux témoins** | l'instrument discrimine-t-il ? un positif qui doit passer, un négatif qui doit échouer | partout |
| **reconstruction depuis `source_tree_sha`** | cette attestation rejoue-t-elle exactement depuis le commit qu'elle déclare ? | `test_production_release_scope_placement.py` |
| **vérification d'archive d'image** | l'archive contient-elle cette image, et entière ? sha256 de la config = identifiant ; chaque couche contre son blob | `tar` + sha256 |
| **table des montages** | ce répertoire est-il lu par la production, et relu quand ? | `docs/reports/lot_1c_table_des_montages.md` |

## Les pièges rencontrés, et ce qui les a trouvés

| piège | ce qui l'a démasqué |
|---|---|
| mesurer `rag_chunks` là où l'autorité est `rag_artifact_placements` | une question posée sur un autre sujet |
| deux accesseurs d'une même propriété (`importlib.metadata` / `__version__`) | un témoin appelé pour autre chose |
| `docker exec python` inspecte un NOUVEAU processus | le journal du conteneur, qui contredisait |
| `$?` après un tube rend le code du dernier maillon | la vraisemblance du résultat |
| `comm` sur fichiers mal triés | la rondeur du chiffre rendu |
| une cause attribuée par recherche de son texte | le retrait de la cause, et le recomptage |
