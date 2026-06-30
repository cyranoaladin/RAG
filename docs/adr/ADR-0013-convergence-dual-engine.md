# ADR-0013 — Convergence dual-engine

**Statut** : accepté
**Date** : 30 juin 2026
**Constats traités** : F-02, A-01, F-14, F-38
**Historique** : `docs/audits/ADR_CONVERGENCE_DRAFT.md` (brouillon v5, LOT 20)

---

## Contexte

Deux chaînes RAG incompatibles coexistent : un moteur historique (nomic-embed-text 768 dim, ChromaDB, Ollama) et un pilote gouverné (e5-large 1024 dim, pgvector, sentence-transformers). Les dimensions sont physiquement incompatibles. Le script `migrate_chroma_to_pgvector.py` est inopérant (préserve les vecteurs sans recalcul). Le code prod diverge du dépôt (91 501 o vs 90 357 o, `COLLECTION_MAP` et fallback différents).

## Décisions

### Modèle et store (A-1)

**intfloat/multilingual-e5-large (1024 dim) + pgvector dédié**, instance séparée de `nexus_prod`. Pas de colocalisation de l'index RAG dans la base applicative à PII.

### Stratégie de migration (A-2)

Shadow puis canary (D-4), rollback nginx en une ligne.

### Génération (A-3)

G-3 transitoire (UI legacy conserve la génération) → G-1 cible (génération gouvernée sous citation obligatoire). Lever de `answer_generation_allowed` par un ADR distinct, postérieur à la résolution de F-01. Cet ADR ne lève aucun verrou.

### Droits (A-4, A-5)

`rights` résolu **par provenance uniquement**, jamais par classification de texte. Contenu Nexus-owned → droits connus ; contenu tiers → droits à établir explicitement ou quarantaine (`rag_nexus_quarantine`).

### `nsi_corpus` (A-6)

Re-ingestion par la chaîne gouvernée depuis les sources `rag-pedago`, après vérification d'existence/correspondance.

### `rag_francais_premiere` (A-7, amendé)

Correction des métadonnées (niveau faux) puis indexation dans la collection fine correspondante. Granularité matière×niveau×statut, pas de fusion dans un silo `rag_nexus_education`.

### Interface (D-M03)

Cible unique = cockpit Next.js, **différé après le LOT 25**. Aucun développement UI dans les lots intermédiaires. Streamlit legacy gelé en l'état (admin/ingestion uniquement). Rejet de l'hybride (coût double, problème prématuré).

### Périmètre d'instanciation initial (D-PERIMETRE)

1. `rag_nexus_nsi_terminale_specialite` — première collection prouvée de bout en bout
2. `rag_nexus_nsi_premiere_specialite` — instanciée juste après
3. `rag_nexus_quarantine` — instanciée d'emblée
4. Français : différé (J-06 non résolu, source unique, droits non établis)
5. Toutes les autres : non instanciées (M-04), restent au catalogue

### Dérive prod ↔ dépôt

Le moteur gouverné **remplace** la prod — la dérive n'est pas reportée. Les comportements prod spécifiques (`score_threshold`, `maths_premiere_fallback`, routing par `section`) sont captés comme spécification de régression et évalués individuellement.

## Arborescence de collections cible

Convention : `rag_nexus_{matiere}_{niveau}_{statut}`. 22 entrées au catalogue taxonomique. Chaque collection porte un flag `instanciee` ; seules les instanciées sont exposées à l'UI (invariant M-04 : peuplé et gouverné uniquement).

Exceptions nommées : `rag_nexus_grand_oral_terminale`, `rag_nexus_exams_bac_general`, `rag_nexus_exams_anticipee_maths`, `rag_nexus_candidats_libres_terminale`, `rag_nexus_quarantine` — cf. `rag_collections.yml` pour le détail.

## Invariants

1. **Pas d'auto-création de collection** — le moteur lève une erreur si la collection n'est pas déclarée instanciée. Pas de `get_or_create_collection`.
2. **Pas de rubrique UI pointant une collection vide** (M-04).
3. **Réentrée par la gouvernance** (C-03) — tout chunk passe par `quality → gate → review` avant indexation.
4. **Re-chunking exige les documents GDrive originaux** (I-03) — mode dégradé documenté si indisponible.

## Table de régression au cutover

Cf. `PROD_INVENTORY_rag-ui.md` §13. Fonctionnalités à traiter : `score_threshold`, `maths_premiere_fallback` (non-fonctionnel par construction L-01), `/rag/query`, filtres `groupe`/`type_ressource`, routing par `section`, auth Bearer → HMAC, rubriques UI.

## Backlog

- Compléter la taxonomie : options hors maths, maths complémentaires/expertes, enseignement scientifique, EMC (O-03)
- Résoudre J-06 (niveau réel `rag_francais_premiere`) avant toute instanciation française
- Benchmark débit e5-large CPU (I-04, LOT 25)

## Conséquences

- Le LOT 21 pose l'infrastructure (pgvector dédié, `rag_collections.yml`, table `rag_chunks`, invariant anti-auto-création).
- Le LOT 22+ exécute la chaîne citations → évaluation → hybride → chunker sur NSI Terminale.
- Le cockpit Next.js est développé après le LOT 25.
