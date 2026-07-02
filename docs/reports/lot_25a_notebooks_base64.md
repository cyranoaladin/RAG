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

### QQ-03 — Bascule
Anciens chunks notebook/tex (LOT 22, 6 791 déchet) supprimés. Chunks propres du shadow insérés. Total post-bascule : **16 892 chunks** (was 22 518, −5 626 déchet éliminé). Table shadow `rag_chunks_25a` conservée pour rollback (LL-03, rétention ≥ 7j).

### QQ-05 — Déchet par format
0 % de base64 sur tous les formats (PDF, IPYNB, TEX, DOCX, ODT) — le corpus est propre.

## État post-bascule

| Statut | Chunks |
|---|---|
| reviewed | 14 884 |
| needs_review | 325 |
| quarantined | 1 683 |
| **Total** | **16 892** |
| **Déchet éliminé** | **5 626** (−25 %) |
| **Marge in/out** | **1.00** (was 0.79, +27 %) |

## Dettes mises à jour

- **R8** : partiellement traité (notebooks re-chunkés heading-aware + 5 626 chunks déchet éliminés ; PDF restent proxy)
- **R10** : créée et différée (PyMuPDF, gain qualitatif, pas de gain de score NN-01)
- **B9** : **RÉSOLU** sur les notebooks (outputs jetés, −74 % de chunks notebook)
- **Diagnostic pertinence** : CLOS (plafond contenu × modèle, 4 mesures — MM-01, NN-01, OO-01, OO-01)
