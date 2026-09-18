# Lot CG — Rescellement de Release V2 et Clôture du Bloqueur C1

- **Lot** : `LOT_GO_LIVE_FINAL_CG_RESEAL_AND_C1_CLOSURE`
- **Branche** : `go-live/reseal-and-c1-closure`
- **Base** : `470c4b991a4234428d3f1960881d45e9bebf3dfa` (merge commit PR #223)
- **Release candidate V2 scellée** : `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/release-1b9eba0c0eb0ab13`
  - Digest manifest V2 : `e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864`
  - Mode filesystem : `0o444` (lecture seule stricte)
- **Registre scellé d'exclusion** : `docs/reports/evidence/release_currentness_exclusion_registry.json` (`07a346b84ae4ebbf1ef7f14dd3f588c95acce36050e8c335f904c37cabe4c72c`)
- **Preuve hermétique de clôture C1** : `docs/reports/evidence/release_v2_reseal_c1_closure_proof.json` (`002884a948552083f1823ad84ef49b428f37a79d84d7fd83cc28bd27321de159`)
- **Suite de qualification CG** : `scripts/qualification/tests/test_release_v2_reseal_c1_closure.py` (9 tests passés)

---

## 1. Contexte et Mandat

À l'issue du Lot CF (PR #223), l'outillage d'exclusion d'actualité et le mode dry-run ont validé la capacité de rescellement en mémoire avec 315 artefacts uniques.

Le mandat du **Lot CG** consiste à :
1. Réaliser le **rescellement réel, gouverné et vérifiable** de la release candidate V2 (`production-profile-gate-2026-2027-v2`) en excluant exactement les 4 archives déclarées par Eduscol conformément à l'ADR-0055.
2. **Préserver strictement la release historique V1** (`production-profile-gate-2026-2027-v1`) conformément à l'ADR-0050 (non-réécriture, copie de référence scellée dans `release-registry-v1.json`).
3. Mettre à jour `release-registry.json` pour pointer officiellement vers V2 tout en conservant V1 dans l'historique de publication.
4. Mettre à jour de façon minimale et fail-closed le contrat partagé `nexus_release_chain.release_readiness` pour autoriser `currentness_exclusion_registry_sha256` uniquement sur les releases V2 (Solution 1 validée).
5. Constater la disparition des contenus refusés dans la nouvelle release promue :
   - `release_promoted_refused_contents` : **4 → 0**
6. **Fermer strictement le bloqueur C1** avec preuve cryptographique scellée, et laisser strictement ouverts les 3 bloqueurs restants :
   - `go_live_qualification_blockers` : **4 → 3**
   - Bloqueurs ouverts : `STAGING_EXTERNE`, `CONCURRENCE`, `MANIFESTE_PRODUCTION`.
7. Garantir les invariants stricts :
   - `GO_LIVE_READY=false`, `--assert-ready=1`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.

---

## 2. Décisions et Solutions Appliquées

### 2.1 Mise à jour minimale du contrat partagé `nexus_release_chain` (Solution 1)

Lors de la confrontation de la release V2 au validateur d'autorités, le garde-fou de réconciliation a rejeté la release candidate en raison de la présence du champ `currentness_exclusion_registry_sha256` non répertorié dans les autorités historiques.

Conformément à la décision d'arbitrage (Solution 1) :
- Ajout de `_CURRENTNESS_EXCLUSION_AUTHORITY_FIELDS = frozenset({"currentness_exclusion_registry_sha256"})`.
- Dans `_require_authority_chain`, ce champ est autorisé **uniquement si `review_chain_allowed=True`** (spécifique aux releases V2), validé par `_require_sha256`.
- Rejet strict pour les releases Wave 0 et V1 (`review_chain_allowed=False`).
- Rejet strict et fail-closed de tout champ inconnu.
- Paquet réinstallé en mode éditable dans l'ensemble des environnements virtuels (`rag-engine`, `rag-pedago`).

### 2.2 Rescellement réel de la Release Candidate V2

Exécution du constructeur de release :
```bash
./services/rag-pedago/.venv/bin/python3 services/rag-pedago/scripts/build_production_profile_release.py \
  --release-mode rehearsal \
  --source-release-root services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate \
  --release-id production-profile-gate-2026-2027-v2 \
  --exclusion-registry docs/reports/evidence/release_currentness_exclusion_registry.json \
  --exclusion-registry-sha256 07a346b84ae4ebbf1ef7f14dd3f588c95acce36050e8c335f904c37cabe4c72c
```

Résultats constatés :
- Répertoire scellé : `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/release-1b9eba0c0eb0ab13/`
- Permissions fixées en lecture seule (`0o444`) sur tous les fichiers générés.
- Empreinte SHA-256 du manifest agrégé V2 : `e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864`.
- Cardinalités exactes :
  - **315 artefacts uniques** (319 - 4)
  - **479 placements** (486 - 7)
  - **8268 chunks uniques** (8324 - 56)
  - **11 matières** (0 matière vide)

### 2.3 Préservation de V1 et alignement du registre de release

- Préservation de la release V1 historique dans `services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v1.json` (`c9a844d4d2cc15caf9694b24ac53e77d65d50608d8a0daaef4963183d7d374fa`).
- Mise à jour de `services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json` :
  - Pointe activement vers V2 (`profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json`).
  - Conserve V1 dans `historical_releases`.
  - Digest SHA-256 : `82051777ba0bea6a316fa65ea7aca468f0d6187891d0c8ccb69c0156801ea5db`.

### 2.4 Clôture stricte de C1 et attestation hermétique

- Création de la preuve scellée :
  - `docs/reports/evidence/release_v2_reseal_c1_closure_proof.json`
  - `docs/reports/evidence/release_v2_reseal_c1_closure_proof.sha256` (`002884a948552083f1823ad84ef49b428f37a79d84d7fd83cc28bd27321de159`)
  - Kind : `NEXUS-RELEASE-V2-RESEAL-C1-CLOSURE-PROOF-V1`, statut `VERIFIED`.
- Implémentation du vérificateur `verifier_c1` dans `scripts/go_live/build_qualification_blockers.py` :
  - Revalidation cryptographique du SHA-256 de la preuve.
  - Revalidation directe sur disque de l'intégrité du manifest V2 et du registre d'exclusion.
  - Vérification de l'absence totale de contenu refusé dans l'ensemble promu.
- Régénération de `qualification_blockers.json` et des artefacts de readiness :
  - Bloqueur C1 : **`closed: true`**.
  - Bloqueurs `STAGING_EXTERNE`, `CONCURRENCE`, `MANIFESTE_PRODUCTION` : **`closed: false`**.
  - `go_live_qualification_blockers` : **3**.

---

## 3. Métriques Avant / Après

| Métrique | Avant (Lot CF / PR #223) | Après (Lot CG) | Évolution |
|---|---|---|---|
| **Release candidate active** | `production-profile-gate-2026-2027-v1` | `production-profile-gate-2026-2027-v2` | V2 scellée et enregistrée |
| **Artefacts promus uniques** | 319 | 315 | -4 (exactement les 4 archives ADR-0055) |
| **Placements promus** | 486 | 479 | -7 |
| **Chunks promus** | 8324 | 8268 | -56 |
| **pii_undecided** | 0 | 0 | Inchangé |
| **pre_release_blockers** | 0 | 0 | Inchangé |
| **release_promoted_refused_contents** | 4 | **0** | **-4 (objectif atteint)** |
| **Bloqueur C1** | Ouvert (`closed: false`) | **Fermé (`closed: true`)** | **Fermé avec preuve scellée** |
| **go_live_qualification_blockers** | 4 | **3** | **-1 (C1 clos)** |
| **Bloqueurs ouverts restants** | C1, STAGING, CONCURRENCE, MANIFESTE | STAGING, CONCURRENCE, MANIFESTE | Strictement 3 |
| **GO_LIVE_READY** | `false` | `false` | Inchangé (fail-closed) |
| **assert-ready exit code** | `1` | `1` | Inchangé (fail-closed) |
| **current_switch** | 0 | 0 | Aucun switch |
| **production_db_writes** | 0 | 0 | Zéro écriture |
| **production_deployments** | 0 | 0 | Zéro déploiement |

---

## 4. Vérification et Reproduction

Toutes les suites de vérification sont 100% vertes :

```bash
# 1. Suite de qualification CG dédiée (9 passed)
pytest -v scripts/qualification/tests/test_release_v2_reseal_c1_closure.py

# 2. Ensemble des qualifications de go-live (152 passed, 2 skipped)
pytest -q scripts/qualification/tests

# 3. Tests de cohérence globale et readiness (538 passed, 7 skipped)
pytest -q scripts/tests

# 4. Tests unitaires rag-engine (3788 passed)
PYTHONPATH=.:src services/rag-engine/.venv/bin/pytest -q -m "not integration"

# 5. Tests unitaires rag-pedago (3488 passed, 12 skipped)
services/rag-pedago/.venv/bin/pytest -q services/rag-pedago/tests

# 6. Gardes-fous de gouvernance et intégrité
bash scripts/check-governance-locks.sh
bash scripts/tests/test-governance-locks.sh
bash scripts/check-authority-uniqueness.sh
bash scripts/tests/test-authority-uniqueness.sh
bash scripts/tests/test-repository-hygiene.sh
ruff check packages/release-chain scripts/qualification/tests/test_release_v2_reseal_c1_closure.py services/rag-engine/tests/ services/rag-pedago/tests/
git diff --check

# 7. Contrôle du readiness final
python3 scripts/go_live/check_go_live_readiness.py --check-only
python3 scripts/go_live/check_go_live_readiness.py --assert-ready || true
```
