# LOT_GO_LIVE_FINAL_CI_HGGSP_HLP_SCOPE_POLICY_DECISIONS

- **Branche** : `go-live/hggsp-hlp-scope-policy-decisions`
- **Base** : `8c639a26` (`main`, après merge de #228 / lot CL)
- **Date** : 2026-09-19
- **Nature** : lot de **décision**. Aucun scope émis.

> **L'approbation de cette PR par abenrhouma vaut validation humaine explicite
> des politiques de scope pour HGGSP première, HGGSP terminale et HLP
> terminale, dans le périmètre défini par ADR-0053. Cette approbation n'émet
> encore aucun scope et ne déploie rien.**

## Objet

ADR-0053 a constaté qu'aucune autorité ne couvrait trois collections de la
release `production-profile-gate-2026-2027-v2`, et les a déclarées bloquantes
avec des champs de politique à `null`. Ce lot rend les trois décisions.

| Collection | Placements | Statut après ce lot |
|---|---|---|
| `rag_nexus_hggsp_premiere_specialite` | 39 | `GOVERNED_BY_HUMAN_DECISION` |
| `rag_nexus_hggsp_terminale_specialite` | 35 | `GOVERNED_BY_HUMAN_DECISION` |
| `rag_nexus_hlp_terminale_specialite` | 89 | `GOVERNED_BY_HUMAN_DECISION` |

Couverture du registre : **11/11**, plus aucune politique `null`.

## Les trois décisions

Dimensions identiques pour les trois (les dimensions curriculaires, elles, sont
lues sur la release et diffèrent) :

| Champ | Valeur | Origine |
|---|---|---|
| `audiences` | `[libre, tous]` | **décision humaine Nexus** |
| `rights` | `[officiel_public]` | **décision humaine Nexus** |
| `policy_visibility` | `internal` | **décision humaine Nexus** |
| `evidence_visibility` | `public` | release V2 scellée |
| `programme_version` | BOEN, via `programme_registry.json` | `NEXUS_PROGRAMME_INDEX_REGISTRY_V3` (ADR-0052 §2) |
| `authority_source` | `NEXUS_HUMAN_DECISION_ADR_0053` | — |
| `policy_source_scope_id` | `null` | aucune reconduction invoquée |
| `decision_reviewer` | `abenrhouma` | — |
| `admissibility_status` | `ADMISSIBLE_ON_SEALED_RELEASE_EVIDENCE` | release V2 scellée |

### Divulgation explicite — à peser par le relecteur

**Ces trois triplets sont identiques à la politique uniforme des huit
collections déjà gouvernées** (`[libre, tous]` / `[officiel_public]` /
`internal`, sur les 8/8).

Cette coïncidence est **énoncée, pas dissimulée**, et c'est toute la
différence avec le lot écarté sous `SECURITY_STOP` :

- le lot écarté **présentait** ces valeurs comme reconduites d'un scope
  `prod_*_v1` qu'il avait lui-même fabriqué — l'autorité était fausse ;
- ici `policy_source_scope_id` reste `null` et `authority_source` vaut
  `NEXUS_HUMAN_DECISION_ADR_0053` : la valeur est **décidée**, et la décision
  est celle du relecteur qui approuve cette PR.

Un test refuse toute entrée humainement décidée qui prétendrait à une source de
politique (`test_human_decisions_never_claim_a_policy_source`).

### Ce sur quoi la décision s'appuie, et ce qu'elle ne déduit de rien

**Admissibilité du matériau — sourcée.** La release V2 scellée déclare, pour
les 163 placements des trois collections, `review_status=reviewed`,
`placement_status=active` et `currentness=current`, sous les digests de subject
cités dans le registre. Un test recompte ces trois champs et le nombre de
placements sur la release elle-même
(`test_human_decisions_carry_sourced_admissibility_evidence`).

**Politique d'accès — non sourçable, donc assumée.** Aucun document Eduscol ou
BOEN ne dit qui a le droit de voir quoi. Conformément à la règle 5 du lot, la
source est déclarée pour ce qu'elle est : une décision humaine Nexus au titre
d'ADR-0053, et non une dérivation documentaire.

**Restriction, jamais élargissement.** `policy_visibility=internal` sur
`evidence_visibility=public` resserre l'accès. Vérifié sur les onze
collections, décisions humaines comprises
(`test_policy_visibility_never_widens_evidence_visibility`).

**Vocabulaire canonique.** `audiences`, `rights` et `policy_visibility` sont
vérifiés contre les valeurs que le contrat admet, dérivées du modèle
`RetrievalScopeEvidenceSubject` et de l'énumération `Rights` — jamais
réécrites dans le test.

## Empreinte du registre après décision

```
docs/governance/retrieval_scope_policy_registry.yml
sha256 = 570bfe18c04c63afa6e9516ee2c92df96c6c373dde5e2f7cc435f32f83d3d55d
```

> Cette empreinte ne peut pas figurer *dans* le fichier qu'elle mesure — elle
> est donc consignée ici et dans le corps de la PR. À recalculer avec
> `sha256sum docs/governance/retrieval_scope_policy_registry.yml`.

## Couverture des preuves exigées

| # | Exigence | Test |
|---|---|---|
| 1 | les 11 ont une politique non nulle | `test_every_v2_collection_has_a_non_null_policy` |
| 2 | les 3 ne sont plus `null` | `test_hggsp_and_hlp_decisions_are_no_longer_pending` |
| 3 | aucune valeur recopiée silencieusement | `test_human_decisions_never_claim_a_policy_source` |
| 4 | chaque décision porte une source d'autorité | `test_every_collection_declares_an_authority_source` |
| 5 | `policy_visibility` n'élargit pas | `test_policy_visibility_never_widens_evidence_visibility` (11/11) |
| 6 | `programme_version` via `programme_registry.json` | `test_programme_version_is_read_from_its_authority_not_from_placements`, `test_human_decisions_name_the_programme_authority` |
| 7 | vocabulaire canonique | `test_rights_and_audiences_use_only_canonical_values` |
| 8 | aucune release modifiée | `test_release_v2_manifest_digest_is_unchanged` |
| 9 | aucun scope généré | `test_no_scope_is_emitted_by_this_lot`, `test_human_decision_collections_still_have_no_packaged_scope` |
| 10 | dossier Drive absent | `test_drive_provenance_directory_is_absent_from_the_repository` |

Périmètre du lot vérifié par `test_lot_touches_only_governance_documents` :
aucun chemin `services/`, aucun `packages/contracts/src/`.

## Qualité

- `packages/contracts` : **756 tests verts** (750 avant le lot, +6).
- `ruff` : propre.
- `scripts/check-governance-locks.sh` : 18/18 conformes à la baseline.

## Verrous de gouvernance

Aucun verrou touché. Aucun `promotion_status`, `activation_status` ou
`review_status` modifié. Release V2, manifeste et `release-registry.json`
inchangés (digest vérifié par test). Aucun `current switch`, aucune écriture en
base production, aucune exposition du staging.

## Suite

Après approbation et merge, et **seulement** ensuite :
`LOT_GO_LIVE_FINAL_CI_FIX_V2_RETRIEVAL_SCOPES_FOR_STAGING_V2` — émission des 11
scopes V2 par l'émetteur canonique lisant ce registre, refus de toute
collection sans autorité, vérification des 11 `source_sha256` contre la release
V2, aucun `*_v1` touché, puis rebuild de l'image staging et reprise du lot CI.
