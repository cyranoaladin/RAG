# Lot — freeze corpus et protocole multi-autorisation V2

## 1. Statut et périmètre

Ce lot part exactement de la baseline `main` après PR #127 :

```text
BASE_SHA=3548bf300c99685ff6ede0dce2e5bfe8c044d213
ADR=ADR-0044
CONTRACT_VERSION=0.13.0
CI_GREEN=false
```

`CI_GREEN=false` reste intentionnel après la vérification locale Task10 : ce
champ décrit les checks de la future PR, pas un raccourci calculé depuis les
commandes locales. Il ne pourra passer à `true` qu'après exécution réussie des
checks distants sur le HEAD immuable de la PR. Le document ne prédit ni HEAD
final, ni TREE final, ni numéro de PR, ni challenge de revue.

Le lot ferme le périmètre corpus de cette release, remplace l'audit
mono-autorité trop étroit, et implémente les primitives V2 nécessaires. Il ne
crée aucune vraie autorisation et n'exécute ni campagne, ni republish, ni H2 de
production.

## 2. Recalcul reproductible — jamais une substitution 63 → 72

La source du résultat est
`services/rag-pedago/scripts/recompute_final_release_set.py`. Elle recompose le
catalogue et les gates PII, droits, routing, currentness, manifest et golden,
sans autorité. Depuis `services/rag-pedago`, la reproduction exacte est :

```bash
release_output="$(mktemp -d)"
NEXUS_SEALED_CORPUS_ROOT="<miroir-scelle>" \
NEXUS_H2_EVIDENCE_ROOT="<preuves-h2>" \
PYTHONPATH=rag_pedago:../../packages/contracts/src \
python scripts/recompute_final_release_set.py \
  --output-dir "$release_output"
cmp --silent \
  "$release_output/final_authority_required_set.txt" \
  ../../docs/reports/final_authority_required_set_20260823.txt
sha256sum "$release_output/final_authority_required_set.txt"
```

Les racines sont fournies par `NEXUS_SEALED_CORPUS_ROOT` et
`NEXUS_H2_EVIDENCE_ROOT` ; aucun chemin machine-local n'est versionné dans la
commande canonique.

Les huit entrées réellement utilisées lors du recalcul ont été figées par
digest :

- manifeste scellé `SHA256SUMS.txt` :
  `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` ;
- placements `eduscol_affectations.tsv` :
  `25cf40cec8a98692d4532a71b58a9685821bbc2b9a4785c25fac7138a49906ec` ;
- scan PII exhaustif :
  `0229a0f2d7edbd1bb1b1412a8ccd447b3c6d2ce71dc73a0f2e726751156fa357` ;
- scan PII campagne :
  `76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311` ;
- routing :
  `0d4d25215cb0ed40c439ff172c9dbce3f2a1b0b945313a042285b2e57bffc833` ;
- droits :
  `e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff` ;
- golden :
  `28856e0655eca7695f273a5934925785c49ecf828d930804984f6e58f4da6f69` ;
- currentness :
  `2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122`.

Résultat :

```text
FINAL_BASE_INGEST_CANDIDATES=73
FINAL_NON_AUTHORITY_BLOCKED_COUNT=1
FINAL_AUTHORITY_REQUIRED_COUNT=72
FINAL_AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
FINAL_RELEASE_ELIGIBLE_ARTIFACTS=72
FINAL_ELIGIBLE_SET_FROZEN=true
```

Le fichier final contient 72 lignes LF, triées, uniques et conformes au format
SHA-256 minuscule. Le test du lot recalcule aussi son digest et compare ses
octets ; le test d'intégration `test_recompute_final_release_set_from_real_inputs`
réexécute le producteur et effectue le `cmp` logique lorsque les preuves
externes scellées sont montées.

Le 2026-08-24 à `06:54:04Z`, ces preuves ont été montées et le producteur a été
réexécuté sans skip. Les huit digests ci-dessus ont été revérifiés, puis le set
produit a été comparé octet par octet au set commité. L'artefact nettoyé
`docs/reports/final_release_recomputation_evidence_20260824.json` a pour digest
`f68f5c525c7bd9280e03a1bbc5fd4a434de1b1d64e8a0a4eff8e32a3caa4f47d` et
publie :

```text
PRODUCER_EXIT_CODE=0
COMMITTED_SET_BYTE_IDENTITY=true
GENERATED_SUMMARY_SHA256=ff0d8a156e82717fdea3b18b9c26083b6c96361c680301bcaca8036e6034b4b5
OUTPUT_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
TERMINAL_DISPOSITIONS_SHA256=127231629e94260170c69c841b29278bf4b74b56a276097e885c574853464a10
```

Les chemins machine ont été remplacés par des libellés logiques. Le résultat
contient aussi le conflit canonique unique (`050b1815…`, `EXCLUDE` contre
`REVIEW_REQUIRED`) résolu fail-closed en `REVIEW_REQUIRED` pour la release.

## 3. Dispositions terminales

La comptabilité est effectuée par identité de contenu unique, pas par nombre
de fichiers physiques :

```text
UNIQUE_CONTENTS=2582
INGEST_CANDIDATE=72
REVIEW_REQUIRED=2399
QUARANTINE=2
ARCHIVE_ONLY=19
EXCLUDE=53
UNSUPPORTED=37
UNACCOUNTED_CONTENTS=0
TERMINAL_DISPOSITION_COVERAGE=100%
```

Les six classes totalisent exactement 2 582. Une disposition terminale ne
signifie pas ingestion : seuls les 72 `INGEST_CANDIDATE` sont dans le set
authority-required final.

Les 138 contenus investigués derrière Cloudflare restent dans leur état
canonique `A_VERIFIER` / `REVIEW_REQUIRED`. Aucun n'est supposé `CURRENT`,
`INGEST`, `ARCHIVE` ou `EXCLUDE`.

```text
CLOUDFLARE_OPERATOR_DECISION=ACCEPT_REVIEW_REQUIRED_FOR_THIS_RELEASE
NETWORK_WORK_CLOSED_FOR_RELEASE=true
CLOUDFLARE_BLOCKS_GO_LIVE=false
```

## 4. Profils : proposition ancrée, pas de données inventées

L'artefact
`docs/reports/proposed_production_profile_matrix_20260823.json` a pour SHA-256
`8009596c0cce54f816a1a1307a9ba5663146cfa2d7d95e381e84819d3be9c963`.

```text
PARTITION_COUNT=24
DISTINCT_LEVEL_SUBJECT_PAIRS_MINIMUM=22
MATRIX_RAW_DISTINCT_LEVEL_SUBJECT_PAIRS=23
MATRIX_FULLY_SPECIFIED_LEVEL_SUBJECT_PAIRS=21
GROUNDED_PARTITION_COUNT=10
GROUNDED_CONTENT_COUNT=11
DECISION_REQUIRED_PARTITION_COUNT=14
DECISION_REQUIRED_CONTENT_COUNT=61
PROFILE_EXACT_MATCH_COUNT=0
PROFILE_NO_MATCH_COUNT=72
PROFILE_AMBIGUOUS_COUNT=0
DISTINCT_CANONICAL_RESOURCE_SCOPES=UNKNOWN_PENDING_PROFILE_DECISIONS
PROFILE_DECISION_REQUIRED=true
FABRICATED_PROFILE_COUNT=0
```

Chaque dimension indique valeur, source de vérité et ancrage. Les 61 contenus
non ancrables attendent une vraie décision produit ; la branche ne fabrique
aucun profil afin de masquer ce gate. La borne opérateur `>=22` n'est pas
réécrite comme une égalité : les valeurs de dimension de la matrice donnent 23
couples bruts, dont 21 entièrement spécifiés.

## 5. Audit et architecture

L'audit adversarial de 45 surfaces réfute le constat historique selon lequel
seul le digest readiness singulier bloquait. Les singularités existent aussi
dans H2 V1, sa map de digests, campaign V1, le report/producteur, republish,
workflows, bundle, signer, deploy et startup/runtime.

ADR-0044 choisit :

- les autorisations `ScopeAuthorizationArtifactV2` et review bindings
  individuels inchangés ;
- `AuthorizationSetV1` (`NEXUS-AUTHORIZATION-SET-V1`) comme source globale
  canonique ;
- `CorpusCampaignV2`, `H2CoverageEvidenceV2`, `H2EvidenceBundleV2`, promotion
  V2 et `ProductionReadinessManifestV2` liés au digest du set ;
- union exacte, zéro extra/gap/overlap, vérification individuelle des revues,
  fenêtres et révocations ;
- placement release prouvé depuis l'arbre Git exact ;
- checkpoints runtime singuliers avant fetch et après fetch.

Les V1 restent strictes, lisibles et identiques ; V2 n'est jamais parsé comme
V1. ADR-0043 reste
`UNREVIEWED_WIP`, `NON_AUTHORITATIVE`, `NOT_REUSED`.

## 6. Commits d'implémentation audités avant intégration finale

- `7f0fbb4c0b2151034a48c0921a9f867a11d4fa57` — fixtures golden V1 ;
- `73890c7777d9c59a3747787bc50be88c4fd46c7e` — ADR, audit, recalcul et matrice ;
- `e165eb5c78bd4bbf9648a7d55905123f37f0142d` — AuthorizationSet canonique ;
- `268e9dfd964c229fc76c1f69f428a81063acfe28` — placement depuis l'arbre Git exact ;
- `54a0507533f8dc2b171bc0f52855655c79f77b66` — protocoles H2/readiness V2 ;
- `ea80579236d235b7d4c8f19b16c4430cb3ef0cb0` — campagne et couverture multi-auth ;
- `c44c53ee300b99cae3e38e998dc599e00e79cd99` — republish et mapping ;
- `d14e1e03c5bdb2b12c2dcb3b4016fb17f6043583` — bundle H2, promotion et workflows ;
- `37aa68ca51e52a9c1a96a72a97b5673c4f20e770` — signer/deploy readiness V2 ;
- `7ec6132dc9c2196889b55bef71faa6f1ea590f7d` — startup/runtime et Compose.

Chaque lot a suivi RED → GREEN et revue de conformité/qualité avant le lot
suivant. La matrice locale Task10 est consignée au §8 ; elle n'est pas
présentée comme une CI distante verte.

La remédiation de revue finale ferme aussi la dernière fenêtre V2 du wrapper
de déploiement : `PRODUCTION_V2_RELEASE_MATERIAL_HOST_DIR` est désormais
remplacé, comme le set, par une génération privée durable. Son inventaire
runtime est une allowlist exacte, sans `.env` ni Compose ; chaque fichier et
chaque inode sont revalidés avant `pull`, après `pull` avant `up`, puis après
`up`. Les tests adversariaux refusent substitution de génération, fichier
modifié, fichier supplémentaire et injection de ligne dotenv avant la
mutation Docker suivante.

## 7. Vérité des chantiers go-live parallèles

Le transcript du rehearsal Docker initial n'est pas disponible sous une forme
versionnée et auditable. Les valeurs résumées par l'opérateur restent une
observation historique non vérifiée ; elles ne sont pas élevées au rang de
preuve. Le blocker technique exact est irrécupérable depuis ce transcript.

```text
DOCKER_REHEARSAL_EVIDENCE_STATUS=UNVERIFIED_TRANSCRIPT_NOT_VERSIONED
ATOMIC_DOCKER_REHEARSAL_PASS=UNKNOWN
ROLLBACK_REHEARSAL_PASS=UNKNOWN
FOREIGN_SERVICES_TOUCHED=UNKNOWN
BAD_DIGEST_REFUSED=UNKNOWN
BAD_READINESS_REFUSED=UNKNOWN
EXACT_TECHNICAL_BLOCKER=UNKNOWN_TRANSCRIPT_UNAVAILABLE
```

Le résumé opérateur de l'audit DB mentionnait un refus SSH sur clé d'hôte
inconnue et zéro écriture, sans transcript versionné. Il est conservé comme
observation historique non vérifiée. La base locale n'est pas prise pour la
cible production :

```text
DB_AUDIT_EVIDENCE_STATUS=UNVERIFIED_TRANSCRIPT_NOT_VERSIONED
PROD_DB_TARGET_VERIFIED=UNKNOWN
PROD_DB_MIGRATION_PLAN_READY=UNKNOWN
PROD_DB_WRITES=UNKNOWN
```

L'Environment GitHub `production` est absent et n'a pas été provisionné. Le
plan exact exige reviewer `abenrhouma` (user id `67140603`), `main` seulement,
`prevent_self_review=true`, `admin_bypass=false`, wait timer 0 et secrets 0.
Une lecture API sans mutation, effectuée à `2026-08-24T06:53:53Z`, est
consignée dans
`docs/reports/github_environment_read_only_observation_20260824.json` : zéro
Environment, reviewer avec permission `write`, aucune donnée sensible. Digest
de l'observation :
`8880808bf1b46032e69141793d34815f4db836692a2e3f44d8f280db9f020d8a`.

`DRIVE_MIRROR_COMPLETE=true` provient des preuves déjà acceptées ; le mirror
n'a pas été rescanné dans ce lot.

## 8. Vérification Task10, dettes reproduites et CI

Le cycle RED de Task9 avait produit `6 failed, 1 passed`, puis le cycle GREEN
avec les entrées scellées montées a produit `16 passed`, aucun skip. Les deux
limites provisoires de Task9 sont maintenant remplacées par la vérification
fraîche :

```text
MAKE_INTERPRETER_PYYAML_ENV_FAILURE=SUPERSEDED_BY_TASK10
KNOWN_UNTOUCHED_MYPY_ERRORS=SUPERSEDED_BY_TASK10
```

### 8.1 `packages/contracts`

```text
PYTEST=PASS (465 passed)
RUFF=PASS
MYPY_SRC=FAIL_PREEXISTING_BASELINE
```

Le seul échec mypy est
`src/nexus_contracts/review_binding.py:315` : argument `str` incompatible avec
`Literal['ed25519']`. La même erreur a été reproduite sur la baseline
`3548bf300c99685ff6ede0dce2e5bfe8c044d213` ; elle n'est pas introduite par
ce lot.

### 8.2 `services/rag-pedago`

```text
LINT=PASS
MYPY=PASS (95 source files)
PYTEST=PASS (2767 passed, 2 skipped)
```

### 8.3 `services/rag-engine`

```text
LINT=PASS
MYPY=PASS (121 source files)
PYTEST_NON_INTEGRATION_COMPLETE=PASS
MAKE_SMOKE=FAIL_PREEXISTING_BASELINE
```

`make smoke` échoue avant le smoke applicatif avec les deux diagnostics
`service web has neither image nor build context` et
`docker compose config --services returned no services`. Les mêmes erreurs ont
été reproduites sur la baseline `3548bf3` ; elles ne proviennent pas du diff
multi-autorisation.

### 8.4 Cockpit et CI locale racine

Le cockpit est entièrement vert : lint PASS, `179 tests` PASS, build PASS et
audit dépendances `0`. Toutes les autres gates repository passent.

La CI locale complète a utilisé Python `3.12.3` et Node `22.22.0` :

```text
CI_LOCAL=15 PASS / 1 FAIL
UNIQUE_FAILURE=rag-engine dependency installation
FAILURE_PHASE=pip install, before tests
FAILURE=OSError [Errno 28] No space left on device
```

Cet échec est une saturation disque de l'environnement de vérification, pas un
résultat de test. Les environnements virtuels générés dans le worktree ont été
supprimés après la campagne ; aucune donnée de ces venvs n'est versionnée.

Commandes Task9 :

```bash
cd services/rag-pedago
PYTHONPATH=rag_pedago:../../packages/contracts/src \
  pytest -q tests/test_multi_authorization_release_report.py \
  tests/test_recompute_final_release_set.py
cd ../..
python -m json.tool docs/reports/master_go_live_state_20260815.json >/dev/null
bash scripts/check-governance-locks.sh
git diff --check
```

Le test réel Task9 réexécute le producteur, revérifie les huit digests et
compare les octets du set. Le test hermétique redérive le set, les dispositions,
Cloudflare et la matrice depuis quatre artefacts versionnés indépendants.

Malgré la matrice locale ci-dessus, `CI_GREEN` reste `false` tant que les checks
de la PR n'ont pas exécuté et accepté le HEAD final :

La revue adversariale finale a identifié puis fait corriger trois bloqueurs P1
avant publication : absence de voie CLI pour le republish V2, absence de
liaison entre la preuve locale et l'artefact exact du run de promotion, et
possibilité de créer une nouvelle signature après avancement de `main`. Les
régressions ajoutées exigent désormais une CLI V2 sans flags singuliers,
l'unicité/non-expiration/identité byte-for-byte de l'artefact de promotion, et
une relecture live de `main` au dernier instant avant accès à la clé. Deux
secondes revues indépendantes du nouveau HEAD ont conclu `APPROVE`, sans
finding P0-P2, avant ouverture de la PR.

Le premier run GitHub de la PR a ensuite révélé un défaut de bootstrap du job
cockpit : le package public importe désormais la composition multi-auth, donc
le check de génération de schémas a besoin de la dépendance `cryptography`
déclarée par `nexus-contracts`. Le workflow installait encore une liste
parallèle réduite à PyYAML/Pydantic. Le correctif installe le package éditable
et ses dépendances déclarées ; le garde-fou structurel du workflow est passé de
RED (`50 passed, 1 failed`) à GREEN (`51 passed, 0 failed`).

```text
CI_GREEN=false
PRODUCTION_READY=false
GO_LIVE_READY=false
RAG_PRODUCTION_DEPLOYED=false
REAL_AUTHORIZATIONS_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
REAL_GOVERNED_REPUBLISH_EXECUTED=false
REAL_H2_GATE_PASS=false
```
