# Master Go-Live State — 2026-08-15

> Source de vérité unique, séquencée, pour la suite de la mission go-live RAG
> Nexus. Remplace la dispersion entre rapports de lots individuels pour les
> décisions de haut niveau. Chaque ligne porte sa preuve (SHA, chemin de
> fichier, ou commande vérifiée live) — aucune valeur n'est héritée d'un
> résumé sans revérification contre l'état réel de `main` ou des artefacts
> commités, sauf mention explicite contraire (voir §5, Google Drive).
>
> Version machine-readable jumelle : `master_go_live_state_20260815.json`.

`CURRENT_MAIN_SHA=a2a69dd472865c944b7cae463d4a50d1ee27bca0`

## 1. PR merges (DONE — revérifié live)

| PR | Sujet | Statut | Merge SHA | Merged at |
|---|---|---|---|---|
| #100 | Signing tool production readiness | DONE | `057e93c` | 2026-08-15T08:26:37Z |
| #107 | Atomic deployment wrapper (Lot C) | DONE | `439255f` | 2026-08-15T10:15:21Z |
| #108 | Evidence-index / terminal-disposition ledger | DONE | `5f44a46` | 2026-08-15T10:31:15Z |
| #109 | H2 workflow E2E rehearsal | DONE | `7117a41` | 2026-08-14T21:53:42Z |
| #110 | Canonical promotion workflow | DONE | `a8a41c7` | 2026-08-14T23:12:58Z |
| #111 | Catalog compiler schema fix | DONE | `fc4d80a` | 2026-08-15T09:12:10Z |
| #112 | Image-provenance fail-open fix | DONE | `c2c08dd` | 2026-08-15T10:45:43Z |
| #114 | Trusted-review check-SHA fix (check-run, superseded) | DONE | `0d98475` | 2026-08-15T09:32:43Z |
| #115 | H2 authority-promotion gap (Finding C) | DONE | `3308fcf` | 2026-08-15T09:52:50Z |
| #116 | Ratification post head-drift incident | DONE | `6867f98` | 2026-08-15T~13:20Z |
| #119 | Trusted-review status transport fix (Commit Status, supersedes #114's check-run) | DONE | `a2a69dd` | 2026-08-15T~15:35Z |

## 2. ADR status (DONE — revérifié dans `docs/adr/*.md`)

```
ADR0035_STATUS=Accepté (2026-08-13)
ADR0036_STATUS=Accepté (2026-08-13)
ADR0042_STATUS=Accepté (voir « Preuve d'acceptation »)
```

## 3. Gate d'intégrité gouvernance (DONE, cette session)

```
TRUSTED_REQUIRED_GATE_RELIABLY_ENFORCED=true
```
Preuve : `docs/reports/trusted_review_head_drift_incident_20260815.md` (cause
racine de l'incident #108/#112/#113), `docs/reports/trusted_review_branch_protection_rehearsal_20260815.md`
(rehearsal isolé prouvant la fiabilité du transport Commit Status), PR#119
(correctif mergé, live), protection de `main` relue : 7 required contexts,
`trusted-human-review/head-pinned` remplace l'ancien check-run non fiable.

## 4. Booleans techniques de préparation (DONE, extraits des rapports de lot)

```
PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=true
  (docs/reports/lot_h2b_production_readiness_signing_tool.md:725)

CATALOG_REAL_CORPUS_COMPILE_PASS=true
  = REAL_2583_ENTRY_CORPUS_COMPILE_REHEARSAL_PASSED=true
  (docs/reports/lot_fix_catalog_compiler_schema.md:189)

H2_WORKFLOW_E2E_REHEARSAL_PASS=true
  = V2_FULL_GOVERNED_REHEARSAL_PASS=true + V2_NEGATIVE_REHEARSAL_PASS=true
  (docs/reports/lot_h2b_production_readiness.md:227-228)

ATOMIC_DEPLOY_REHEARSAL_PASS=PARTIAL — voir note
  (docs/reports/lot_c_atomic_deployment_wrapper.md, item 9 « Rehearsal Docker
  réel, isolé ») : la logique du wrapper (matérialisation de bundle, dry-run,
  refus sur falsification) est prouvée avec de vrais fichiers Compose/`.env`
  factices et de vrais octets, MAIS `run_subprocess` reste un double même
  dans ce test — aucun `docker compose pull/up` réel n'a encore été exécuté.
  Un vrai déploiement Docker de bout en bout reste à faire (§7 Phase Release).
```

## 5. Corpus / éligibilité (DONE — revérifié depuis l'artefact canonique commité)

Source : `docs/reports/evidence-index/summary_20260814.json` (sur `main`,
`CURRENT_LEDGER_PRELIMINARY: false`)

```
PHYSICAL_FILES=2584
MANIFEST_ENTRIES=2583
UNIQUE_CONTENT_SHA256=2582
DUPLICATE_CONTENT_GROUPS=1

PII_PDF_UNION_COVERAGE=2475
RELEASE_ELIGIBLE_ARTIFACTS=63

content_final_disposition_counts:
  INGEST=63, QUARANTINE=2, REVIEW_REQUIRED=2408, EXCLUDE=53,
  ARCHIVE_ONLY=19, UNSUPPORTED=37
```

Rappel impératif (Section 10 de la directive du 2026-08-15) :
**ELIGIBLE != AUTHORIZED.**

```
RELEASE_ELIGIBLE_ARTIFACTS=63
AUTHORIZED_ELIGIBLE_ARTIFACTS=NOT_YET_COMPUTED
  — BLOCKED_TECHNICAL : PR#98 n'autorise que 5 contenus, ce n'est pas
  l'autorité finale. Une stratégie d'autorisation exacte-content (SHA par
  SHA, sans wildcard) couvrant les 63 doit encore être construite.
INGESTED_ELIGIBLE_ARTIFACTS=0 — NOT_STARTED (aucune ingestion réelle en
  production n'a encore eu lieu)
API_DISCOVERABLE_ELIGIBLE_ARTIFACTS=0 — NOT_STARTED (API production non
  déployée)
```

## 6. Governed republish (BLOCKED_TECHNICAL)

```
GOVERNED_REPUBLISH_STEP_EXISTS=false
```
`docs/reports/lot_h2_authority_promotion.md` : PR#115 apprend au gate H2 à
**reconnaître** une autorité valide couvrant un candidat bloqué, mais aucune
étape ne **matérialise/republie** le catalogue lui-même en dispositions
INGEST gouvernées. Non construit. **Blocker technique direct du go-live** —
doit être fait avant la construction des autorisations finales (§ suivante).

## 7. Google Drive (UNVERIFIED_THIS_SESSION — limite honnête)

Les artefacts de vérification de la session précédente
(`drive_provenance_snapshot_20260815.json`, `post_repair_listing.json`,
`final_check.log`) vivaient dans le scratchpad d'une session Claude Code
antérieure, isolé de celui-ci — inaccessibles depuis cette session. Dernier
état **connu** (résumé de session précédente, **non revérifié en direct
ici**) : `DRIVE_MIRROR_COMPLETE=true` (2584/2584 fichiers, 0 différence
`rclone check --one-way`).

```
DRIVE_MIRROR_COMPLETE=UNVERIFIED_THIS_SESSION (dernière valeur connue : true)
```

**Action requise avant le freeze final (§9)** : relancer un scan Drive live
et un `rclone check` frais pour requalifier cette ligne en `DONE` avec preuve
de cette session, plutôt que de citer l'ancienne comme actuelle.

## 8. Production GitHub Environment (NOT_STARTED — revérifié live)

```
PRODUCTION_ENVIRONMENT_EXISTS=false
  (gh api repos/cyranoaladin/RAG/environments -> total_count: 0, revérifié
  2026-08-15)
REQUIRED_REVIEWER_CONFIGURED=false
MAIN_ONLY_POLICY=false
SELF_REVIEW_PREVENTED=false
ADMIN_BYPASS_DISABLED=false
LONG_LIVED_SECRETS=UNKNOWN (aucun environment -> rien à auditer encore)
```
Plan existant et mergé (`docs/reports/plan_production_github_environment.md`,
PR#113) mais configuration réelle jamais provisionnée. Sera un **HUMAN GATE
repo-admin séparé** lorsque ce sera le prochain blocker réel — avant le
premier vrai run de `promote.yml`.

## 9. Statut consolidé

| Item | Statut | Preuve |
|---|---|---|
| Gouvernance PR#100/107/108/109/110/111/112/114/115/116/119 | **DONE** | §1 |
| Gate trusted-review fiable (Commit Status) | **DONE** | §3 |
| Signing tool / catalog compile / H2 E2E rehearsals | **DONE** | §4 |
| Atomic deploy — logique wrapper | **DONE (partiel)** | §4 — vrai `docker compose up` encore mocké |
| Governed republish (catalogue → INGEST matérialisé) | **BLOCKED_TECHNICAL** | §6 |
| Stratégie d'autorisation exacte-content (63 objets) | **BLOCKED_TECHNICAL** | §5 — PR#98 insuffisant |
| Currentness Tier A (1253 objets PII-cleared non scope-collection) | **NOT_STARTED** | task tracker interne |
| Google Drive mirror | **UNVERIFIED_THIS_SESSION** | §7 |
| Production GitHub Environment | **NOT_STARTED — BLOCKED_HUMAN (repo-admin)** | §8 |
| Vrai déploiement Docker end-to-end | **NOT_STARTED** | §4 |
| `production-image-provenance.yml` run réel | **NOT_STARTED** | dépend du freeze |
| `promote.yml` run réel | **NOT_STARTED** | dépend du freeze |
| `FINAL_RAG_MAIN_SHA` freeze | **NOT_STARTED** | dépend de tout ce qui précède |
| Signature offline (clé privée opérateur) | **NOT_STARTED — HUMAN GATE final** | Section 14 directive |
| Cutover production | **NOT_STARTED — HUMAN GATE final** | pas encore atteint |

## 10. Prochaine séquence recommandée

Dans l'ordre, chaque étape re-vérifiée avant de passer à la suivante :

1. **Governed republish** (§6) — construire l'étape qui matérialise réellement
   les 63 candidats vers INGEST une fois l'autorité reconnue, dans le respect
   de `AGENTS.md` (jamais d'écriture pgvector hors `quality → gate → review`).
2. **Stratégie d'autorisation exacte-content** (§5/§6 de la directive) —
   couvrir les 63 éligibles un par un, sans wildcard, chacun avec son
   evidence rights/PII/currentness et son review-binding.
3. **Re-vérification Drive live** (§7) — nouveau scan + `rclone check`, pour
   remplacer `UNVERIFIED_THIS_SESSION` par une preuve de cette session.
4. **Currentness Tier A** (1253 objets) si encore dans le périmètre du
   go-live minimal, sinon documenter explicitement pourquoi il est hors
   scope pour ce cutover.
5. **Production GitHub Environment** (§8) — HUMAN GATE repo-admin.
6. `FINAL_RAG_MAIN_SHA` freeze, puis Phase Release réelle (provenance,
   promotion, evidence, signature offline, cutover) selon Section 14 de la
   directive du 2026-08-15.
