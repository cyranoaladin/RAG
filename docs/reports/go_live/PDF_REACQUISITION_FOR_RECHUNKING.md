# Réacquisition des PDF pour le re-découpage

- kind : `NEXUS-PDF-REACQUISITION-FOR-RECHUNKING-V1`
- périmètre : `SERVABLE_CANDIDATE_SET` — 2264 contenus
- empreinte du périmètre : `227617d4c4364dda1267b15bb30005a26a329414bc151f3c3e5f4c5362a1fbdd`
- portée Drive : `NEXUS_RAG/NEXUS_RAG_GDRIVE_READY`
- accès : lecture seule : copie descendante uniquement
- racine du miroir : variable `NEXUS_DRIVE_MIRROR_DIR`

## Couverture

| Mesure | Valeur |
|---|---:|
| PDF attendus | 2264 |
| PDF réacquis | **2264** |
| **PDF manquants** | **0** |
| octets réacquis | 1510611111 |
| objets du miroir | 2583 |
| `sha256_verified` | `True` |

> empreinte sha256 recalculée sur les octets rapatriés, comparée à l'identité de contenu de la matrice — le nom de fichier n'est pas utilisé

## Contenus refusés par le gate

- présents dans le miroir : 266
- qui seront re-découpés : **0**

Le miroir couvre tout le Drive autorisé, donc aussi des contenus que le gate refuse. Le re-découpage n'itère que sur la liste blanche : aucun refusé n'entre dans l'indexation.

## Secrets

- `tokens_versioned` : **0**
- `tokens_not_versioned` : `True`
- `rclone_config_not_reprinted` : `True`
- `GOOGLE_OAUTH_REVOCATION_DEFERRED_BY_HUMAN` : `True`

La révocation OAuth est différée par décision humaine explicite. Aucun jeton n'est reproduit ici, ni dans aucun artefact versionné.

## Ce que ceci ne prouve pas

- ne produit aucun chunk : les octets sont rapatriés, pas découpés
- ne produit aucun vecteur
- ne rend pas le corpus interrogeable
