# Master Go-Live State — snapshot du 2026-08-15 (soir), mis à jour 2026-08-22

> Source de vérité unique, séquencée, pour la suite de la mission go-live RAG
> Nexus. **Ceci est un instantané d'un état observé, pas une API live de la
> branche `main`** — un document committé ne peut jamais maintenir
> honnêtement un `current_main_sha` puisque son propre merge fait avancer
> `main`. Le SHA live doit toujours être relu depuis GitHub/Git ; les champs
> `state_observed_at_*` ci-dessous décrivent l'état au moment de la
> génération, jamais un pointeur vivant.
>
> Mise à jour de ce même document (version initiale mergée via PR#120,
> rafraîchie via PR#123, puis à nouveau ici après PR#124/#125/#126 et le lot
> Tier A byte-identity + scope/profile du 2026-08-22) — pas un nouveau
> fichier daté parallèle. Chaque ligne porte sa preuve.

```
state_generated_at=2026-08-22T00:00:00Z
state_observed_at_main_sha=b9e3b47dd952991236e44b3afb605bf6e63d388f
```

> Ce SHA décrit l'état observé **au moment de la génération**. Une fois ce
> lot mergé, `main` aura déjà avancé d'au moins ce merge lui-même — c'est
> attendu et normal pour un instantané, jamais un défaut à corriger en
> committant un SHA auto-référent.

## 1. PR merges (DONE — revérifié live, `gh pr view --json state,mergedAt,mergeCommit`)

| PR | Sujet | Statut | Merge SHA | Merged at |
|---|---|---|---|---|
| #100 | Signing tool production readiness | DONE | `057e93c` | 2026-08-15T08:26:37Z |
| #107 | Atomic deployment wrapper (Lot C) | DONE | `439255f` | 2026-08-15T10:15:21Z |
| #108 | Evidence-index / terminal-disposition ledger | DONE | `5f44a46` | 2026-08-15T10:31:15Z |
| #109 | H2 workflow E2E rehearsal | DONE | `7117a41` | 2026-08-14T21:53:42Z |
| #110 | Canonical promotion workflow | DONE | `a8a41c7` | 2026-08-14T23:12:58Z |
| #111 | Catalog compiler schema fix | DONE | `fc4d80a` | 2026-08-15T09:12:10Z |
| #112 | Image-provenance fail-open fix | DONE | `c2c08dd` | 2026-08-15T10:45:43Z |
| #114 | Trusted-review check-SHA fix (check-run, superseded by #119) | DONE | `0d98475` | 2026-08-15T09:32:43Z |
| #115 | H2 authority-promotion gap (Finding C) | DONE | `3308fcf` | 2026-08-15T09:52:50Z |
| #116 | Ratification post head-drift incident | DONE | `6867f98` | 2026-08-15T13:16:23Z |
| #119 | Trusted-review status transport fix (Commit Status) | DONE | `a2a69dd` | 2026-08-15T15:33:18Z |
| #120 | Master go-live state (v1, superseded) | DONE | `4b2f611` | 2026-08-15T16:05:43Z |
| #121 | Governed catalog republish mechanism | DONE | `8ad8741` | 2026-08-15T17:18:23Z |
| #122 | Currentness-verified promotion | DONE | `353703f` | 2026-08-15T20:35:48Z |
| #123 | Master go-live state refresh (v2, superseded by this doc), Drive snapshot | DONE | `8844407` | 2026-08-15T20:52:44Z |
| #124 | Reconcile the two real PII scans into a complete gate input | DONE | `1d7cf45` | 2026-08-15T21:15:47Z |
| #125 | Bind authority completeness to post-currentness, non-authority-cleared candidates | DONE | `3167b1c` | 2026-08-15T23:42:14Z |
| #126 | Refuse `report_to_h2_coverage_evidence` without authority explicitly | DONE | `b9e3b47` | 2026-08-16T07:45:20Z |

PR#96 et PR#98 : voir §6 (audit dédié, ni mergées ni fermées — revérifié live
le 2026-08-22, toujours `OPEN`, non-`Draft`).

## 2. Gate d'intégrité gouvernance (DONE — inchangé)

```
TRUSTED_REQUIRED_GATE_RELIABLY_ENFORCED=true
required_context_final_name=trusted-human-review/head-pinned
```
Confirmé en conditions réelles sur PR#120/#121/#122 : approbation réelle →
Commit Status `success` → branch protection reconnaît nativement → merge
sans aucun rollback de protection. Preuve :
`docs/reports/trusted_review_head_drift_incident_20260815.md`,
`docs/reports/trusted_review_branch_protection_rehearsal_20260815.md`.

## 3. Booleans techniques de préparation (DONE — inchangé depuis PR#123)

```
PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=true
CATALOG_REAL_CORPUS_COMPILE_PASS=true
H2_WORKFLOW_E2E_REHEARSAL_PASS=true
GOVERNED_REPUBLISH_STEP_EXISTS=true
GOVERNED_REPUBLISH_REAL_CAMPAIGN_EXECUTED=false   # mécanisme prêt, jamais encore exécuté pour de vrai
CURRENTNESS_VERIFIED_PROMOTION_STEP_EXISTS=true
CURRENTNESS_VERIFIED_PROMOTION_REAL_RUN_EXECUTED=false   # mécanisme prêt, jamais encore exécuté pour de vrai
ATOMIC_DEPLOY_REHEARSAL_PASS=PARTIAL
```
Non retouché par le lot du 2026-08-22 (hors périmètre annoncé de ce lot).
Danger réel toujours présent sur cet hôte, non revérifié dans ce lot :
stack `infra` dev locale + stack orpheline `rag-smoke-ci3` — signalées le
2026-08-15, non touchées.

## 4. Corpus / éligibilité (revérifié depuis l'artefact canonique commité)

```
PHYSICAL_FILES=2584
MANIFEST_ENTRIES=2583
UNIQUE_CONTENT_SHA256=2582
DUPLICATE_CONTENT_GROUPS=1

CURRENT_RELEASE_ELIGIBLE_ARTIFACTS=63
BASE_INGEST_CANDIDATES=73          # inchangé — reconfirmé bit-à-bit le 2026-08-22
CURRENT_AUTHORITY_REQUIRED_COUNT=72   # inchangé — reconfirmé bit-à-bit le 2026-08-22
CURRENT_AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
PII_BLOCKED_COUNT=1
FINAL_RELEASE_ELIGIBLE_ARTIFACTS=UNKNOWN   # tant que Tier A n'est pas clos pour cette release
```

**Pourquoi le baseline 73/72 n'a pas bougé le 2026-08-22** : le lot Tier A
byte-identity de ce jour (§5) a audité en réseau, pour de vrai, les 138
candidats `REVIEW_REQUIRED` en attente de vérification de source — zéro
n'a pu être promu (voir §5, blocage Cloudflare, pas un verdict de
currentness). Sans nouvelle entrée `CURRENT_BYTE_IDENTICAL`, le registre de
currentness-verification n'a pas changé, donc le catalogue recompilé est
identique et 73/72/`3705935f...` ne pouvaient pas changer — ceci a été
constaté par raisonnement direct sur les entrées, pas supposé par
convention (l'instruction de ce lot était explicitement de ne jamais
préserver 72 par convention).

## 5. Tier A / currentness — réconciliation complète et audit réseau réel (2026-08-22)

Remplace entièrement le §5 précédent (investigation du 2026-08-15, jamais
chiffrée exactement). Reproduit depuis `main` propre
(`b9e3b47dd952991236e44b3afb605bf6e63d388f`) dans un worktree dédié
(`rag-pedago/tier-a-currentness-clean-20260822`), sans reprendre aucune
donnée d'un WIP non revu trouvé et mis en quarantaine sur cet hôte
(`rag-pedago/tier-a-currentness-byte-identity-20260820`, 44 commits non
revus + modifications non commitées touchant des contrats cœur et un
ADR-0043 non ratifié — photographié en lecture seule dans
`~/Documents/NEXUS_RAG_WIP_QUARANTINE/tier-a-20260822/`, jamais utilisé
comme preuve).

### 5.1 Algèbre exacte des registres de currentness

Preuve : `docs/reports/tier_a_set_algebra_reconciliation_20260822.json` +
`docs/reports/lot_tier_a_set_algebra_20260822.md`.

```
SET_CURRENT=10
SET_WAVE0=2
SET_REVIEW_REQUIRED_PENDING=138
(toutes intersections pairwise et triple = 0 — partition garantie par construction)
UNION_REGISTRY_COVERED_UNCLASSIFIED=150
```

**Clarification importante** : la mission attendait une union à 141. 141 est
réel, mais désigne une quantité différente (voir 5.2) — pas l'union
ci-dessus, qui est 150. Les deux quantités ont été fusionnées à tort sous
le même nom dans le cadrage initial ; elles sont maintenant produites
séparément et documentées.

### 5.2 Deux univers séparés : PII-cleared vs PII+droits-cleared, currentness indéterminée

```
PII_CLEARED_CURRENTNESS_UNDETERMINED:
  UNCLASSIFIED_ZERO_REGISTRY=1252
  UNCLASSIFIED_REGISTRY_COVERED=141   # <- ici que 141 est le nombre exact attendu
  A_VERIFIER=746
  TOTAL=2139

PII_AND_RIGHTS_CLEARED_CURRENTNESS_UNDETERMINED:
  UNCLASSIFIED_ZERO_REGISTRY=1252
  UNCLASSIFIED_REGISTRY_COVERED=141
  A_VERIFIER=746
  TOTAL=2139
```
Les deux univers coïncident numériquement sur ce périmètre précis (cohérent
avec `RIGHTS_AS_BLOCKER=false` déjà constaté le 2026-08-15 : 2405/2408
`REVIEW_REQUIRED` déjà `CLEARED_BY_HUMAN_DECISION`) — un futur lot ne doit
jamais supposer que cela reste vrai sans revérifier, les deux ensembles ne
sont pas identiques par construction.

### 5.3 Delta historique

```
HISTORICAL_REPORTED_TIER_A=1252
CURRENT_REPRODUCED_HISTORICAL_PREDICATE=1252
HISTORICAL_MEASUREMENT_DELTA=0
```
Le nombre historique de 1252 (déjà versionné en §`tier_a_investigation`
depuis PR#123) se reproduit exactement. Le cadrage initial mentionnait une
reproduction courante à 1253 (delta de 1, non résolu) — cette reproduction
indépendante ne la confirme pas.

### 5.4 Audit byte-identity réseau réel (138 sources primaires)

Preuve : `docs/reports/tier_a_byte_identity_network_audit_20260822.json` +
`docs/reports/lot_tier_a_byte_identity_network_audit_20260822.md`.

Provenance URL réelle trouvée dans le corpus scellé lui-même
(`00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES/catalogue-complet.tsv`, colonne
`url_source`, clé `sha256`) — 138/138 résolus vers 8 URLs distinctes
(plusieurs PDF cités depuis la même page article Éduscol).

```
NETWORK_PROBE_PASS=false
DIAGNOSIS=CLOUDFLARE_BOT_PROTECTION_403_DOMAIN_WIDE   # pas DNS/TLS/no-egress/local
BYTE_IDENTITY_CURRENT=0
BYTE_IDENTITY_CHANGED=0
BYTE_IDENTITY_NOT_FOUND=0
BYTE_IDENTITY_UNAVAILABLE=138
BYTE_IDENTITY_AMBIGUOUS=0
BYTE_IDENTITY_CONFLICT=0
```
Diagnostic confirmé (contrôles `1.1.1.1`/`google.com` OK, DNS résout bien,
`robots.txt` d'Éduscol autorise explicitement le crawl) : le blocage est un
403 Cloudflare au niveau du domaine, vérifié individuellement sur les 8
URLs distinctes (pas une extrapolation depuis un échantillon), aucune
tentative d'évasion. **`SOURCE_UNAVAILABLE` ≠ `NOT_CURRENT`** : les 138
restent `pending`, aucune promotion, aucune démotion, aucun archivage.
Suite requise : accès réseau non filtré (poste opérateur réel) ou
arrangement d'accès — hors périmètre technique de ce lot, décision
opérateur.

## 6. PR#96 / PR#98 — audit (DONE, décision toujours réservée à l'opérateur)

```
PR96_ACTION=KEEP_OPEN
PR98_ACTION=REUSE_AS_SUBSET
PR96_PR98_OVERLAP=none
```
Revérifié live le 2026-08-22 (`gh pr view 96/98`) : les deux toujours
`OPEN`, non-`Draft`. Aucune action prise — décision opérateur requise avant
construction des autorisations finales.

## 7. Google Drive (DONE — non rescanné dans ce lot, lecture seule du mirroir)

```
DRIVE_MIRROR_COMPLETE=true
DRIVE_CURRENT_CONTENT_FILES=2584
DRIVE_MANIFEST_ENTRIES_MATCHED=2583
DRIVE_EXTRA_UNACCOUNTED=1
DRIVE_CANONICAL_FILES_MISSING=0
DRIVE_SHA_MISMATCH=0
```
Preuve inchangée depuis le 2026-08-15 :
`docs/reports/evidence-index/drive-snapshot/drive_snapshot_mapping_20260815.json`,
`drive_snapshot_metadata_20260815.json`. Le lot du 2026-08-22 a **lu** le
mirroir local (`~/Téléchargements/NEXUS_RAG_GDRIVE_READY/`) comme source
d'évidence (manifeste scellé, TSV de provenance) sans le rescanner ni
revérifier sa complétude — usage en lecture, pas un audit Drive.

## 8. Scope / profils gouvernés — audit réel (NOUVEAU, 2026-08-22)

Preuve : `docs/reports/tier_a_scope_profile_audit_clean_20260822.json` +
`docs/reports/lot_tier_a_scope_profile_multiscope_audit_20260822.md`.

```
AUTHORITY_REQUIRED_CONTENT_COUNT=72
DISTINCT_LEVEL_SUBJECT_PAIRS=22
DISTINCT_CANONICAL_RESOURCE_SCOPES (10 dimensions, entièrement ancré)=0
ITEMS_WITH_UNRESOLVED_DIMENSION=72/72
```
**Constat structurel, pas un bug** : sur les 10 dimensions de
`ResourceScope`, seules `matiere`/`niveau` (placements pédagogiques réels)
et `school_year` (config de release) sont ancrables depuis une donnée de
contenu réelle. `tenant`/`collection`/`voie`/`candidat`/`audience`/
`visibility`/`programme_version` sont assignées par profil ou campagne,
jamais intrinsèques au contenu — c'est pourquoi aucun des 72 n'obtient un
tuple à 10 dimensions entièrement ancré indépendamment d'un profil.

```
PRODUCTION_PROFILE_FILES=1
STAGING_PROFILE_FILES=2   (+ 1 sous-répertoire multilevel, + 1 manifest)
AUTHORITY_REQUIRED_MAPPED_PRODUCTION=0
AUTHORITY_REQUIRED_MAPPED_STAGING=0
AUTHORITY_REQUIRED_NO_PROFILE=72
AUTHORITY_REQUIRED_AMBIGUOUS_PROFILE=0
```
Cas notable signalé, non résolu ici : les 5 items Philosophie s'ancrent à
`niveau=non-classe` (Éduscol ne grade-tag jamais la Philosophie), donc même
eux échouent un match exact contre l'unique profil de production
(`philosophie_terminale_tc_h2c_v1.yml`, `niveau=terminale`) — décision
humaine, pas résolue par ce lot.

### 8.1 Architecture multi-scope — audit uniquement, aucun code touché

```
MULTISCOPE_ARCHITECTURE_DECISION=Chaque étage de la chaîne d'autorisation est architecturé pour exactement un ResourceScope par run ; le vrai set de 72 couvre >=22 couples (niveau, matiere) distincts, donc il ne peut pas être prouvé complet en un seul passage sans élargir artificiellement le scope.
EXISTING_CONTRACT_SUFFICIENT=false
CONTRACT_CHANGE_REQUIRED=true
```
Preuve par lecture directe (vérifiée indépendamment) :
`ScopeAuthorizationArtifactV2.scope: ResourceScope`
(`packages/contracts/src/nexus_contracts/authority_artifacts.py:360`,
singulier) et `CorpusCampaignV1.scope: ResourceScope`
(`services/rag-pedago/rag_pedago/governance/corpus_campaign.py:119`,
singulier) ; `generate_coverage_report --authority` ne prend qu'un fichier ;
`catalog_republish.republish_catalog` ne prend qu'un `authority_path` ;
`promote.yml` ne prend qu'un `campaign_id` ; le worker runtime
(`runtime_authority.py:41-70`) ne prend qu'un `collection_config_path`. Les
six composants, sur les deux services, sont cohérents entre eux —
mono-scope par design, pas une lacune isolée.

Piste minimale identifiée (non rédigée, non codée) : étendre
l'orchestration (pas le modèle `ResourceScope`/`ScopeAuthorizationArtifactV2`
lui-même) pour accepter plusieurs autorisations à scopes disjoints, et
redéfinir la complétude comme l'union de leurs `allowed_content_sha256` ==
le set global authority-required. Nécessiterait son propre ADR et sa
propre PR — **explicitement pas une résurrection d'ADR-0043** (quarantiné,
sujet sans rapport : migration H2 V1→V2, pas le multi-scope).

## 9. Production GitHub Environment (NOT_STARTED — non revérifié dans ce lot)

```
PRODUCTION_ENVIRONMENT_EXISTS=false
```
Plan mergé (PR#113) mais configuration réelle jamais provisionnée. HUMAN GATE
repo-admin séparé, avant le premier vrai run de `promote.yml`.

## 10. Statut consolidé

| Item | Statut | Preuve |
|---|---|---|
| Gouvernance PR#100→#126 (hors #96/#98) | **DONE** | §1 |
| Gate trusted-review fiable (Commit Status) | **DONE** | §2 |
| Governed republish — mécanisme | **DONE** | §3 |
| Governed republish — exécution réelle | **NOT_STARTED** | §3 |
| Currentness-verified promotion — mécanisme | **DONE** | §3 |
| Currentness-verified promotion — exécution réelle | **NOT_STARTED** | §3 |
| Atomic deploy — logique wrapper | **DONE (partiel)** | §3 |
| Atomic deploy — rehearsal Docker réel isolé | **NOT_STARTED** | §3 |
| Tier A — algèbre exacte + univers PII/droits | **DONE** | §5.1-5.3 |
| Tier A — audit byte-identity réseau réel | **DONE (bloqué Cloudflare, 0 promotion)** | §5.4 |
| Tier A — résolution complète (accès réseau non filtré requis) | **BLOCKED_HUMAN/INFRA** | §5.4 |
| Scope/profil — mapping réel sur le set actuel | **DONE (0 match, 72 NO_PROFILE)** | §8 |
| Architecture multi-scope — audit | **DONE** | §8.1 |
| Architecture multi-scope — changement de contrat | **NOT_STARTED — nécessite ADR + PR dédiée** | §8.1 |
| PR#96/#98 — audit | **DONE** | §6 |
| PR#96/#98 — décision + action | **BLOCKED_HUMAN** | §6 |
| Google Drive mirror | **DONE** | §7 |
| Production GitHub Environment | **NOT_STARTED — BLOCKED_HUMAN (repo-admin)** | §9 |
| `FINAL_ELIGIBLE_SHA_SET` figé | **NOT_STARTED** — reste 73/72 tant que Tier A n'est pas clos | §4, §5 |
| Stratégie d'autorisation exacte-content | **NOT_STARTED — bloqué sur le changement de contrat multi-scope** | §8.1 |
| Campagne réelle + republish réel | **NOT_STARTED** | §3 |
| `promote.yml` run réel | **NOT_STARTED** | dépend du freeze |
| `FINAL_RAG_MAIN_SHA` freeze | **NOT_STARTED** | dépend de tout ce qui précède |
| Signature offline | **NOT_STARTED — HUMAN GATE final** | |
| Cutover production | **NOT_STARTED — HUMAN GATE final** | |

## 11. Prochaine séquence recommandée

1. **Décision opérateur** : comment lever le blocage Cloudflare sur
   eduscol.education.gouv.fr (poste réseau non filtré, ou accepter les 138
   comme `REVIEW_REQUIRED` permanents pour cette release) — §5.4.
2. **ADR + PR dédiée** pour l'extension d'orchestration multi-scope — §8.1 —
   avant toute construction d'autorisation réelle sur le set de 72.
3. **Décision opérateur sur PR#96/#98** — §6.
4. Une fois 1-3 tranchés : construire la stratégie d'autorisation
   exacte-content sur le set final (jamais sur 63 ou 72 seuls si le
   multi-scope change le périmètre), créer la première vraie campagne,
   exécuter `republish-catalog` pour de vrai.
5. Rehearsal Docker réel isolé (atomic deploy), sans toucher la stack
   `infra` déjà en cours sur cet hôte.
6. Production GitHub Environment — HUMAN GATE repo-admin.
7. Freeze → provenance réelle → promotion réelle → signature offline →
   cutover.
