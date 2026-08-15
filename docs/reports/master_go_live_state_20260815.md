# Master Go-Live State — snapshot du 2026-08-15 (soir)

> Source de vérité unique, séquencée, pour la suite de la mission go-live RAG
> Nexus. **Ceci est un instantané d'un état observé, pas une API live de la
> branche `main`** — un document committé ne peut jamais maintenir
> honnêtement un `current_main_sha` puisque son propre merge fait avancer
> `main`. Le SHA live doit toujours être relu depuis GitHub/Git ; les champs
> `state_observed_at_*` ci-dessous décrivent l'état au moment de la
> génération, jamais un pointeur vivant.
>
> Mise à jour de ce même document (version initiale mergée via PR#120, ce
> soir devenue obsolète après PR#121/#122) — pas un nouveau fichier daté
> parallèle. Chaque ligne porte sa preuve.

```
state_generated_at=2026-08-15T20:40:00Z
state_observed_at_main_sha=353703f96ee58345e9a46cd1c2fa7aed952a6e9f
state_observed_at_tree_sha=cc4e96f69d140750913ca8102cde5752f31401c7
```

> Ces deux SHA décrivent l'état observé **au moment de la génération**. Une
> fois cette PR mergée, `main` aura déjà avancé d'au moins ce merge lui-même
> — c'est attendu et normal pour un instantané, jamais un défaut à corriger
> en committant un troisième SHA auto-référent.

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
| #120 | Master go-live state (v1, superseded by this doc) | DONE | `4b2f611` | 2026-08-15T16:05:43Z |
| #121 | Governed catalog republish mechanism | DONE | `8ad8741` | 2026-08-15T17:18:23Z |
| #122 | Currentness-verified promotion | DONE | `353703f` | 2026-08-15T20:35:48Z |

PR#96 et PR#98 : voir §6 (audit dédié, ni mergées ni fermées).

## 2. Gate d'intégrité gouvernance (DONE)

```
TRUSTED_REQUIRED_GATE_RELIABLY_ENFORCED=true
required_context_final_name=trusted-human-review/head-pinned
```
Confirmé en conditions réelles sur PR#120/#121/#122 : approbation réelle →
Commit Status `success` → branch protection reconnaît nativement → merge
sans aucun rollback de protection. Preuve :
`docs/reports/trusted_review_head_drift_incident_20260815.md`,
`docs/reports/trusted_review_branch_protection_rehearsal_20260815.md`.

## 3. Booleans techniques de préparation (DONE)

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
`ATOMIC_DEPLOY_REHEARSAL_PASS` détail (audit du 2026-08-15, §5) : logique du
wrapper prouvée avec de vrais fichiers ; `run_subprocess` reste un double,
aucun `docker compose pull/up` réel exécuté. Gap précisément caractérisé :
mécanisme d'injection identifié (`deploy_verified_release_cli.py:290-294,419`),
fixture Compose sûre déjà disponible
(`services/rag-engine/infra/docker-compose.test.yml`, images publiques
légères). **Danger réel trouvé sur cet hôte** : une stack de développement
`infra` (rag_worker/rag_ui/rag_pgvector/rag_redis) tourne déjà en local —
tout rehearsal réel doit utiliser un nom de projet Compose isolé
(`COMPOSE_PROJECT_NAME` unique par run), jamais le défaut dérivé du
répertoire. Une stack orpheline non trackée (`rag-smoke-ci3`) existe aussi
sur cet hôte — signalée, non touchée.

## 4. Corpus / éligibilité (DONE — revérifié depuis l'artefact canonique commité)

Source : `docs/reports/evidence-index/summary_20260814.json` (inchangée par
les lots de ce jour — ceux-ci ont construit des *mécanismes*, aucun n'a
encore été exécuté pour de vrai contre le corpus réel).

```
PHYSICAL_FILES=2584
MANIFEST_ENTRIES=2583
UNIQUE_CONTENT_SHA256=2582
DUPLICATE_CONTENT_GROUPS=1

CURRENT_RELEASE_ELIGIBLE_ARTIFACTS=63
FINAL_RELEASE_ELIGIBLE_ARTIFACTS=UNKNOWN   # tant que Tier A n'est pas clos pour cette release
```

**Rappel impératif** (le nombre 63 n'est PAS le set final) :
Le travail currentness/rights Tier A (§5) peut transformer des contenus
`REVIEW_REQUIRED` en réellement éligibles. Toute stratégie d'autorisation
construite sur 63 devrait être reconstruite si Tier A change ce nombre.
`AUTHORIZED_ELIGIBLE_ARTIFACTS`/`INGESTED_ELIGIBLE_ARTIFACTS`/
`API_DISCOVERABLE_ELIGIBLE_ARTIFACTS` restent tous `0` — aucune autorisation
finale, aucune campagne réelle, aucune ingestion n'a eu lieu.

## 5. Tier A / currentness — investigation réelle (2026-08-15)

```
TIER_A_REAL_POPULATION=1252   # PII-cleared + unclassified + zéro couverture registre (pas "1253" -- non reproductible tel quel)
TIER_A_A_VERIFIER_POPULATION=805   # bucket séparé, zéro couverture registre
ROUTING_CONFIG_GAP_FOUND=false   # comme correctif en masse -- les chemins "unclassified" encodent un TYPE de document, jamais un statut de currentness
REASONABLY_RESOLVABLE_NOW=10-11   # items déjà preuve-résolus (actuel + droits + PII clairs) -- CORRIGÉ par PR#122, mécanisme prêt
GENUINELY_NEEDS_MANUAL_REVIEW=805+38   # a_verifier sans couverture registre + programme/sujet-alignment
NOT_YET_INVESTIGATED=true   # extension de la méthode d'audit réseau (byte-identity) aux ~14 combinaisons niveau/matière non couvertes -- nécessite des requêtes réseau live, non tentées (passe en lecture seule)
RIGHTS_AS_BLOCKER=false   # confirmé : 2405/2408 REVIEW_REQUIRED déjà CLEARED_BY_HUMAN_DECISION
```
Détail complet : investigation fork du 2026-08-15 (non versionnée séparément
— synthèse ci-dessus et dans `docs/reports/lot_currentness_verified_promotion.md`).

**Prochaine étape concrète** : exécuter `h2b_coverage_report.py
--currentness-verification` / `catalog_republish.py` avec
`multilevel_currentness_evidence.yml` pour de vrai contre le catalogue
candidat réel, pour mesurer le nombre exact promu (10-11 attendus, jamais
supposé).

## 6. PR#96 / PR#98 — audit (DONE, décision réservée à l'opérateur)

```
PR96_ACTION=KEEP_OPEN   # grant révocable toujours-ouvert par conception -- son propre corps de PR interdit le merge ("DO NOT APPROVE", "must never be merged"). Fermer = révoquer, une décision substantielle, pas un nettoyage.
PR98_ACTION=REUSE_AS_SUBSET   # techniquement valide (manifeste exact, 5/5 SHA toujours dans les 63 INGEST, non expiré), mais documenté ailleurs comme insuffisant seul.
PR96_PR98_OVERLAP=none   # authorization_id distincts, aucune collision ; PR#98 cite l'évidence PII corrigée, PR#96 une évidence superseded.
```
Aucune action prise — décision opérateur requise avant construction des
autorisations finales.

## 7. Google Drive (DONE — revérifié en direct cette session)

```
DRIVE_MIRROR_COMPLETE=true
DRIVE_CURRENT_CONTENT_FILES=2584
DRIVE_MANIFEST_ENTRIES_MATCHED=2583
DRIVE_EXTRA_UNACCOUNTED=1   # le fichier manifeste lui-même, jamais une entrée de contenu de lui-même -- attendu
DRIVE_CANONICAL_FILES_MISSING=0
DRIVE_SHA_MISMATCH=0
```
Preuve : `rclone check` one-way, rate-limited, contre
`gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY` (remote canonique confirmé via
`prepare_nexus_rag_gdrive.py`, jamais `gdrive_clean`) — verdict rclone natif :
*"0 differences found... 2584 matching files"*.

```
drive_snapshot_id=drive-snapshot-20260815T180436Z
drive_snapshot_mapping_sha256=75ac6bd288882939d2bb8fcad758730238037c5266913166fcbc61c3be47cdc8
drive_snapshot_metadata_sha256=15d517a49517d94a9dcccfbc6767815afc0b09b933dd2022eb8830dcd09fb7fb
```
Artefacts :
`docs/reports/evidence-index/drive-snapshot/drive_snapshot_mapping_20260815.json`
(content_sha256 + canonical_path — toujours depuis le manifeste scellé local
— joint à fileId/mimeType/size/modifiedTime Drive ; le fileId reste
provenance, jamais identité) et
`drive_snapshot_metadata_20260815.json`.

## 8. Production GitHub Environment (NOT_STARTED — revérifié live)

```
PRODUCTION_ENVIRONMENT_EXISTS=false
```
Plan mergé (PR#113) mais configuration réelle jamais provisionnée. HUMAN GATE
repo-admin séparé, avant le premier vrai run de `promote.yml`.

## 9. Statut consolidé

| Item | Statut | Preuve |
|---|---|---|
| Gouvernance PR#100→#122 (hors #96/#98) | **DONE** | §1 |
| Gate trusted-review fiable (Commit Status) | **DONE** | §2 |
| Governed republish — mécanisme | **DONE** | §3 |
| Governed republish — exécution réelle | **NOT_STARTED** | §3 |
| Currentness-verified promotion — mécanisme | **DONE** | §3, §5 |
| Currentness-verified promotion — exécution réelle | **NOT_STARTED** | §3, §5 |
| Atomic deploy — logique wrapper | **DONE (partiel)** | §3 |
| Atomic deploy — rehearsal Docker réel isolé | **NOT_STARTED** | §3 |
| Tier A — investigation | **DONE** | §5 |
| Tier A — résolution complète | **NOT_STARTED** | §5 |
| PR#96/#98 — audit | **DONE** | §6 |
| PR#96/#98 — décision + action | **BLOCKED_HUMAN** | §6 |
| Google Drive mirror | **DONE** | §7 |
| Production GitHub Environment | **NOT_STARTED — BLOCKED_HUMAN (repo-admin)** | §8 |
| `FINAL_ELIGIBLE_SHA_SET` figé | **NOT_STARTED** | §4, §5 |
| Stratégie d'autorisation exacte-content | **NOT_STARTED — bloqué sur `FINAL_ELIGIBLE_SHA_SET`** | §4 |
| Campagne réelle + republish réel | **NOT_STARTED** | §3 |
| `production-image-provenance.yml` run réel | **NOT_STARTED** | dépend du freeze |
| `promote.yml` run réel | **NOT_STARTED** | dépend du freeze |
| `FINAL_RAG_MAIN_SHA` freeze | **NOT_STARTED** | dépend de tout ce qui précède |
| Signature offline | **NOT_STARTED — HUMAN GATE final** | |
| Cutover production | **NOT_STARTED — HUMAN GATE final** | |

## 10. Prochaine séquence recommandée (ordre imposé par la directive du 2026-08-15)

1. **Exécuter les deux mécanismes pour de vrai** contre le catalogue candidat
   réel : currentness-verified promotion d'abord (peut faire grandir le set
   éligible), puis mesurer `FINAL_RELEASE_ELIGIBLE_ARTIFACTS` réel.
2. **Clore Tier A pour cette release** — investiguer/résoudre ce qui est
   raisonnablement résoluble (extension de l'audit byte-identity réseau),
   documenter le reste `REVIEW_REQUIRED_AFTER_INVESTIGATION` vs
   `REVIEW_REQUIRED_NOT_YET_INVESTIGATED`.
3. **Figer `FINAL_ELIGIBLE_SHA_SET`** (digest du set trié).
4. **Décision opérateur sur PR#96/#98**, puis construire la stratégie
   d'autorisation exacte-content sur le set final (jamais sur 63 seul).
5. **Créer la première vraie campagne** + exécuter `republish-catalog` pour
   de vrai.
6. **Rehearsal Docker réel isolé** (atomic deploy), sans toucher la stack
   `infra` déjà en cours sur cet hôte.
7. **Production GitHub Environment** — HUMAN GATE repo-admin.
8. Freeze → provenance réelle → promotion réelle → signature offline →
   cutover.
