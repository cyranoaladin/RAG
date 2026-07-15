# LOT 27 P3 — audit de mapping Chroma legacy vers pgvector v2

Date : 2026-07-16 (UTC).
Périmètre strictement en lecture seule : aucune écriture Chroma ou pgvector, aucune ingestion, restauration, migration, suppression de volume ni redémarrage n'a été réalisé.

## État de départ

- Release active : `rag-v2-main-27a4558-lot27p3-20260715T133534Z`, commit `27a4558a1abca304d415240b9ec0c06000cd2db5`.
- `rag_chunks` pgvector v2 est vide.
- L'API v2 déclare 35 collections ; les deux collections NSI retrievable ne retournent aucun hit.
- Chroma legacy `compose-chroma-1` reste actif sur le volume `compose_rag_ui_chroma_data`.

## Contrat pgvector et embedding v2

| Élément | Constat |
|---|---|
| Colonne de vecteur v2 | `rag_chunks.vector vector(1024)` avec index HNSW cosine. |
| Contrat documentaire et code de retrieval/ingestion v2 | `intfloat/multilingual-e5-large`, 1024 dimensions. |
| Modèle Ollama réellement présent | `nomic-embed-text:v1.5`, 768 dimensions. |
| Compose v2 réellement configuré | `EMBED_MODEL=nomic-embed-text:v1.5`, `EMBED_DIM=768`. |
| Cohérence | **Incohérente** : le compose/runtime 768d ne peut pas écrire dans la colonne 1024d ; le modèle e5-large n'est pas présent dans l'inventaire Ollama. |

Cette incohérence doit être corrigée et validée dans un lot distinct avant toute reprise de données. Elle interdit aussi une migration directe des vecteurs Chroma.

## Inventaire Chroma legacy

Les dimensions proviennent d'échantillons API Chroma v2 de trois embeddings par collection non vide. Aucun document long n'a été extrait.

| Collection | Chunks | Dimension | Métadonnées observées | Qualification |
|---|---:|---:|---|---|
| `nsi_corpus_v2` | 5 992 | 768 | `level`, `notion`, `theme`, `document_type`, `path`, `sha256`, `status`, `source_type` | Corpus NSI structuré. |
| `nsi_corpus` | 4 716 | 768 | `level`, `notion`, `theme`, `document_type`, `path`, `sha256`, `status`, `source_type` | Corpus NSI structuré, antérieur/recouvrant. |
| `rag_education` | 7 181 | 768 | `matiere`, `niveau`, `groupe`, `source`, `drive_file_id`, `sha256` | Mélange documentaire ; l'échantillon est NSI mais porte « Première et Terminale » sans séparation par chunk. |
| `rag_francais_premiere` | 5 948 | 768 | `matiere`, `niveau`, `source`, `page`, `sha256` | Hors NSI ; l'échantillon indique Français / Sixième malgré le nom legacy. |
| `rag_math_correction` | 67 | 768 | `exam_id`, `question_id`, `content_hash`, `source_path`, `sha256` | Hors NSI ; matériel de correction à qualifier. |
| `rag_maths_premiere` | 0 | — | — | Collection vide. |
| `rag_divers` | 0 | — | — | Collection vide. |
| `ressources_pedagogiques_terminale` | 0 | — | — | Collection vide. |

### Classification exhaustive des deux corpus NSI

| Collection | Première | Terminale | Niveau absent | Remarque |
|---|---:|---:|---:|---|
| `nsi_corpus_v2` | 2 700 | 3 292 | 0 | Tous les chunks sont `needs_review`. |
| `nsi_corpus` | 1 930 | 2 356 | 430 | Les 430 chunks sans niveau ne sont pas routables vers une collection NSI pédagogique. |

`nsi_corpus` comporte 4 716 hash de chunks distincts et 494 chemins source ; `nsi_corpus_v2` 451 hash distincts et 452 chemins source. Ils ont 84 hash et 447 chemins source communs : une déduplication de contenu et de provenance est obligatoire avant toute reprise.

## Doublons et collisions

- 23 904 IDs legacy ont été lus sans documents ; 20 306 IDs sont uniques.
- 3 598 IDs sont dupliqués entre `rag_education` et `rag_francais_premiere`.
- Aucun ID identique n'est partagé entre `nsi_corpus` et `nsi_corpus_v2`, mais les hash et chemins communs prouvent un recouvrement de sources.
- Les noms de collections legacy ne suffisent pas pour déterminer le niveau, la matière ou la voie ; le routage doit être fait chunk par chunk à partir des métadonnées et de la source, avec revue humaine en cas d'ambiguïté.

## Mapping proposé (dry-run)

| Source Chroma | Cible v2 proposée | Confiance | Action | Justification |
|---|---|---|---|---|
| `nsi_corpus_v2`, `level=premiere` | `rag_nexus_nsi_premiere_specialite` | Haute | Réingérer après déduplication | Matière NSI implicite, niveau explicite, provenance et hash disponibles ; vecteurs 768d incompatibles. |
| `nsi_corpus_v2`, `level=terminale` | `rag_nexus_nsi_terminale_specialite` | Haute | Réingérer après déduplication | Même preuve, niveau explicite. |
| `nsi_corpus`, `level=premiere` | `rag_nexus_nsi_premiere_specialite` | Moyenne | Réingérer après comparaison avec v2 | Métadonnées exploitables, mais recouvrement fort avec `nsi_corpus_v2`. |
| `nsi_corpus`, `level=terminale` | `rag_nexus_nsi_terminale_specialite` | Moyenne | Réingérer après comparaison avec v2 | Même réserve de dédoublonnage. |
| Corpus NSI sans niveau | `rag_nexus_quarantine` | Basse | Quarantaine + revue humaine | Niveau absent : affectation NSI Première/Terminale interdite. |
| `rag_education` | Collections futures seulement après qualification | Basse | Export de métadonnées + classification | Mélange probable ; ne pas injecter en bloc dans NSI. |
| `rag_francais_premiere` | Future collection Français ou quarantaine | Moyenne | Réingérer après qualification | Ne doit jamais être routé vers NSI ; incohérence de niveau observée. |
| `rag_math_correction` | Future collection examen/maths ou quarantaine | Basse | Revue humaine | Hors NSI et sémantique de correction spécifique. |
| Collections legacy vides | Aucune | Haute | Ignorer | Aucun chunk à reprendre. |

## Décision : migration directe interdite

| Contrôle | Résultat | Décision |
|---|---|---|
| Dimension Chroma | 768 | Incompatible avec `vector(1024)`. |
| Modèle Chroma | Nomic 768d documenté et observé | Non interopérable avec e5-large 1024d. |
| Contrat runtime v2 | Compose 768d, schéma/code 1024d | Corriger et prouver l'alignement avant toute reprise. |
| Métadonnées NSI | Partiellement suffisantes, avec ambiguïtés et recouvrements | Réingestion depuis sources avec dédoublonnage et revue. |
| Vecteurs legacy | Ne peuvent pas être copiés vers pgvector v2 | **Migration directe interdite.** |

## Plan de reprise proposé (non exécuté)

1. Corriger le contrat d'embedding v2 : un seul modèle, une seule dimension et un test bloquant schéma/modèle/runtime.
2. Réaliser un backup approuvé de pgvector et du volume Chroma avant toute mutation.
3. Exporter hors production les IDs et métadonnées Chroma nécessaires, sans documents non autorisés, puis bâtir un manifeste de dédoublonnage par `sha256`, chemin source et hash de contenu normalisé.
4. Qualifier humainement les chunks NSI sans niveau, les collections mixtes et les incohérences de niveau.
5. Réingérer les sources approuvées via `quality → gate → review`, jamais par copie de vecteurs legacy.
6. Écrire avec `review_status=needs_review`, contrôler les métadonnées v2 obligatoires et valider les collections v2 explicitement.
7. Accepter la reprise seulement si les collections NSI Première et Terminale ont des chunks, les recherches de fumée retournent des hits, aucune collection legacy n'est exposée, et les backups sont vérifiés.

## Risques ouverts

- Incohérence active du contrat d'embedding 768/1024.
- Perte ou double comptage sans dédoublonnage des corpus NSI recouvrants.
- Mauvais routage pédagogique pour les chunks sans niveau ou les collections mixtes.
- Les sources legacy peuvent contenir des champs insuffisants pour satisfaire le schéma v2 sans enrichissement et revue.

## Conclusion

`LOT_27_P3_MAPPING_AUDIT_COMPLETE_REINGEST_RECOMMENDED`.

La donnée legacy est présente et partiellement qualifiable, mais la migration directe est bloquée par l'incompatibilité d'embeddings et les collisions de provenance. Une réingestion gouvernée, précédée de l'alignement du runtime embedding et d'un plan de déduplication/revue, est la seule reprise sûre.
