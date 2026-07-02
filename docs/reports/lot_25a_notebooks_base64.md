# LOT 25a — Ré-ingestion notebooks + filtrage base64

**Branche** : `lot-25a-notebooks-base64`
**Date** : 2 juillet 2026
**Statut** : dry-run exécuté, embedding en attente de session CPU.

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

## Plan d'exécution (en attente de session CPU)

1. Créer table shadow `rag_chunks_25a` (même schéma)
2. Embedder les 4 775 chunks propres (e5-large CPU, ~1-2h)
3. Insérer dans la table shadow
4. Mesurer PP-04 (questions à réponse-notebook)
5. Si OK : bascule par renommage (LL-03, rétention 7j)

## Commande de reprise

```bash
cd services/rag-engine
CUDA_VISIBLE_DEVICES="" PG_RAG_DSN="postgresql://nexus_rag:<password>@localhost:5436/nexus_rag" \
  python scripts/ingest_lot25a.py
```

## Dettes mises à jour

- **R8** : partiellement traité (notebooks re-chunkés heading-aware, PDF restent proxy)
- **R10** : créée et différée (PyMuPDF, gain qualitatif, pas de gain de score NN-01)
- **B9** : RÉSOLU sur les notebooks (outputs jetés, −74 % de chunks)
- **Diagnostic pertinence** : CLOS (plafond contenu × modèle, 4 mesures)
