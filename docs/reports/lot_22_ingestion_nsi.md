# LOT 22 — Ingestion NSI gouvernée (clôture)

**Branche** : `lot-22-ingestion-nsi`
**Date** : 1er juillet 2026
**Statut** : **COMPLET** — T-22-1 à T-22-5 exécutés.

---

## Volumétrie réelle (SELECT count(*))

| Métrique | Valeur |
|---|---|
| **Total chunks en base** | **22 518** |
| `rag_nexus_nsi_premiere_specialite` | 7 143 |
| `rag_nexus_nsi_terminale_specialite` | 15 375 |
| Documents uniques (`doc_id`) | 1 762 |
| Chunks en quarantaine | **0** |
| Estimation initiale | ~20 031 |
| Écart estimation/réel | +12 % (petits docs → min 1 chunk) |

## Type_doc (réel)

| type_doc | Chunks |
|---|---|
| notebook | 8 418 |
| annale | 4 342 |
| evaluation | 3 935 |
| autre | 1 408 |
| cours | 1 336 |
| programme_officiel | 1 001 |
| corrige | 901 |
| tp | 850 |
| td | 231 |
| fiche_synthese | 96 |

## F-01 Citabilité

| Critère | Résultat |
|---|---|
| Chunks sans `rights` | **0** |
| Chunks sans `source_label` | **0** |
| Chunks sans `doc_id` | **0** |
| **F-01 satisfait** | **oui** |

## Quarantaine

`rag_nexus_quarantine` : **0 chunk**. Aucun contenu douteux lisible identifié — correct.

Holding list (non embeddée) : 70 fichiers (37 `.ipynb` JSON corrompus, 30 PDFs scannés, 3 `.docx` corrompus).

## Golden queries (T-22-5)

6 requêtes, 3 par collection, scoping `WHERE collection = ?` :

| Query | Collection | Top-1 sim | Citable | Source |
|---|---|---|---|---|
| algorithme tri insertion | Première | 0.8803 | oui | tri_par_insertion.pdf |
| protocole TCP IP réseau | Première | 0.8719 | oui | cours_ihm.pdf |
| base de données SQL | Première | 0.8492 | oui | 8.Bases_de_donnees_cours.pdf |
| arbre binaire parcours | Terminale | 0.8954 | oui | Eval2_Arbres_binaires.odt |
| programmation dynamique | Terminale | 0.8764 | oui | tnsi_13_progr_dyn_exos.pdf |
| pile file structure de données | Terminale | 0.8910 | oui | 4_PilesFiles.pdf |

Tous les hits portent `rights=usage_interne`, `source_label` non vide, `doc_id` non vide. **Citabilité F-01 satisfaite sur 100 % des résultats.**

Quarantaine ne remonte **jamais** : 0 chunk dans `rag_nexus_quarantine`, isolation confirmée.

## Exécution

| Étape | Résultat |
|---|---|
| T-22-1 staging | Manifest ratifié (1 763 docs) |
| T-22-2 parsing + chunking | 22 519 chunks (dry-run), tokenizer e5 réel à 480 tokens |
| T-22-3 embedding + INSERT | 22 518 chunks insérés, 2 runs (crash NUL corrigé + resume), 163+72 min CPU |
| T-22-4 quarantaine | 70 en holding, 0 en collection quarantaine |
| T-22-5 validation | F-01 satisfait, golden queries OK, quarantaine isolée |

## Incidents

1. **CUDA OOM** (GPU 3,6 GiB trop petit) → basculé en CPU (`CUDA_VISIBLE_DEVICES=""`)
2. **NUL bytes** dans un PDF → `psycopg.DataError` → corrigé par `.replace("\x00", "")`, reprise `--resume`
3. Dépendances manquantes (`sentence-transformers`, `psycopg`) → installées

## Dettes

- R1 (dédup base-name), R2 (30 PDFs scannés OCR), R3 (chunker proxy) — consignées dans `lot_0_dettes.md`
- `notions[]` vide (B7) — dette assumée LOT 22
- `review_status = needs_review` sur tous les chunks — revue humaine à planifier
