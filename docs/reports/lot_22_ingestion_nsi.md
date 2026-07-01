# LOT 22 — Ingestion NSI gouvernée (T-22-1→T-22-5)

**Branche** : `lot-22-ingestion-nsi`
**Date** : 1er juillet 2026
**Statut** : T-22-3 en cours (embedding CPU). T-22-5 à exécuter après complétion.

---

## Investigation (T-22-0)

Rapport complet : `docs/reports/lot_22_investigation_ingestion_nsi.md` (v3.1, C1→C25).
Manifest ratifié : `docs/audits/manifest_nsi_dryrun.json.gz` (SHA-256 `d0e1217c...`).

## T-22-1 — Staging

Les 1 763 fichiers gardés sont lus directement depuis le corpus source (`~/Documents/NSI/scrapping_NSI/ressources_nsi_centralisees/`). Pas de copie physique en staging — le manifest fait office de staging logique. Le répertoire physique n'est pas committé.

## T-22-2 — Parsing + Chunking

- Extraction par format : pypdf (PDF), python-docx (DOCX), odfpy (ODT), json (IPYNB), brut (TEX)
- Chunking avec tokenizer e5 réel (`AutoTokenizer.from_pretrained('intfloat/multilingual-e5-large')`)
- Budget : 480 tokens e5 par chunk (max total avec préfixe : 484 ≤ 512, C24 prouvé)
- Dry-run : 1 762 docs parsés, **22 519 chunks**, 0 erreur

## T-22-3 — Embedding + INSERT

- Modèle : `intfloat/multilingual-e5-large` (1024 dim, CPU)
- Préfixe : `passage:` (`nexus_contracts.embedding_utils.format_passage`)
- Upsert : `ON CONFLICT (chunk_id) DO UPDATE ... WHERE chunk_sha256 <>`
- Résumable par `doc_id` (table `ingestion_progress`)
- Instance pgvector dédiée : `localhost:5436`, base `nexus_rag`
- **En cours** — progression : voir `SELECT count(*) FROM rag_chunks`

## T-22-4 — Quarantaine

Holding list : 70 fichiers (37 `.ipynb` JSON corrompus, 30 PDFs scannés, 3 `.docx` corrompus). Non embeddés, tracés dans le manifest. `rag_nexus_quarantine` reste vide (aucun contenu douteux lisible identifié — correct).

## T-22-5 — Validation retrieval

Script : `scripts/validate_nsi_lot22.py`. À exécuter après complétion de T-22-3.

Vérifiera :
- Volumétrie réelle (`SELECT count(*) FROM rag_chunks WHERE collection IN (...)`)
- F-01 citabilité : `rights`, `source_label`, `doc_id` non vides sur 100 % des chunks
- Quarantaine isolation : 0 chunk dans `rag_nexus_quarantine`
- Golden queries : 6 requêtes (3 Première, 3 Terminale), scoping `WHERE collection = ?`
- Chaque hit porte des métadonnées citables

## Dettes consignées

- R1 : dédup fallback base-name (faux positifs possibles)
- R2 : 30 PDFs scannés en holding (OCR hors-scope)
- R3 : chunker proxy non unifié (LOT 25)

## Script d'ingestion

`services/rag-engine/scripts/ingest_nsi_lot22.py` — résumable (`--resume`), idempotent (upsert).

## Commande de reprise (si session interrompue)

```bash
cd services/rag-engine
CUDA_VISIBLE_DEVICES="" PG_RAG_DSN="postgresql://nexus_rag:lot22dev@localhost:5436/nexus_rag" \
  python scripts/ingest_nsi_lot22.py --resume
```

## Commande de validation (après complétion)

```bash
CUDA_VISIBLE_DEVICES="" PG_RAG_DSN="postgresql://nexus_rag:lot22dev@localhost:5436/nexus_rag" \
  python scripts/validate_nsi_lot22.py
```
