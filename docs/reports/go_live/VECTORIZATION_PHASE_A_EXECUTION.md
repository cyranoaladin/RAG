# Vectorisation phase A — exécution

- kind : `NEXUS-VECTORIZATION-PHASE-A-EXECUTION-V1`
- base dédiée : `nexus_vector_staging_a_20260912T060731Z` (`127.0.0.1:55436`)
- périmètre : `SERVABLE_CANDIDATE_SET` — 2264 contenus
- empreinte du périmètre : `227617d4c4364dda1267b15bb30005a26a329414bc151f3c3e5f4c5362a1fbdd`
- modèle : `intfloat/multilingual-e5-large` révision `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`
- dimension : 1024

## Provenance du modèle

- identifiant logique : `staging-phase-a-e5-large-3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`
- racine : variable `RAG_MODEL_ARTIFACTS_DIR` (aucun chemin de poste dans cette preuve)
- empreinte d'inventaire : `72b65af8c96d73e1c49e150e2809132efec1d22a108eb02d79ad673b4c0e4d01`
- statut : `VERIFIED_BY_CANONICAL_AUTHORITY`
- vérificateur : ingestor.embedding_contract.verify_embedding_artifact — appelée, son résultat est la source de ces champs
- ancre : la révision épinglée ; l'empreinte d'inventaire est calculée sur l'artefact et n'est donc pas une ancre externe — le dépôt n'en épingle aucune

## `vectorization_executed` : **False**

> 15630 chunks autorisés sur 23121 dépassent la limite de 512 tokens du modèle canonique (maximum observé : 12840). Ils portent 85.9 % du texte. Les indexer exigerait de les tronquer, donc d'indexer autre chose que ce qui est annoncé ; les ignorer produirait un index qui paraît couvrir le périmètre en laissant des contenus entiers inatteignables.

Manquements relevés :

- corpus inapte : des chunks dépassent la limite du modèle
- aucune couverture attendue : rien ne peut être certifié

## Aptitude du corpus à l'embedding

| Mesure | Valeur |
|---|---:|
| limite de séquence du modèle | 512 tokens |
| chunks autorisés | 23121 |
| tiennent dans la limite | 7491 |
| **dépassent la limite** | **15630** |
| maximum observé | 12840 tokens |
| part du texte dans les chunks trop longs | **85.9 %** |
| apte à la vectorisation | `False` |

## Couverture exigée pour un succès

| Contrôle | Valeur |
|---|---:|
| `expected_vector_rows` | 0 |
| `vector_rows_after` | **0** |
| `expected_content_count_with_chunks` | 0 |
| `distinct_vectorized_contents` | 0 |
| `missing_authorized_contents_with_chunks` | 0 |
| contenus autorisés porteurs de chunks | 2259 |
| contenus autorisés SANS aucun chunk | 5 |

Un index partiel n'est pas un succès partiel : c'est un échec.

## Contrôles d'exclusion

- `unauthorized_content_rows` : 0
- `pii_undecided_rows` : 0
- `currentness_refused_rows` : 0
- `gate_refused_rows` : 0
- `dimension_mismatch` : 0
- `null_vectors` : 0
- `duplicates` : 0
- `missing_authorized_contents_with_chunks` : 0

## Sûreté

- `review_db_written` : `False`
- `review_db_readonly_enforced_by` : `client_session_option`
- accès base de revue : lecture seule posée côté client (option de session default_transaction_read_only=on) ; NI le serveur NI le rôle ne l'imposent — l'imposer exigerait d'écrire dans la base de revue
- `pgvector_installed_in_review_db` : `False`
- `production_touched` : `False`
- `current_switch` : `False`
- `pii_decision` : `False`
- `release_modified` : `False`

## Retour arrière

```
docker rm -f nexus-vector-staging-a-20260912T060731Z && docker volume rm $(docker inspect nexus-vector-staging-a-20260912T060731Z --format '{{range .Mounts}}{{.Name}}{{end}}')
```

## Ce qu'il faut lever avant de réessayer

- re-découper le texte sous la limite de séquence du modèle : les chunks de staging ont été produits sans budget de tokens, et le découpeur canonique (chunk_publication) exige les octets du PDF, absents de la base de revue
- repointer la source de mesure de l'écart de recherche sur la base dédiée, sinon staging_vectors_present restera à zéro après une vectorisation réussie

## Ce que ceci ne prouve pas

- ne valide pas le retrieval applicatif
- ne valide pas les citations
- ne valide pas la latence
- ne valide pas les filtres de scope applicatifs
- ne rend pas le go-live prêt
