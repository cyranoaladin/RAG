# Lot CF — Outillage d'exclusion gouvernée et préparation du rescellement de release

- **Lot** : `LOT_GO_LIVE_FINAL_CF_EXCLUSION_TOOLING_AND_RESEAL_PREPARATION`
- **Branche** : `go-live/exclusion-tooling-and-reseal-preparation`
- **Base** : `a75550e411159cbbe2b8ad462f23d8e7d3270706` (merge commit PR #222)
- **Registre scellé d'exclusion** : `docs/reports/evidence/release_currentness_exclusion_registry.json` (`07a346b84ae4ebbf1ef7f14dd3f588c95acce36050e8c335f904c37cabe4c72c`)
- **Preuve de préflight scellée** : `docs/reports/evidence/release_exclusion_tooling_preflight_proof.json` (`0c349f7292d073dcd2f0ab4ce60e7db8ac8db6ab0b85ac15489051aa117fc669`)
- **Suite de qualification** : `scripts/qualification/tests/test_release_exclusion_tooling_cf.py` (7 tests passés)

---

## 1. Contexte et Mandat

À l'issue du Lot CE (PR #222), l'ensemble des 149 décisions PII scellées a été importé avec succès. Les refus promus de la release V1 sont passés de 26 à 4. Conformément à l'ADR-0055 et à l'arbitrage formel (Option 1), ces 4 contenus restants sont strictement des archives déclarées par Eduscol (`BLOCKED_NOT_CURRENT_BY_SOURCE`).

Le mandat du **Lot CF** consiste à :
1. Construire et sceller le registre gouverné des exclusions d'actualité pour ces 4 archives.
2. Aligner l'outillage de préflight (`preflight_currentness_reseal.py`) et valider l'admissibilité de la release candidate V2 sous sa nouvelle identité (`production-profile-gate-2026-2027-v2`).
3. Doter le producteur de release canonique (`build_production_profile_release.py`) d'une capacité d'exclusion gouvernée par registre scellé et d'un mode `--dry-run` en mémoire.
4. Prouver en simulation dry-run le rescellement de la release V2 avec ses métriques exactes :
   - **315 artefacts uniques** (319 - 4)
   - **479 placements** (486 - 7)
   - **11 collections** (aucune collection vidée)
   - **8268 chunks uniques** (8324 - 56)
   - **0 écriture sur disque**
5. Garantir les invariants stricts du lot :
   - **Ne PAS fermer C1** dans CF (réservé au rescellement réel du Lot CG).
   - **Ne PAS modifier le readiness** (`release_promoted_refused_contents` reste à 4 dans CF).
   - **Ne PAS toucher à la release historique V1** (`production-profile-gate-2026-2027-v1`, immuable sous ADR-0050).
   - `GO_LIVE_READY=false`, `--assert-ready=1`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.

---

## 2. Réalisations Techniques

### 2.1 Registre gouverné scellé d'exclusion d'actualité

- Création du constructeur gouverné `scripts/go_live/build_release_currentness_exclusion_registry.py`.
- Production et scellement des artefacts :
  - `docs/reports/evidence/release_currentness_exclusion_registry.json`
  - `docs/reports/evidence/release_currentness_exclusion_registry.sha256` (`07a346b84ae4ebbf1ef7f14dd3f588c95acce36050e8c335f904c37cabe4c72c`)
- Kind scellé : `NEXUS-CURRENTNESS-EXCLUSION-REGISTRY-V1`.
- Référence de gouvernance : `ADR-0055`.
- Les 4 archives déclarées sont exhaustivement et exclusivement répertoriées :
  1. `157309db13b674ffe4bf1371015bfc7c9c9cf475af75769a6beaf4dade45925f` — EAF 2024 (2 placements, 13 chunks, PII_CLEARED)
  2. `174f273ff25818064be60cd4c7cded89ab8f257de484b32a21250578f323149b` — DGEMC (1 placement, 25 chunks, PII_CLEARED_OR_NOT_SCANNED)
  3. `ccffe628bbd64e34a8442a045f95ec2ef65109765c0a0a476c0156aa84a5f9a2` — SVT voie technologique (2 placements, 9 chunks, PII_CLEARED_OR_NOT_SCANNED)
  4. `dc58fcc42ef9b4e6d15a129124eff54ce5d76e0e16e1e4f62115b64482e94fd2` — SVT voie générale (2 placements, 9 chunks, PII_CLEARED_OR_NOT_SCANNED)
- Épinglage explicite du constructeur sous `MATRIX_READER` dans `scripts/authority-uniqueness.baseline` pour préserver l'isolation d'autorité.

### 2.2 Préflight de rescellement et preuve formelle

- Adaptation de `scripts/go_live/preflight_currentness_reseal.py` :
  - Support des statuts sains PII admissibles (`PII_CLEARED_OR_NOT_SCANNED` et `PII_CLEARED`).
  - Intégration de l'option `--exclusion-registry` avec contrôle d'intégrité SHA-256 et concordance stricte des 4 contenus.
  - Test d'admissibilité de l'identité `production-profile-gate-2026-2027-v2` (`identity_free: true`).
- Production et scellement de la preuve de préflight :
  - `docs/reports/evidence/release_exclusion_tooling_preflight_proof.json`
  - `docs/reports/evidence/release_exclusion_tooling_preflight_proof.sha256` (`0c349f7292d073dcd2f0ab4ce60e7db8ac8db6ab0b85ac15489051aa117fc669`)
  - Résultat : `preflight_passed: true`, `blocking_findings: []`, `contents_to_exclude.count: 4`.

### 2.3 Adaptation du constructeur de release (`build_production_profile_release.py`)

- Implémentation du chargeur fail-closed `load_and_validate_exclusion_registry` :
  - Vérification d'existence du fichier.
  - Vérification du hash SHA-256 (fail-closed si discordance).
  - Validation du `kind`, de la référence `ADR-0055`, et du compte exact de 4 entrées.
  - Validation stricte des statuts `ARCHIVE_DECLARED` et `BLOCKED_NOT_CURRENT_BY_SOURCE`.
  - Aucune lecture de la matrice de servabilité dérivée dans le module de production.
- Intégration des options CLI :
  - `--exclusion-registry <path>`
  - `--exclusion-registry-sha256 <sha256>`
  - `--dry-run`
- Rôle du mode `--dry-run` :
  - Calcule l'intégralité de la release candidate en mémoire.
  - Extrait et vérifie les comptages agrégés et individuels.
  - Quitte avec code 0 **sans appeler `_write_documents`** (aucune écriture disque).
- Liaison d'autorité et packaging :
  - Inscription de l'autorité `currentness_exclusion_registry_sha256` dans `authority_bindings.json`.
  - Packaging du fichier `release_currentness_exclusion_registry.json` dans la release.

### 2.4 Preuve dry-run du rescellement de release V2

Exécution vérifiée :
```bash
./services/rag-pedago/.venv/bin/python3 services/rag-pedago/scripts/build_production_profile_release.py \
  --release-mode rehearsal \
  --source-release-root services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate \
  --release-id production-profile-gate-2026-2027-v2 \
  --exclusion-registry docs/reports/evidence/release_currentness_exclusion_registry.json \
  --exclusion-registry-sha256 07a346b84ae4ebbf1ef7f14dd3f588c95acce36050e8c335f904c37cabe4c72c \
  --dry-run
```

Sortie standard constatée :
```
DRY_RUN=true
EXCLUDED_CONTENTS_COUNT=4
PRODUCTION_PROFILE_RELEASE_UNIQUE_ARTIFACTS=315
PRODUCTION_PROFILE_RELEASE_PLACEMENTS=479
PRODUCTION_PROFILE_RELEASE_COLLECTIONS=11
PRODUCTION_PROFILE_RELEASE_CHUNKS=8268
PRODUCTION_PROFILE_RELEASE_SHA256=e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864
```

Vérification d'intégrité :
- Aucun fichier ni répertoire n'a été créé sous `data/releases/`.
- La release V1 reste rigoureusement intacte (319 artefacts uniques, 486 placements, 8324 chunks).

---

## 3. Métriques et Invariants de Gouvernance

| Métrique | Valeur Lot CF | Règle / Invariant |
|---|---|---|
| `pii_undecided` | **0** | Maintenu fermé |
| `pre_release_blockers` | **0** | Maintenu fermé |
| `release_promoted_refused_contents` | **4** | Inchangé (C1 reste ouvert jusqu'au rescellement réel en CG) |
| `go_live_qualification_blockers` | **4** | Ouverts : C1, STAGING_EXTERNE, CONCURRENCE, MANIFESTE_PRODUCTION |
| `go_live_ready` | **false** | Strictement faux |
| `--assert-ready` | **exit 1** | Échec fail-closed garanti |
| `current_switch` | **0** | Aucune bascule |
| `production_db_writes` | **0** | Aucune écriture en base de production |
| `production_deployments` | **0** | Aucun déploiement en production |

---

## 4. Résultats des Vérifications et Tests

- **Tests de qualification CF** (`scripts/qualification/tests/test_release_exclusion_tooling_cf.py`) : **7/7 passés**
- **Ensemble des qualifications** (`scripts/qualification/tests/`) : **143 passés, 2 ignorés**
- **Scripts unitaires** (`scripts/tests/`) : **538 passés, 7 ignorés**
- **Tests plan de contrôle** (`services/rag-pedago/tests`) : **3490 passés, 12 ignorés**
- **Tests plan de données** (`services/rag-engine/tests -m "not integration"`) : **100% passés**
- **Verrous de gouvernance** (`scripts/check-governance-locks.sh`) : **OK (18 clés vérifiées)**
- **Unicité d'autorité** (`scripts/check-authority-uniqueness.sh`) : **NEXUS-AUTHORITY-UNIQUENESS-V1: PASS**
- **Hygiène du dépôt** (`scripts/tests/test-repository-hygiene.sh`) : **PASS**
- **Linter** (`ruff check`) : **All checks passed!**
- **Git diff cleanliness** (`git diff --check --cached`) : **Code 0**

---

## 5. Transition vers le Lot CG

L'outillage d'exclusion, les registres scellés, le préflight et le constructeur sont désormais entièrement qualifiés. Le **Lot CG** (`LOT_GO_LIVE_FINAL_CG_RESEAL_AND_C1_CLOSURE`) pourra s'exécuter pour :
1. Produire la release effective `production-profile-gate-2026-2027-v2` sur disque avec application du registre d'exclusion.
2. Mettre à jour `release-registry.json` pour pointer vers V2.
3. Fermer définitivement le bloqueur **C1**.
4. Constater `release_promoted_refused_contents: 4 -> 0`.
