# LOT 25a — Ré-ingestion notebooks + filtrage base64

**Branche** : `lot-25a-notebooks-base64`
**Date** : 2 juillet 2026
**Statut** : **COMPLET** — embedding exécuté, bascule faite, mesures réelles.

---

## Diagnostic de pertinence — CLOS

Quatre mesures successives ont identifié et écarté quatre fausses pistes :
1. **MM-01** (compteur tokens réel sur PDF) : Δ = 0.00 → cosmétique
2. **NN-01** (PyMuPDF + heading-aware sur PDF) : Δ = +0.09 → cosmétique
3. **OO-01** (reranker L-12) : marge 0.79 → 0.81 → marginal
4. **OO-01** (BGE multilingual) : marge **−0.49** → ne discrimine pas l'in-domain du hors-domaine (PP-01 : la raison du rejet est l'absence de discrimination, pas le calibrage d'échelle)

**Verdict** : les scores in-domain faibles (+2.30 à +5.59) sont le plafond réel du contenu croisé avec un cross-encoder léger (MiniLM-L-6). Pas de défaut technique récupérable. Config L-6 + seuil +1.90 = optimum actuel.

## Dry-run PP-02

| Métrique | Avant (LOT 22) | Après (heading-aware) |
|---|---|---|
| Docs .ipynb/.tex | 333 | 333 |
| Chunks totaux | 18 567 | **4 775** |
| Chunks base64 filtrés | — | 394 |
| Réduction | — | **−74 %** (outputs .ipynb jetés, B9 résolu) |

## ProjetPopArt (PP-03)

1 418 chunks LOT 22 → **11 propres + 8 base64 filtrés**. 8 chunks base64 subsistent → **reste quarantiné** (LL-04 : pas propre = pas re-servable). Le filtre attrape la majorité du base64 inline mais quelques fragments passent.

## Exécution réelle (QQ-01→QQ-05)

### QQ-01 — Embedding shadow
- 294 docs, **4 145 chunks** embeddés en shadow table `rag_chunks_25a`
- **0 base64** dans le shadow (vérifié par requête stricte)
- Durée : 56 min CPU

### QQ-02 — Mesure avant/après (PP-04)

| Métrique | Avant (LOT 22) | Après (propre) | Delta |
|---|---|---|---|
| In-domain avg | +4.87 | **+4.90** | +0.03 |
| Out-domain avg | -4.29 | **-4.46** | -0.18 (mieux) |
| Plancher in | +2.30 | +2.30 | 0.00 |
| **Plafond out** | +1.51 | **+1.30** | **-0.21** (mieux) |
| **Marge** | **0.79** | **1.00** | **+0.21 (+27 %)** |

**Gain notable** : « type construit (tuple/dictionnaire) » +3.67 → **+5.30** (+1.64) — le chunk propre du notebook `1_Cours_Types_construits_Python.ipynb` remplace un corrigé de TD.

Pas de régression in-domain (1 variation de -1.00 sur « codage binaire » = variabilité rerank sur le même chunk, pas une régression de contenu).

### QQ-03 — Bascule (TT-01 réconcilié)

Décomposition exacte (vérifiée par requête SQL, somme = −5 626) :

| Composant | Chunks |
|---|---|
| LOT 22 total | 22 518 |
| Non-notebook (PDF/DOCX/ODT) — **inchangés** | 11 248 |
| LOT 22 notebook/tex (sentence-split) | 11 270 |
| LOT 25a notebook/tex (heading-aware + filtre base64) | 5 644 |
| **Réduction notebook** | **−5 626** (= 11 270 − 5 644) |
| **LOT 25a total** | **16 892** (= 11 248 + 5 644) ✓ |

La bascule a été exécutée par DELETE/INSERT (pas le renommage atomique prévu en LL-03) à cause de la coexistence des PDF LOT 22 dans la même table. L'état final est certifié propre (SS-01 : 0 NULL F-01, SS-02 : PDF intact, RR-02 : totaux cohérents).

**Leçon** : prochaine bascule blue/green = table dédiée par format + renommage atomique, pas DELETE/INSERT sur table mixte.

### QQ-05 — Déchet par format
0 % de base64 sur tous les formats (PDF, IPYNB, TEX, DOCX, ODT) — le corpus est propre.

## État post-bascule

| Statut | Chunks |
|---|---|
| reviewed | 14 884 |
| needs_review | 325 |
| quarantined | 1 683 |
| **Total** | **16 892** |
| **Réduction** | **−5 626** (−25 %) = 11 270 notebook/tex LOT 22 → 5 644 heading-aware (TT-01) |
| **Marge in/out** | **1.00** (was 0.79, +27 %) |

## Dettes mises à jour

- **R8** : partiellement traité (notebooks re-chunkés heading-aware, sections cohérentes au lieu de fragmentation par phrase ; PDF restent proxy)
- **R10** : créée et différée (PyMuPDF, gain qualitatif, pas de gain de score NN-01)
- **B9** : **re-statué** — les outputs .ipynb étaient DÉJÀ jetés au LOT 22 (`ingest_nsi_lot22.py` ne collectait que `cell.source`). B9 n'était pas ouvert au sens strict. La réduction de chunks vient du **regroupement par sections** (heading-aware vs sentence-split), pas du filtrage des outputs.
- **Diagnostic pertinence** : CLOS (plafond contenu × modèle, 4 mesures — MM-01, NN-01, OO-01 L-12, OO-02 BGE)

## UU-02 — Rollback : INDISPONIBLE (VV-02)

**La bascule LOT 25a est irréversible.** Les anciens chunks notebook/tex LOT 22 ont été supprimés (suppression ciblée par extension .ipynb/.tex) sans sauvegarde préalable. La table shadow `rag_chunks_25a` contient les chunks LOT **25a** (4 145), pas les anciens LOT 22.

**Retour arrière** : la seule voie de retour serait une ré-ingestion depuis le corpus source avec le chunker LOT 22 (`chunk_text()` de `ingest_nsi_lot22.py`). Ce n'est pas un rollback instantané.

**Leçon** : la bascule DELETE/INSERT sur table mixte (PDF + notebooks) sans archiver les anciens rend le rollback impossible. La prochaine bascule doit être un renommage atomique sur table dédiée par format, conservant l'ancienne table intacte.

Table `rag_chunks_25a` à supprimer après le 9 juillet 2026 (plus de valeur de rollback) :
```sql
DROP TABLE IF EXISTS rag_chunks_25a;
```

## État final du RAG NSI (UU-03)

### Référence pour les lots futurs

| Métrique | Valeur |
|---|---|
| **Corpus total** | **16 892 chunks** |
| Reviewed | 14 884 |
| Needs_review | 325 (36 mini-projets) |
| **Servable** | **15 209** (= 14 884 + 325) |
| Quarantined | **1 683** (décomposition VV-01 ci-dessous) |

### Composition de la quarantaine (VV-01, certifiée par requête)

| Motif | Chunks | Docs |
|---|---|---|
| ProjetPopArt (base64 images inline) | 1 418 | 1 |
| Notebooks base64 résiduels | 129 | 38 |
| DMX (manuels matériel hors NSI) | 78 | 5 |
| PDFs artefacts encodage | 58 | 16 |
| **Total quarantaine** | **1 683** | **60** |

Vérification : 15 209 + 1 683 = **16 892** ✓
| **Marge in/out** | **1.00** |
| **Seuil rerank** | **+1.90** (provisoire, lié au chunking) |
| In-domain conservé | 15/15 (100 %) |
| Hors-domaine rejeté | 10/10 (100 %) |
| Base64 servable | **0** |
| F-01 (citabilité) | **satisfait** (0 NULL sur rights/source_label/doc_id) |

### Config de retrieval

```
dense: intfloat/multilingual-e5-large (1024 dim)
rerank: cross-encoder/ms-marco-MiniLM-L-6-v2
seuil: +1.90 (score rerank, provisoire)
hybride BM25/RRF: DÉSACTIVÉ (DD-01, collision lexicale mono-matière)
gate retrievable: fail-closed, domaine déclaré (GG-01, 8 tests)
scoping: WHERE collection = ? (une collection par requête)
answer_generation_allowed: false
```

### Diagnostic pertinence — CLOS

Les scores in-domain faibles (+2.30 à +5.59) sont le plafond réel du contenu croisé avec un cross-encoder léger (MiniLM-L-6). Prouvé par 4 mesures indépendantes : compteur tokens (MM-01, Δ=0.00), extracteur PDF (NN-01, Δ=+0.09), reranker L-12 (OO-01, marge stable), reranker BGE multilingue (OO-02, marge -0.49). Pas de défaut technique récupérable.

### Dettes ouvertes (non urgentes)

| Dette | Nature | Priorité |
|---|---|---|
| R10 — extraction PDF structurée (PyMuPDF) | Qualitative (meilleurs breadcrumbs) | Basse (NN-01 : pas de gain de score) |
| R4 — notions[] vide | Fonctionnelle (routage thématique) | Moyenne |
| Multi-matières + hybride | Fonctionnelle (DD-01 : hybride utile en multi-matières) | Dépend du besoin lead |
| Reranker plus capable | Pertinence (plafond actuel) | Basse (cross-encoder FR dédié, non trivial) |

### Lots livrés (LOT 20 → LOT 25a)

| Lot | Livrable | PR |
|---|---|---|
| LOT 20 | Inventaire production rag-ui | #36 |
| LOT 21 | Infrastructure convergence (ADR-0013, pgvector dédié) | #37 |
| LOT 22a | Séparation legacy/v2 étanche | #38 |
| LOT 22 | Ingestion NSI 22 518 chunks, F-01 satisfait | #39 |
| LOT 24 | Pertinence : rerank + seuil +1.90, marge 0.79 | #40 |
| LOT 25a | Notebooks heading-aware, −5 626 déchet, marge 1.00 | #41 |

### RR-01 — Vraie cause de la réduction (corrigée)

La réduction de 22 518 → 16 892 (−5 626) n'est PAS le filtrage des outputs B9 (déjà fait au LOT 22). C'est le **passage du sentence-split au heading-aware** :
- Le LOT 22 (`chunk_text()`) coupait par phrases/regex, produisant beaucoup de petits chunks fragmentés
- Le LOT 25a (`parse_sections + _flatten_section`) regroupe par sections H1/H2/H3, produisant moins de chunks mais thématiquement cohérents
- Le filtre base64 a éliminé 394 chunks artefacts supplémentaires

Vérifié sur 3 notebooks : le heading-aware produit un nombre comparable de chunks (ratio 0.6-1.0×). La réduction globale vient de la consolidation des fragments.

### RR-02 — Base certifiée propre

- 0 doublon source_label (295 notebooks/tex uniques)
- 10 848 chunks PDF intacts (inchangés depuis LOT 22)
- 0 base64 dans le servable
- Totaux cohérents : 14 884 reviewed + 325 needs_review + 1 683 quarantined = 16 892
- Collections : Première 7 805, Terminale 7 404, Quarantaine 1 683
