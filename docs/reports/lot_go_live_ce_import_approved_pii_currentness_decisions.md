# Lot CE — Import des décisions PII et actualité approuvées

- Lot : `LOT_GO_LIVE_FINAL_CE_IMPORT_APPROVED_PII_CURRENTNESS_DECISIONS`
- Branche : `go-live/import-approved-pii-currentness-decisions`
- Décision : `GO_LIVE_CE_APPROVED_PII_IMPORT_PR_OPEN`
- Source : PR #219 (validée et approuvée par `abenrhouma`)
- Décisions scellées : `governance/pii-review-decisions/pii-review-2026-09-17-final.json` (`0805c9babfc16def873bbf0b3593ae6f7d0ce6fcb9002a68eb456d80b8906352`)
- Preuve formelle d'import : `docs/reports/evidence/pii_currentness_approved_import_proof.json` (`573ad6a453b6da83f7199d749940384b3bd06a7197cf38ffea2d596c4fd5326b`)

---

## 1. Contexte et mandat

La PR #219 a formellement validé la feuille de proposition de décisions PII et actualité (`pii_currentness_decision_proposal.tsv`) portant 152 décisions (149 contenus PII et 3 contenus déclarés archivés par Eduscol).

Le mandat du lot CE est d'importer strictement ces décisions dans la gouvernance scellée du dépôt, de mettre à jour la matrice de servabilité et le readiness, sans aucune modification arbitraire, sans dérogation métier et sans faux vert.

---

## 2. Arbitrage d'application stricte de l'ADR-0055 (Option 1)

L'arbitrage de gouvernance retenu et confirmé pour ce lot est l'**Option 1** :

- Application stricte de l'ADR-0055 et de la composition des gates (`servability_gate.composer`).
- **Aucune dérogation métier pour `157309db13b6`** (formulaire d'épreuve blanche EAF 2024, situé dans `90_ARCHIVE_CATALOGUE`).
- Bien que sa décision PII soit `APPROVED` (`PII_CLEARED`), ce document est déclaré archivé par la source (`ARCHIVE_DECLARED`). Le gate d'actualité (`CURRENTNESS_GATE`) le bloque donc strictement avec le verdict `BLOCKED_NOT_CURRENT_BY_SOURCE`.
- Aucun override d'actualité n'a été appliqué pour forcer artificiellement le passage de 26 à 3 refus promus.
- Le nombre de contenus promus refusés passe ainsi de **26 à 4** (et non à 3).

### Les 4 archives maintenues bloquées dans la release promue :

1. `157309db13b674ffe4bf1371015bfc7c9c9cf475af75769a6beaf4dade45925f` — archive Eduscol 2024 / EAF
2. `174f273ff25818064be60cd4c7cded89ab8f257de484b32a21250578f323149b` — archive Eduscol DGEMC
3. `ccffe628bbd64e34a8442a045f95ec2ef65109765c0a0a476c0156aa84a5f9a2` — archive Eduscol SVT voie technologique
4. `dc58fcc42ef9b4e6d15a129124eff54ce5d76e0e16e1e4f62115b64482e94fd2` — archive Eduscol SVT voie générale

Ces 4 contenus restent bloqués par `CURRENTNESS_GATE` (`BLOCKED_NOT_CURRENT_BY_SOURCE`) et seront exclus lors du rescellement de release prévu aux lots CF/CG.

---

## 3. Réalisations techniques

### 3.1 Index de revue complet compatible et scellement gouverné
- Création du générateur `scripts/go_live/build_complete_pii_review_index.py` produisant `docs/reports/evidence/pii_review_complete_compatible_index.json` (496 Ko, 149 paquets, 479 signalements).
- Adjonction stricte du champ `page = page_number` sur chaque signalement sans modifier les instruments, scanners ou empreintes.
- Mise à jour de `scripts/go_live/convert_review_sheet_to_sealer_draft.py` pour accepter un index configurable et supporter l'ensemble complet.
- Conversion vers `/tmp/nexus-pii-sealer-draft-ce` avec permissions restrictives (`0700` / `0600`), exécution de `services/rag-pedago/scripts/sceller_decisions_pii.py sceller` vers `governance/pii-review-decisions/pii-review-2026-09-17-final.json`, puis nettoyage immédiat du draft temporaire hors dépôt.
- Validation formelle par `nexus_contracts.parse_pii_review_decision_set` : 149 décisions, 23 approuvées, 126 exclusions conservatoires.

### 3.2 Câblage explicite et traçable dans la matrice de servabilité
- Modification de `services/rag-pedago/scripts/construire_matrice_servabilite.py` :
  - Import et parsing du jeu scellé via `parse_pii_review_decision_set`.
  - Intégration traçable dans les `inputs` de la matrice :
    - `path`: `governance/pii-review-decisions/pii-review-2026-09-17-final.json`
    - `sha256`: `0805c9babfc16def873bbf0b3593ae6f7d0ce6fcb9002a68eb456d80b8906352`
    - `decision_set_id`: `pii-review-2026-09-17-final`
    - `decisions_count`: 149
    - `reviewer_login`: `abenrhouma`
    - `decided_at`: `2026-09-17T19:30:48+00:00`
    - `source_pr`: 219
  - Affectation des statuts PII : `APPROVED` → `PII_CLEARED`, `REJECTED` → `REJECTED`.
  - Transmission au gate de servabilité (`pii_gate="REJECTED"`).
- Régénération de `docs/reports/handoff/servability_matrix_v1.json` (`9a695b68d6518cc416f475cae712f2ab91f8274dad8b554d3088f4c7107f3a98`) :
  - `SERVABILITY_ROWS_TOTAL`: 2530
  - `CANDIDATE_NO_BLOCKING_DIMENSION`: 2286
  - `BLOCKED_PII_HUMAN_REVIEW`: 126
  - `BLOCKED_NO_URL_PROVENANCE`: 59
  - `BLOCKED_NOT_CURRENT_BY_SOURCE`: 38
  - `NOT_INDEXABLE_BY_ROLE`: 20
  - `REFUSED_PROGRAM_INCOMPATIBLE`: 1

### 3.3 Mise à jour du readiness et levée de bloqueurs
- Exécution de `scripts/go_live/check_go_live_readiness.py` :
  - Régénération de `docs/reports/go_live/go_live_readiness_state.json`.
  - Régénération de `docs/reports/go_live/GO_LIVE_READINESS.md`.
  - Régénération de `docs/reports/go_live/blocker_closure_ledger.json`.
  - Régénération de `docs/reports/go_live/BLOCKER_CLOSURE_LEDGER.md`.
- Levée effective du bloqueur pré-release `PII_UNDECIDED` (`current_value: 0`, `blocking: false`).
- `pre_release_blockers` passe de 1 à 0.

---

## 4. Métriques de readiness constatées

| Métrique | Avant CE | Après CE | Statut |
|---|---|---|---|
| `pii_undecided` | 149 | **0** | Fermé |
| `pre_release_blockers` | 1 | **0** | Fermé |
| `release_promoted_refused_contents` | 26 | **4** | 4 archives (`BLOCKED_NOT_CURRENT_BY_SOURCE`) |
| `go_live_qualification_blockers` | 4 | **4** | Restent ouverts (C1, STAGING_EXTERNE, CONCURRENCE, MANIFESTE_PRODUCTION) |
| `go_live_ready` | false | **false** | Strictement faux |
| `--assert-ready` | exit 1 | **exit 1** | Échec fail-closed garanti |
| `current_switch` | 0 | **0** | Aucune bascule |
| `production_db_writes` | 0 | **0** | Aucune écriture |
| `production_deployments` | 0 | **0** | Aucun déploiement |

---

## 5. Garanties et épreuves de test

1. **Nouveau test de qualification dédié** : `scripts/qualification/tests/test_pii_currentness_import_ce.py` (7 tests passants) :
   - Vérification des 149 décisions scellées, conformité d'empreinte et de reviewer.
   - Validation stricte des compteurs de readiness post-CE.
   - Vérification nominative des 4 archives bloquées.
   - Audit de transition de `157309db13b6` (Option 1).
   - Traçabilité et câblage de provenance dans les inputs de la matrice.
   - Invariants de sécurité et de production (zéro écriture, switch=0, zéro matière brute).
   - Validation que `--assert-ready` renvoie 1.
2. **Suite de qualification complète** (`scripts/qualification/tests`) : **136 passants, 2 ignorés, 0 échec**.
3. **Suite de scripts et garde-fous** (`scripts/tests`) : **538 passants, 7 ignorés, 0 échec**.
4. **Qualité rag-pedago** : `make lint` et `make typecheck` à 100% sans erreur.
