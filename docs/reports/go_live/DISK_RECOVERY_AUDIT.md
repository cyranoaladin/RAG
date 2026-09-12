# Récupération d'espace disque — audit

- kind : `NEXUS-DISK-RECOVERY-AUDIT-V1`
- libre avant : **34.8 Gio**
- plancher du gate : **40.0 Gio**
- manque : **5.2 Gio**
- `disk_policy_ok_before` : `False`

> 34,85 Gio et 37,42 Go sont la MÊME mesure : gibioctets contre gigaoctets décimaux. Il n'y a pas deux relevés qui divergent.

## Inventaire classé

| Élément | Taille | Catégorie | Raison | Commande proposée |
|---|---:|---|---|---|
| base de revue PII nexus-drive-staging-v2 (+ son volume) | — | `KEEP_REVIEW_PII` | seul support rendant rejouables 149 décisions PII, dont 23 promues | — |
| base dédiée nexus_vector_staging_a_20260912T060731Z (+ son volume) | — | `KEEP_VECTOR_DB` | cible de la phase A ; porte la liste blanche des 2264 autorisés | — |
| /backup/rag/non-pdf-reacquired | 6.8 Mio | `KEEP_BACKUP` | store durable qui ferme non_pdf_servable_reacquired=37 | — |
| ~/nexus-backups (sauvegarde de la base de revue) | 124.9 Mio | `KEEP_BACKUP` | restauration prouvée du corpus de revue ; 125 Mo, gain nul | — |
| ~/rag-model-artifacts/intfloat-multilingual-e5-large-3d7cfbda… | 9.0 Gio | `KEEP_MODEL_ARTIFACT` | révision EXACTE épinglée par le manifeste et vérifiée au préflight | — |
| ~/.cache/huggingface (E5, bge-reranker-v2-m3, bge-m3, MiniLM) | 8.6 Gio | `KEEP_MODEL_ARTIFACT` | artefacts de modèle ; interdits de suppression par le mandat | — |
| 24 images Docker sans étiquette, non référencées | 53.2 Gio | `DELETE_CANDIDATE_SAFE` | aucune n'est référencée par un conteneur ; restes de rebuilds Node/Playwright d'autres chantiers, dont 16 des 6 dernières heures | `docker rmi 3d53b92c6c57 80c4e806c15e a8c65404dc7c e67cac305711 ccc96b0650e4 8838b3c6cc1c fa9d6bbdd381 a1c7447f7d46` |
| cache de build Docker (buildx) | 127.5 Gio | `DELETE_CANDIDATE_NEEDS_CONFIRMATION` | cache pur, régénérable, aucune donnée ; mais la commande est un prune : elle n'énumère pas ce qu'elle emporte | `docker buildx prune --force` |
| ~/.cache/uv et ~/.cache/pip | 13.0 Gio | `DELETE_CANDIDATE_NEEDS_CONFIRMATION` | caches de paquets régénérables, hors de ce dépôt ; leur reconstruction coûte du réseau, pas des données | `uv cache clean; pip cache purge` |
| images E2E d'autres chantiers (agent-*, entitlement-*, core-v2-*) | — | `UNKNOWN_DO_NOT_TOUCH` | appartiennent à d'autres sessions ; leur cycle de vie ne se décide pas depuis ce dépôt | — |
| ~/nexus-claude-pr153-p2-20260908 (15 Gio) | 15.0 Gio | `UNKNOWN_DO_NOT_TOUCH` | copie de travail d'un lot antérieur, non enregistrée comme worktree ; sa valeur d'archive n'est pas établie ici | — |

## Ce qui est protégé

- volumes protégés : 2 nommés
- `vector_db_preserved` : `True`
- `review_db_preserved` : `True`

## Récupérable selon Docker

- images : 72.6 Gio
- cache de build : 62.5 Gio
- volumes au total : 205

## Après, si l'humain confirme

- estimation haute : 88.0 Gio
- borne HAUTE : les images sans étiquette partagent des couches, le gain réel est inférieur à leur somme. Le besoin n'est que de 5.2 Gio.
- suppressions exécutées par ce lot : **0**

## Ce que ce lot ne fait pas

- aucune suppression : toutes les commandes sont proposées, aucune lancée
- aucun prune global : ils n'énumèrent pas ce qu'ils emportent
- ne rend pas le corpus interrogeable : le blocage recherche reste ouvert
