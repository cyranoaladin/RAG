# Re-découpage sous budget de tokens

- kind : `NEXUS-RECHUNK-PUBLICATION-TOKEN-BUDGET-V1`
- périmètre : `SERVABLE_CANDIDATE_SET` — 2264 contenus
- empreinte du périmètre : `227617d4c4364dda1267b15bb30005a26a329414bc151f3c3e5f4c5362a1fbdd`
- découpeur : `ingestor.publication_chunking.chunk_publication`
- compteur de tokens : `ingestor.embedding_provider.VerifiedE5EmbeddingProvider`
- budget visé : 384 tokens (limite du modèle : 512)

## Couverture

| Mesure | Valeur |
|---|---:|
| contenus autorisés | 2264 |
| avec octets PDF retrouvés | 2264 |
| **sans octets PDF** | **0** |
| sans texte extractible | 22 |
| contenus découpés | 2242 |
| chunks produits | **54719** |
| pages couvertes | 22875 |
| **chunks au-delà de la limite** | **0** |
| maximum de tokens observé | 384 |
| chunks dont un NUL a été retiré | 49 |
| octets NUL retirés | 203 |

## Exclusions

- `gate_refused_intersection` : 0
- `pii_undecided_intersection` : 0
- `currentness_refused_intersection` : 0
- `no_url_provenance_intersection` : 0
- `non_indexable_intersection` : 0

## Sûreté

- `review_db_read` : `False`
- `review_db_written` : `False`
- `written_to` : `drive_staging.publication_chunks (base dédiée)`

## Ce que ceci ne prouve pas

- ne produit aucun vecteur : le texte est découpé, pas indexé
- ne valide pas le retrieval
- ne rend pas le go-live prêt
