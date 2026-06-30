# Rapport de lot 20 — Reconnaissance de la production rag-ui (clôture finale)

**Branche** : `lot-20-prod-preflight-rag-ui`
**Date** : 30 juin 2026
**Cible** : `rag-ui.nexusreussite.academy` (`88.99.254.59`)
**Règles** : R-01, R-02, R-03.

---

## Livrables

| Livrable | Fichier |
|---|---|
| Inventaire de production | `docs/audits/PROD_INVENTORY_rag-ui.md` |
| Projet d'ADR de convergence | `docs/audits/ADR_CONVERGENCE_DRAFT.md` (v5) |
| Rapport d'incident sécurité | `docs/reports/lot_20_securite_incident.md` |
| Baseline retrieval prod | `docs/audits/baseline_retrieval_prod.json` (v2) |
| Rapport de lot | ce fichier |

---

## Mutations prod réalisées

| Mutation | Date/heure | Autorisation | Impact | Rollback |
|---|---|---|---|---|
| Rotation du token API | 2026-06-30 ~17:22 UTC | A-8 | Ancien token invalidé. Brève coupure (~30s). | `.env` pré-rotation conservé (chmod 600) |
| Recréation ingestor+ui | 2026-06-30 ~17:22 UTC | Conséquence rotation | Brève coupure (~30s). | `docker compose up -d` avec ancien `.env` |
| Création involontaire de `rag_web3` et `rag_divers` (vides) | 2026-06-30 ~17:45 UTC | Non intentionnelle (M-01, test L-02) | Collections vides | **Supprimées** (A-CLEANUP-COLLECTIONS) |
| Suppression de `rag_web3` et `rag_divers` | 2026-06-30 ~18:15 UTC | A-CLEANUP-COLLECTIONS | 8 → 6 collections. `rag_maths_premiere` conservée (régénérée par fallback nominal). | Pas de rollback nécessaire (collections vides) |

---

## Résumé de la reconnaissance

| Fait | Valeur |
|---|---|
| Collections prod | 5 à l'arrivée → 8 après auto-créations → **6 après cleanup** (4 peuplées, 2 vides : `rag_maths_premiere` par fallback nominal + `ressources_pedagogiques_terminale` résiduelle) |
| Vecteurs totaux | 17 912, tous 768 dim mesurées |
| Modèle embedding | nomic-embed-text (Ollama) |
| Admissibles (matiere ∧ niveau ∧ URL) | **9 199** (51 %) |
| `rights` | **0 %** sur tout le corpus |
| `nsi_corpus` non revu | 100 % (4 437 `needs_review` + 279 sans statut) |
| Code prod ≠ dépôt | Confirmé (91 501 vs 90 357 octets) |
| UI servie | `app_v2.py` (`app.py` morte) |
| Rubriques UI | 6 (3 OK : Français 1re, Éducation, Toutes ; **3 cassées** : Maths 1ère, Web3, Divers) |
| Rubriques cassées | **Documentées, non masquées** (A-L03-REQUALIFIE). Différées au remplacement UI. |
| `section=nsi` dans l'UI | Non exposé |
| UI après rotation token | Fonctionnelle (J-01 prouvé end-to-end) |

---

## Punch-lists closes

### Punch-list J (clôturée)

J-01 (UI fonctionnelle), J-02 (baseline 4 sections), J-03 (texte non droité purgé), J-04 (dérive = spec de remplacement), J-05 (nsi non exposé), J-06 (francais_premiere étiquetage suspect), J-07 (cleanup rollback) — tous validés.

### Punch-list K (clôturée)

K-01 (Maths 1ère cassée, confirmé), K-02 (`app_v2.py` servie), K-03 (format baseline cutover posé), K-04 (spec régression couvre `app_v2.py`), K-05 (section mutations prod) — tous validés.

### Punch-list L (clôturée)

| Item | Statut |
|---|---|
| L-01 | Fallback maths non-fonctionnel par construction, consigné (inventaire §13, ADR §10) |
| L-02 | 6 rubriques testées : 3 OK, 3 cassées (Web3/Divers = collections auto-créées vides) |
| L-03 | **Requalifié** (A-L03-REQUALIFIE) : documenté, non exécuté. Pas de mutation prod. |
| L-04 | `ressources_pedagogiques_terminale` → suppression au décommissionnement (inventaire §4.2) |

### Punch-list M (consignée)

| Item | Statut |
|---|---|
| M-01 | Dette consignée : `get_or_create_collection` crée des collections vides (inventaire §16). Invariant cible : pas d'auto-création. |
| M-02 | Arborescence de collections cible dérivée de la taxonomie (ADR §11). Convention `rag_nexus_{matiere}_{niveau}_{statut}`. |
| M-03 | Question de cadrage interface RAG posée (ADR §13). Cockpit vs Streamlit vs hybride — à trancher au LOT 21. |
| M-04 | Invariant consigné (ADR §12) : n'exposer que ce qui est peuplé et gouverné. |

---

## Décisions de lead intégrées

A-1 à A-8 (modèle/store/migration/génération/rights/quarantaine/nsi/francais/rotation), A-L03-REQUALIFIE (pas de masquage), A-COMMIT (go conditionnel). Toutes actées dans l'ADR §1.

---

## Point d'étape

**LOT 20 prêt pour commit/PR.** M-01 consigné, L-03 requalifié (documenté, non exécuté), M-02→M-04 intégrés dans l'ADR. Aucune mutation prod restante. En attente du « go » du lead pour committer.
