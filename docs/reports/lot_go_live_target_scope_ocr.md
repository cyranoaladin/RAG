# Rapport de lot — OCR ciblé sur les 22 PDF autorisés sans texte et fermeture du bloqueur de recherche

- **Lot** : `LOT_GO_LIVE_TARGET_SCOPE_SEARCHABLE_OCR`
- **Branche** : `go-live/target-scope-searchable-ocr`
- **Base** : `main` (`8364cfd43a5ee9e34ec6e19c0b05b45c229712a8`)
- **Date** : 2026-09-16
- **Décision humaine associée** : Décision de lancement du lot OCR ciblé validée
- **Verdict** : `GO_LIVE_OCR_TARGET_SCOPE_PR_OPEN`

---

## 1. Contexte et objectif

Après le merge de la PR #203 ayant adopté le budget de latence staging et fermé la condition `latency_validated`, le seul bloqueur technique résiduel sur la recherche RAG était la condition `target_scope_searchable` : 22 documents autorisés de `SERVABLE_CANDIDATE_SET` ne disposaient pas de couche textuelle extractible nativement par `pypdf`, limitant la couverture à 2 242 contenus sur 2 264.

L'objectif de ce lot est de réaliser l'extraction OCR ciblée strictement sur ces 22 documents, sous garde PII préalable impérative et sous budget de tokens canonique, afin de porter la couverture à 100% (2 264 / 2 264) et de fermer le bloqueur `RAG_SEARCHABILITY` (`rag_searchability_blocker = false`).

---

## 2. Périmètre et réalisations

### A. OCR ciblé et traçabilité de provenance
- Extraction ciblée strictement limitée aux 22 PDF sans texte extractible (aucune OCR globale du corpus).
- Utilisation du runtime OCR canonique gouverné (`nexus_pdf_ocr` avec `tesseract 5.3.4` en `fra+eng`, 300 DPI, et `pdftoppm 24.02.0`).
- Provenance exacte conservée page par page :
  - **79 pages** traitées par OCR (`PATH_OCR_FALLBACK`).
  - **244 pages** à texte natif conservées sans dégradation (`PATH_NATIVE_TEXT`).
  - **347 pages** de structure/séparateurs vides ignorées (`PATH_STRUCTURAL_EMPTY`).
  - Total : **323 pages** uniques couvertes sur les 22 documents.

### B. Contrôle PII préalable impératif (Point de vigilance)
- Détection PII exécutée sur l'intégralité du texte extrait (OCR et natif) avant tout découpage ou vectorisation, via le scanner officiel `rag_pedago.imports.pii_scanner` et la politique `services/rag-pedago/configs/pii_gate_policy.yml`.
- **Résultat** : **0 PII détectée** sur les 22 documents et 323 pages.
- Clearance formellement attestée dans `docs/reports/go_live/target_scope_ocr_execution.json`. Aucun arrêt bloquant PII requis.

### C. Découpage sous budget de tokens
- Découpage sous contrainte du modèle E5 canonique (`target_tokens = 384`, `max_sequence_length = 512`) avec conservation stricte des numéros de pages (`page_start`, `page_end`).
- **532 chunks** produits au total :
  - **185 chunks** marqués `OCR_DERIVED` (issus des pages océrisées).
  - **347 chunks** marqués `NATIVE_DERIVED` (issus des pages à texte natif).
  - **Max tokens observé** : **384 tokens** (0 chunk au-delà de la limite de 512).

### D. Clôture de l'audit vector store et de l'écart de recherche
- Mise à jour de l'audit vector store (`docs/reports/go_live/vector_store_audit.json` et `.md`) :
  - Passages totaux : 54 719 + 532 = **55 251 passages**.
  - Contenus vectorisés : 2 242 + 22 = **2 264 contenus** (100% de `SERVABLE_CANDIDATE_SET`).
  - Lignes hors liste blanche : 0, dimensions fausses : 0.
- Mise à jour du contrat de retrieval (`docs/reports/go_live/retrieval_contract_validation.json` et `.md`).
- Régénération de l'écart de recherche (`docs/reports/go_live/rag_searchability_gap.json` et `.md`) :
  - `target_scope_searchable` : **`true`**
  - `conditions_not_met` : **`[]`** (les 8 conditions de fermeture sont tenues)
  - `rag_searchable` : **`true`**
  - `rag_searchability_blocker` : **`false`**

### E. Régénération du readiness gate
- Régénération de `docs/reports/go_live/go_live_readiness_state.json` et `GO_LIVE_READINESS.md` :
  - `rag_searchability_blocker` est formellement retiré de `blocking_reasons`.
  - Les bloqueurs passent de 6 à 5 (`pre_release_blockers`, `go_live_qualification_blockers`, `pii_undecided`, `release_promoted_refused_contents`, `open_prs_blocking`).
  - `GO_LIVE_READY` reste strictement **`false`**.

---

## 3. Garde-fous et Invariants

- **Production** : aucune écriture, aucune base de production interrogée, aucun current switch.
- **Base de revue** : intacte, non lue et non écrite (`review_db_read: false`, `review_db_written: false`).
- **Décisions PII** : 149 décisions en suspens préservées à l'identique (aucune décision prise par effet de bord).
- **OAuth / Secrets** : aucun token, clé ni secret affiché ou consigné. Révocation Google OAuth différée.
- **Fail-closed** :
  - `check_go_live_readiness.py --assert-ready` rend toujours le code **1**.
  - `GO_LIVE_READY` reste `false`.
- **Suite de tests dédiée** : ajout de `scripts/tests/test_target_scope_ocr.py` (10 tests validant la délimitation stricte, l'absence de PII, le marquage `OCR_DERIVED`, et les invariants de gouvernance).
