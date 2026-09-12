# Récupération d'espace disque — audit

- kind : `NEXUS-DISK-RECOVERY-AUDIT-V1`
- libre avant nettoyage : **30.4 Gio**
- libre après nettoyage : **95.8 Gio**
- récupéré : **65.4 Gio**
- plancher du gate : **40.0 Gio**
- manque : **0 o**
- `disk_policy_ok_before` : `False`
- `disk_policy_ok_after` : `True`

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
| 9 images Docker sans étiquette, non référencées | 9.8 Gio | `DELETE_CANDIDATE_SAFE` | aucune n'est référencée par un conteneur ; restes de rebuilds Node/Playwright d'autres chantiers, dont 16 des 6 dernières heures | `docker rmi d503b9da7ab6 5a5030af1c4a 643072082e49 69c27b74b058 970c7643de3f 1f81f263dd24 667495ca2ac3 13105d2858de` |
| cache de build Docker (buildx) | 69.2 Gio | `DELETE_CANDIDATE_NEEDS_CONFIRMATION` | cache pur, régénérable, aucune donnée ; mais la commande est un prune : elle n'énumère pas ce qu'elle emporte | `docker buildx prune --force` |
| ~/.cache/uv et ~/.cache/pip | 13.0 Gio | `DELETE_CANDIDATE_NEEDS_CONFIRMATION` | caches de paquets régénérables, hors de ce dépôt ; leur reconstruction coûte du réseau, pas des données | `uv cache clean; pip cache purge` |
| images E2E d'autres chantiers (agent-*, entitlement-*, core-v2-*) | — | `UNKNOWN_DO_NOT_TOUCH` | appartiennent à d'autres sessions ; leur cycle de vie ne se décide pas depuis ce dépôt | — |
| ~/nexus-claude-pr153-p2-20260908 (15 Gio) | 15.0 Gio | `UNKNOWN_DO_NOT_TOUCH` | copie de travail d'un lot antérieur, non enregistrée comme worktree ; sa valeur d'archive n'est pas établie ici | — |

## Ce qui est protégé

- volumes protégés : 2 nommés
- `vector_db_preserved` : `True`
- `review_db_preserved` : `True`

## Récupérable selon Docker

- images : 70.5 Gio
- cache de build : 3.1 Gio
- volumes au total : 210

## Ce qu'il resterait à récupérer

- borne haute sur les images sans étiquette : 105.6 Gio
- borne HAUTE : les images sans étiquette partagent des couches, le gain réel est inférieur à leur somme. Le besoin n'est que de 0 o.

## Ce qu'un humain a autorisé et exécuté, et ce que la mesure en a dit

| Commande | Gain estimé | Gain mesuré | Verdict |
|---|---:|---:|---|
| `docker rmi 3d53b92c6c57 80c4e806c15e a8c65404dc7c e67cac305711 c` | 49.5 Gio | **-2.0 Mio** | `ESTIMATION_DEMENTIE_PAR_LA_MESURE` |
| `docker buildx prune --force` | — | **70.7 Gio** | `PLANCHER_FRANCHI` |

> `docker images` affiche une taille VIRTUELLE, couches partagées comprises. Ces huit images partageaient presque toutes leurs couches avec des images encore étiquetées (core-v2-auth-*, entitlement-*) : supprimer le manifeste n'a libéré aucune donnée. Le pool d'images n'a cédé qu'environ 1 Go, et l'espace libre rien du tout.

> le cache de build ne porte aucune donnée : seul son temps de reconstruction est perdu. C'est la seule grande réserve dont la suppression ne coûte rien d'irremplaçable.

## Ce que ce script ne fait jamais

- il ne supprime rien : il n a aucun chemin d execution destructif
- il ne propose aucun prune global : ils n enumerent pas ce qu ils emportent, et une commande protegee est refusee a la construction
- il ne touche ni la base de revue, ni la base dediee, ni un volume, ni un artefact de modele

## Ce que ce lot ne prouve pas

- ne rend pas le corpus interrogeable : le blocage recherche reste ouvert et aucun vecteur n existe
- ne ferme aucun des six blocages de fond du go-live
