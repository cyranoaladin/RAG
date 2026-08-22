# Lot — Réconciliation set-theoretic Tier A (2026-08-22)

## 1. Périmètre

Reproduction indépendante, depuis `main` propre (`b9e3b47dd952991236e44b3afb605bf6e63d388f`),
dans un worktree dédié (`rag-pedago/tier-a-currentness-clean-20260822`), du
gate H2 sans autorité et de l'algèbre exacte des registres de currentness
Tier A. Aucune donnée issue de la branche non revue
`rag-pedago/tier-a-currentness-byte-identity-20260820` (mise en quarantaine,
voir rapport de session séparé) n'a été réutilisée : chaque nombre ci-dessous
est recalculé depuis les entrées réelles, jamais recopié.

Script : `services/rag-pedago/scripts/tier_a_set_algebra_report.py` — appelle
uniquement les fonctions déjà revues (`pii_scan_reconciliation`,
`corpus_catalog_compiler`, `h2b_coverage_report`), ne duplique aucune logique
de gate. `ruff check` / `mypy` propres.

## 2. Fichiers d'entrée réels — vérifiés par sha256

| Fichier | sha256 | Vérifié contre |
|---|---|---|
| Manifeste scellé (`00_ADMIN/SHA256SUMS.txt`) | `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` | `SEALED_MANIFEST_SHA256` cité dans `lot_evidence_index_reconciliation.md`, `lot_authority_required_set_correction.md`, `lot_h2b_production_readiness.md` (merged) |
| Registre de droits (`configs/rights_evidence_registry.yml`) | `e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff` | digest "rights registry" cité dans `lot_multilevel_ingestion_2026_2027.md` (merged) |
| Currentness registry (`configs/prerentree_2026_2027/multilevel_currentness_evidence.yml`) | `2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122` | digest "currentness artifact-bound" cité dans `lot_multilevel_ingestion_2026_2027.md` (merged) |
| Routing policy (`configs/corpus_zone_routing.yml`) | `0d4d25215cb0ed40c439ff172c9dbce3f2a1b0b945313a042285b2e57bffc833` | — (pas de digest publié à comparer ; fichier versionné, provenance = repo) |
| Golden corpus (`configs/golden_corpus_h2b.yml`) | `28856e0655eca7695f273a5934925785c49ecf828d930804984f6e58f4da6f69` | — (idem, versionné) |
| Placement catalog (`00_ADMIN/eduscol_affectations.tsv`) | `25cf40cec8a98692d4532a71b58a9685821bbc2b9a4785c25fac7138a49906ec` | chemin exact cité en dur dans `lot_fix_catalog_compiler_schema.md` (merged) : `Path.home() / "Téléchargements/NEXUS_RAG_GDRIVE_READY/00_ADMIN/eduscol_affectations.tsv"` |
| Scan PII exhaustif (`h2b_exhaustive_pii_scan_20260813.jsonl`) | `0229a0f2d7edbd1bb1b1412a8ccd447b3c6d2ce71dc73a0f2e726751156fa357` | 2411 lignes, conforme à `lot_pii_scan_reconciliation.md` |
| Scan PII campagne (`h2b_pii_evidence_20260808.json`) | `76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311` | 64 empreintes, conforme à `lot_pii_scan_reconciliation.md` |

Les deux scans PII et le manifeste vivent hors dépôt (« trove » local), par
convention déjà documentée (`lot_pii_scan_reconciliation.md` §4) — pas une
lacune de ce lot.

## 3. Étape 1 — Reproduction du gate H2 sans autorité (garde-fou fail-closed)

```
required_pdf_path_count=2476, results=2475 (1 doublon de contenu)
CLEARED=2286, QUARANTINED_PII=146, REVIEW_REQUIRED_EXTRACTION_FAILED=43
```
→ identique à PR#124 (`lot_pii_scan_reconciliation.md` §3), recoupement
indépendant confirmé une seconde fois.

```
BLOCKED_INGEST_CANDIDATES=73
AUTHORITY_REQUIRED_COUNT=72
AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
PII_BLOCKED_COUNT=1
H2_COVERAGE_GATE_PASS=false
GOLDEN_VALIDATION_PASS=true (13/13)
```
→ **identique bit à bit** à PR#125 (`lot_authority_required_set_correction.md`).
**RÉPRODUCTION : PASS.** Le reste de ce rapport peut s'appuyer sur ces
données réelles.

## 4. Étape 2 — Algèbre exacte des registres de currentness

Deux registres réels existent (jamais un seul) :
- `multilevel_currentness_evidence.yml` — 150 artefacts, partition stricte
  (par construction, clé `partition` du fichier) : 12 `CURRENT`, 138
  `REVIEW_REQUIRED`.
- `wave0_currentness_evidence_v2.yml` — 2 artefacts (Troisième, hors
  périmètre lycée du fichier précédent), tous deux `effective_currentness:
  actuel` / `byte_identity: true`.

En restreignant chaque registre au pool réel `currentness ∈
{unclassified, a_verifier}` du catalogue recompilé (jamais supposé) :

```
SET_CURRENT=10                     # 12 CURRENT − 2 déjà ailleurs INGEST (10_ACTUEL_CONFIRME)
SET_WAVE0=2                        # les 2 artefacts Wave0 sont bien dans le pool indéterminé
SET_REVIEW_REQUIRED_PENDING=138

CURRENT_INTERSECT_WAVE0=0
CURRENT_INTERSECT_REVIEW_REQUIRED=0   # partition garantie par construction du fichier
WAVE0_INTERSECT_REVIEW_REQUIRED=0
TRIPLE_INTERSECTION=0

UNION_REGISTRY_COVERED_UNCLASSIFIED=150   # 10 + 2 + 138, aucun chevauchement réel
```

**Écart avec la valeur attendue de 141 : réel, expliqué, pas forcé.**
141 n'est **pas** le bon nombre pour cette union — voir §5, où 141 réapparaît
exactement mais pour une définition différente (PII-cleared ∩
`currentness=unclassified` uniquement, en excluant `a_verifier`). La mission
avait fusionné deux quantités distinctes sous le même nom ; les deux sont
maintenant produites séparément et aucune n'a été forcée pour coller à une
attente.

Les deux items `CURRENT` exclus de `SET_CURRENT` (déjà classés
`10_ACTUEL_CONFIRME` par le routage de zone, donc jamais dans le pool
indéterminé) :
`b88b5c685ec05d44b0c22d64f491443759fc0f544fe9ad33e626fb6cc29bf65a`,
`c07f8b2db9d22a6c2b9ab8386cf7ba323bc2c56abacb3f560dd97d02b383de18`.
Ce sont deux des trois items déjà mentionnés dans
`master_go_live_state_20260815.md` §5 (« 2 étaient déjà 10_ACTUEL_CONFIRME »).
Protocole autoritaire pour ces deux contenus : le routage de zone
(`corpus_zone_routing.yml`), pas le registre de currentness — aucun
superseding réel, les deux sources s'accordent (le registre les marque
`CURRENT` précisément parce qu'ils sont déjà `actuel`).

## 5. Étape 3 — Deux univers séparés : PII seul vs PII+droits

```
PII_CLEARED_CURRENTNESS_UNDETERMINED:
  UNCLASSIFIED_ZERO_REGISTRY=1252
  UNCLASSIFIED_REGISTRY_COVERED=141
  A_VERIFIER=746
  TOTAL=2139

PII_AND_RIGHTS_CLEARED_CURRENTNESS_UNDETERMINED:
  UNCLASSIFIED_ZERO_REGISTRY=1252
  UNCLASSIFIED_REGISTRY_COVERED=141
  A_VERIFIER=746
  TOTAL=2139
```

**Constat, pas un bug** : les deux univers sont rigoureusement identiques.
Sur ce périmètre précis (contenus `currentness ∈ {unclassified, a_verifier}`
et PII-cleared), l'ensemble droits-clairs (`_derive_rights_clearances`, sur
le vrai registre de droits) est un sur-ensemble strict de l'ensemble
PII-clair — cohérent avec le constat déjà versionné
`RIGHTS_AS_BLOCKER=false` (`master_go_live_state_20260815.md` §5 :
« 2405/2408 REVIEW_REQUIRED déjà CLEARED_BY_HUMAN_DECISION »). Le périmètre
réellement pertinent pour un futur lot INGEST est le second
(`_apply_mandatory_ingest_gates` exige droits **et** PII) ; ici les deux
coïncident numériquement mais ne sont pas identiques par construction — un
futur lot ne doit jamais supposer que ça restera vrai sans le revérifier.

`UNCLASSIFIED_REGISTRY_COVERED=141` ici est le nombre qui correspond
exactement à la valeur attendue par la mission — **141 est confirmé**, mais
pour cette définition précise (PII-cleared, `currentness=unclassified`
strictement, couvert par n'importe lequel des trois registres), pas pour
l'union du §4.

## 6. Étape 4 — Delta historique

```
HISTORICAL_REPORTED_TIER_A=1252
CURRENT_REPRODUCED_HISTORICAL_PREDICATE=1252
HISTORICAL_MEASUREMENT_DELTA=0
HISTORICAL_DELTA_FORENSICALLY_RESOLVABLE=true   # delta nul : rien à résoudre
```

**Le nombre historique de 1252 se reproduit exactement.** La mission
mentionnait une reproduction courante à 1253 (delta de 1, non résolu) : cette
reproduction indépendante, depuis main propre, ne confirme pas 1253 — elle
reproduit 1252, identique à l'historique. Aucune régression, aucun forçage :
c'est la valeur qui sort du calcul réel décrit ci-dessus.

## 7. Étape 5 — Entrées de l'audit byte-identity

`SET_REVIEW_REQUIRED_PENDING` (138 exactement) devient la liste d'entrée de
l'audit réseau byte-identity, sans aucune requête réseau effectuée dans ce
lot :

```
BYTE_IDENTITY_AUDIT_INPUT_COUNT=138
```

Chaque ligne porte `content_sha256`, `canonical_path` (chemin réel du
catalogue), `source_registry` (`multilevel_currentness_evidence.yml`),
`source_url` (laissé `null` — le registre ne porte réellement aucune URL
pour ces 138 entrées `REVIEW_REQUIRED`, jamais devinée),
`programme_version` (`current_for_school_year`, réel), et des champs
`http_result`/`download_sha256`/`byte_identity`/`decision`/
`effective_currentness`/`reason_code` — les cinq premiers en `null`
(placeholders pour le suivi réseau), `reason_code` déjà rempli
(`CURRENT_SOURCE_BYTE_IDENTITY_NOT_AUDITED` pour les 138).

**Recoupement indépendant fort** : le digest de cet ensemble de 138
`content_sha256` (`input_set_sha256=152bd6fc0f2441beff9a8f41744c0f58289f1c05900fe607c19be32f4f3f2a89`)
est **identique** à celui produit par la branche quarantinée
(`tier_a_byte_identity_evidence.json`, même clé). Les deux calculs,
indépendants, arrivent au même ensemble exact de 138 identités — un signal
positif sur cette partie précise du WIP quarantiné (jamais utilisé comme
preuve, seulement comme indice, conformément à la consigne de quarantaine ;
ce recoupement confirme *a posteriori* qu'il pointait au bon endroit).

## 8. Désaccords explicites avec le WIP quarantiné et avec les chiffres "conceptuels" de la mission

| Quantité | WIP quarantiné / mission | Cette reproduction | Verdict |
|---|---|---|---|
| `registry_union` (§4, définition large) | 150 (WIP) | 150 | **Accord** |
| `set_wave0` | 0 (WIP) | 2 | **Désaccord** — le WIP semble avoir exclu Wave0 du pool indéterminé ; cette reproduction vérifie directement la `currentness` catalogue des 2 sha256 Wave0 et les trouve dans le pool. |
| `UNCLASSIFIED_REGISTRY_COVERED` (PII-cleared) | 139 (WIP) / 141 (mission) | 141 | **Mission confirmée, WIP en désaccord** (écart de 2 avec le WIP, cause non investiguée — hors périmètre de la quarantaine). |
| `UNCLASSIFIED_ZERO_REGISTRY` (PII-cleared) | 1255 (WIP) / 1252 ou 1253 (mission) | 1252 | **Historique (1252) confirmé, ni le WIP (1255) ni "1253" ne le sont.** |
| `TOTAL_CURRENTNESS_UNDETERMINED` (PII-cleared) | 2140 (WIP/mission) | 2139 | **Désaccord de 1**, cohérent avec 1252+141+746=2139 (arithmétique interne correcte ici). |
| `UNION_REGISTRY_COVERED_UNCLASSIFIED` (§4) | 141 (attendu par la mission) | 150 | **La mission a fusionné deux définitions distinctes** — voir §4/§5 : 141 est correct pour la définition du §5, pas pour celle du §4. |
| `byte_identity_audit_input` set (138 sha256) | digest identique | digest identique | **Accord fort, indépendant.** |

Aucun nombre ci-dessus n'a été ajusté pour correspondre à une attente — les
désaccords sont rapportés tels quels.

## 9. Ce qui n'a pas été fait dans ce lot

- Aucune requête réseau (audit byte-identity réel des 138 sources
  primaires) — périmètre d'un lot séparé.
- Aucun contrat touché (`packages/contracts/src/nexus_contracts/*`) —
  aucun blocker rencontré ne l'exigeait.
- Aucune autorité, campagne ou autorisation réelle créée.
- Aucun push, aucune PR ouverte.

## 10. Booléens finaux

```
H2_BASELINE_REPRODUCED_EXACTLY=true
TIER_A_SET_ALGEBRA_COMPUTED_FROM_REAL_DATA=true
CONTRACT_BLOCKER=none
GOVERNANCE_LOCKS_TOUCHED=false
REAL_AUTHORITY_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
PGVECTOR_WRITES=0
```
