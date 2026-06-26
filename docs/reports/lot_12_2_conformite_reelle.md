# Rapport — Lot 12.2 : Conformité contrat RÉELLE (model_validate)

## Architecture artefacts

- **`data/chunks/{niveau}/{matiere}_{notion}.jsonl`** : une ligne = un objet **strictement conforme `ChunkMeta`** (schema_version, chunk_id, doc_id, chunk_sha256, chunk_index, chunk_type=text, text, notions, token_count, char_count, retrieval_title, citation_label). `extra: forbid` respecté.
- **`data/chunks/{niveau}/{matiere}_{notion}.meta.json`** : sidecar **conforme `ChunkMetadata`** (tenant, niveau, voie, matiere, audience, type_doc, notions, source_label, source_uri, rights, official, doc_id). Porte les métadonnées de filtrage retrieval.

## Preuve par model_validate

```
ChunkMeta:     124/124 valid (model_validate)
ChunkMetadata:  16/16 valid (model_validate)
```

Test CI : `test_all_chunks_validate_chunkmeta` + `test_all_sidecars_validate_chunkmetadata` — échouent si un seul chunk n'est pas conforme.

## B4 corrigé

`fr_ratio` calculé sur échantillon réparti (50 premiers + 50 milieu + 50 derniers mots), pas seulement les 100 premiers.

## B6 clarifié

`dictionnaires` dans `notion_articles.yml` avec article `Tableau_associatif` (existant). Absent du staging car au-delà du pilote 5 notions/matière. La couverture reste 16/30 pour le pilote ; `dictionnaires` sera couvert à l'élargissement.

## A3 (exposants)

`x<sup>2</sup>` → `x 2` (espacé par BS4 get_text). Acté au BACKLOG (DETTE-12-A) : améliorer vers `x^2` ou collage. Non bloquant car le texte reste lisible et le contenu préservé.

## CI locale : 7/7 PASS, 11/11 chunk tests PASS
