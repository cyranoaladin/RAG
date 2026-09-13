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
- empreinte d'inventaire : `d0436ae704457fbb38315babd02491840eb3e92a1931c6810fe7779a2b5115df`
- statut : `VERIFIED_BY_CANONICAL_AUTHORITY`
- vérificateur : ingestor.embedding_contract.verify_embedding_artifact — appelée, son résultat est la source de ces champs
- ancre : la révision épinglée ; l'empreinte d'inventaire est calculée sur l'artefact et n'est donc pas une ancre externe — le dépôt n'en épingle aucune

## `vectorization_executed` : **True**

## Aptitude du corpus à l'embedding

| Mesure | Valeur |
|---|---:|
| limite de séquence du modèle | 512 tokens |
| chunks autorisés | 54719 |
| tiennent dans la limite | 54719 |
| **dépassent la limite** | **0** |
| maximum observé | 384 tokens |
| part du texte dans les chunks trop longs | **0.0 %** |
| apte à la vectorisation | `True` |

## Couverture exigée pour un succès

| Contrôle | Valeur |
|---|---:|
| `expected_vector_rows` | 54719 |
| `vector_rows_after` | **54719** |
| `expected_content_count_with_chunks` | 2242 |
| `distinct_vectorized_contents` | 2242 |
| `missing_authorized_contents_with_chunks` | 0 |
| contenus autorisés porteurs de chunks | 2242 |
| contenus autorisés SANS aucun chunk | 22 |

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
