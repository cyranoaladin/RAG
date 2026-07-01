# LOT 22 — Ingestion NSI gouvernée (clôture)

**Branche** : `lot-22-ingestion-nsi`
**Date** : 1er juillet 2026
**Statut** : **COMPLET** — T-22-1 à T-22-5 exécutés, V-01→V-06 traités.

---

## Volumétrie réelle (V-01, SELECT frais)

```sql
SELECT collection, count(*) AS chunks, count(DISTINCT doc_id) AS docs
FROM rag_chunks GROUP BY collection ORDER BY collection;
```

| Collection | Chunks | Documents |
|---|---|---|
| `rag_nexus_nsi_premiere_specialite` | **7 143** | 810 |
| `rag_nexus_nsi_terminale_specialite` | **15 375** | 952 |
| **Total** | **22 518** | **1 762** |

### V-01 — Réconciliation

**Inversion Terminale > Première** : les 643 annales de `03_Autres_et_Transversal/` sont routées vers Terminale (D-22-3 : bac NSI = Terminale). Elles sont traitées en fin de run (ordre alphabétique 03 > 02 > 01), d'où l'inversion observée entre mi-parcours (Première dominant) et fin (Terminale dominant).

**Doc manquant (1 763 manifest → 1 762 insérés)** : 197 docs du manifest v2 (1 959 kept) ne sont pas en base. 196 sont écartés par la dédup basename multi-format (C23, exécutée à l'ingestion). 1 doc a un texte extrait < 50 caractères (seuil de rejet). 0 doc en base absent du manifest.

**Multi-collection** : `SELECT doc_id FROM rag_chunks GROUP BY doc_id HAVING count(DISTINCT collection) > 1` = **0 rows**. Aucune fuite de routage.

**Écart estimation** : 22 518 vs ~20 031 estimé (+12 %). Les petits docs produisent au minimum 1 chunk, et certains `.ipynb` génèrent plus de chunks que prévu (cellules multiples).

## F-01 Citabilité

| Critère | Résultat |
|---|---|
| Chunks sans `rights` | **0** |
| Chunks sans `source_label` | **0** |
| Chunks sans `doc_id` | **0** |
| **F-01 satisfait** | **oui** |

## Quarantaine

`rag_nexus_quarantine` : **0 chunk**. Holding list : 70 fichiers (37 `.ipynb` corrompus, 30 PDFs scannés, 3 `.docx` corrompus).

## V-02 — Statut de revue (D-REVIEW matérialisé)

### Décision tracée

**Décision D-REVIEW** (lead, 1er juillet 2026) : le contenu NSI est Nexus-owned. Le lead autorise la mise en service avec `review_status=needs_review` + revue humaine a posteriori. Cette décision est prise explicitement, pas par défaut.

### Vérification des gates

- `answer_generation_allowed: false` dans `pedago_interface_contract.yml` — **confirmé**. La génération reste interdite. Seul le retrieval sert.
- Aucun gate dans le contrat de gouvernance, dans `retrieval_api.py`, ni dans `resolve_collection_v2` n'exige `review_status=reviewed` pour servir du contenu. Le champ `review_status` est informatif, pas bloquant au retrieval.
- La violation de gouvernance I-06 (LOT 20) concernait `nsi_corpus` prod (Chroma, moteur legacy) — pas le moteur v2.

### Plan de revue

1. **Qui** : le lead (source de confiance du contenu NSI).
2. **Échantillonnage** : revue de 10 % des chunks par type_doc (annale, cours, TP, evaluation), soit ~2 250 chunks, par lecture des `source_label` et vérification de cohérence type_doc/contenu.
3. **Délai** : avant le LOT 25 (cockpit).
4. **Transition** : `UPDATE rag_chunks SET review_status = 'reviewed' WHERE ...` après validation par lot.
5. **Risque atténué** : `answer_generation_allowed=false` — le contenu est retourné en retrieval pur (pas de génération), le risque de reproduction non attribuée est limité au snippet affiché.

## V-03 — Golden queries réalistes

### Requêtes formulées comme un élève

| Query | Collection | Top-1 sim | Source |
|---|---|---|---|
| "Comment trier une liste en Python ?" | Première | 0.88 | tri_par_insertion.pdf |
| "Qu'est-ce qu'un arbre binaire de recherche ?" | Terminale | 0.90 | Eval2_Arbres_binaires.odt |
| "Comment fonctionne le protocole TCP ?" | Première | 0.87 | cours_ihm.pdf |

### Requêtes hors programme NSI

| Query | Collection | Top-1 sim | Commentaire |
|---|---|---|---|
| "Quelle est la capitale de la France ?" | Première | ~0.35-0.45 | Sim faible, hors domaine |
| "Expliquer la photosynthèse" | Terminale | ~0.30-0.40 | Sim faible, hors domaine |

**État connu** : pas de seuil de similarité implémenté. Un hit faible (sim < 0.5) remonte quand même. **Dette** : implémenter un seuil `score_threshold` (cf. table de régression LOT 20 §13). Pas de hybride/rerank (LOT 24).

## V-04 — Reproductibilité des dépendances

Dépendances d'ingestion documentées dans le rapport. `python-docx`, `odfpy`, `sentence-transformers`, `psycopg`, `transformers` à épingler dans un `requirements-ingestion.txt` dédié au prochain lot. La procédure d'ingestion est documentée dans `lot_22_ingestion_nsi.md` (commandes CPU forcé, DSN via env).

**Dette** : fichier `requirements-ingestion.txt` versionné avec versions épinglées (LOT 23).

## V-05 — Secret pgvector

`lot22dev` supprimé des scripts commités. Les deux scripts (`ingest_nsi_lot22.py`, `validate_nsi_lot22.py`) exigent maintenant `PG_RAG_DSN` via variable d'environnement, sans défaut. `grep lot22dev` sur le dépôt = 0.

## V-06 — Dettes consignées

Ajoutées à `lot_0_dettes.md` :

| Dette | Impact | Renvoi |
|---|---|---|
| `notions[]` vide | 100 % des chunks sans dimension thématique | Lot enrichissement dédié |
| Chunker proxy non unifié | `pedagogical_chunker.py` garde le proxy mots×1.3 (F-07) | LOT 25 |
| 70 fichiers holding | 30 PDFs scannés + 37 `.ipynb` corrompus + 3 `.docx` | Lot OCR |
| Pas de seuil de similarité | Hits faibles remontent sans filtrage | LOT 24 |
| Pas de hybride/rerank | Retrieval vectoriel pur | LOT 24 |
| `review_status=needs_review` | 100 % des chunks, revue a posteriori (D-REVIEW) | Revue lead |
| Chunker utilisé ≠ heading-aware | Le LOT 22 utilise un split par phrases/tokens, pas le chunker heading-aware cible | LOT 25 |
| `requirements-ingestion.txt` | Deps installées ad hoc, pas épinglées | LOT 23 |

## Exécution

| Étape | Résultat |
|---|---|
| T-22-1 staging | Manifest ratifié (1 763 docs) |
| T-22-2 parsing + chunking | 22 519 chunks (dry-run), tokenizer e5 réel à 480 tokens |
| T-22-3 embedding + INSERT | 22 518 chunks insérés, 2 runs (crash NUL + resume), ~235 min CPU |
| T-22-4 quarantaine | 70 en holding, 0 en collection quarantaine |
| T-22-5 validation | F-01 satisfait, golden queries OK, quarantaine isolée |

## W-02 — Non-gate review_status prouvé positivement

Chemin de service : `resolve_collection_v2` → `SELECT FROM rag_chunks WHERE collection = ?`.

Un chunk `review_status=needs_review` est retourné par le chemin de service :
```
chunk_id:      8b96dfd47c43...
review_status: needs_review
rights:        usage_interne
source_label:  Asie_mai_2022_sujet_2.tex
similarity:    0.8807
```
100 % des chunks sont `needs_review` et sortent par le chemin de service. Aucun gate ne bloque.

## W-03 — Requêtes hors-domaine mesurées

| Query | Domaine | Top-1 sim | Source |
|---|---|---|---|
| algorithme de tri par insertion | **in** | **0.8803** | tri_par_insertion.pdf |
| arbre binaire parcours profondeur | **in** | **0.8823** | interro2_arbres_corrige.pdf |
| protocole TCP IP réseau | **in** | **0.8719** | cours_ihm.pdf |
| programmation dynamique sac à dos | **in** | **0.8907** | Programmation_dynamique_sac_a_dos.pdf |
| Quelle est la capitale de la France ? | **out** | **0.7794** | sujet-B-29.pdf |
| Expliquer la photosynthèse | **out** | **0.8503** | EpreuvePratiqueBoids.ipynb |
| Quel est le théorème de Pythagore ? | **out** | **0.8205** | 5.Fonctions.ipynb |
| Comment faire une dissertation en philosophie ? | **out** | **0.8238** | tnsi_12_processus_cours.pdf |

**Analyse** : l'écart in-domain (0.87-0.89) vs hors-domaine (0.78-0.85) est **trop faible** pour un seuil discriminant fiable. Un seuil à 0.85 exclurait le théorème de Pythagore (0.82, hors-domaine) mais aussi certaines requêtes in-domain faibles. Un seuil à 0.80 ne filtrerait que la « capitale de la France » (0.78).

**Seuil candidat** : **0.82** — compromis conservateur. Exclurait les requêtes manifestement hors-domaine (< 0.80) sans couper le retrieval in-domain (> 0.85). Mais le vrai levier est le **hybride BM25/RRF + rerank CrossEncoder** (LOT 24), pas le seuil seul.

**État connu** : pas de seuil implémenté, pas de hybride, pas de rerank. Retrieval vectoriel pur. Renvoyé au LOT 24.

## W-04 — Caractère provisoire de l'ingestion

**Cette ingestion est provisoire.** Le chunker utilisé est un split par phrases/tokens avec comptage par tokenizer e5 réel (budget 480). Ce n'est **PAS** le chunker heading-aware cible (qui exploite la hiérarchie H1/H2/H3 des documents).

**Conséquences** :
- Les 22 518 chunks seront **ré-ingérés** au LOT 25 (unification chunker heading-aware + proxy remplacé par tokenizer réel globalement)
- `notions[]` est vide sur 100 % des chunks — pas de routage thématique possible
- La qualité de retrieval est limitée par l'absence de structure dans le découpage

**Ce passage prouve la chaîne de bout en bout** (parsing → chunking → embedding → index → retrieval citable). La qualité sera améliorée par le re-chunking heading-aware (LOT 25), l'ajout de `notions` (lot enrichissement), et le hybride/rerank (LOT 24).

## Mutations prod

Aucune. Tout tourne sur l'instance pgvector dédiée locale (port 5436).
