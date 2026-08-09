# Rapport de lot — H2-B préparation corpus et production

## Verdict courant

Ce rapport remplace les affirmations H2-B non committées et non démontrées du
8 août 2026. Il repose sur le manifest et le catalogue réellement téléchargés
depuis la source Drive scellée, en lecture seule.

`H2_B_IMPLEMENTATION_COMPLETE=false`

`H2_B_TECHNICAL_GATE=BLOCKED`

`GO_LIVE_READY=false`

`GO_LIVE_COMPLETED=false`

`NEXT_ACTION=GO_LIVE_REMEDIATION`

Le pipeline s'arrête avant audit, merge et déploiement : l'autorité LOT41A
réelle est absente et le runtime de retrieval ne sait pas encore représenter
un artefact avec plusieurs placements sans dupliquer ses chunks. Ces deux
constats sont des gates obligatoires, pas des dettes non bloquantes.

## Préflight observé

- `START_HEAD=9e70225b33a12bf54f05fbd8b69aa4d5e43b70b0` ;
- `START_BRANCH=track-a/lot-h2b-corpus-production-readiness` ;
- `WORKTREE_CLEAN=false` : le registre de droits modifié et le rapport non
  suivi ont été inspectés et conservés avant correction ;
- `MAIN_SHA=a956441645d48107ab983fad62b80f0848345e81` ;
- `ORIGIN_MAIN_SHA=a956441645d48107ab983fad62b80f0848345e81` ;
- `PR95_HEAD=9e70225b33a12bf54f05fbd8b69aa4d5e43b70b0` au préflight ;
- `PR95_IS_DRAFT=true` ;
- checks techniques GitHub du head initial : verts ; check de revue de confiance
  rouge uniquement parce que la PR était draft et sans approbation exigée.

## Décisions humaines de droits

La consigne explicite de Nexus Réussite est enregistrée comme décision
organisationnelle humaine, jamais comme avis juridique externe ni signature
cryptographique :

- `EDUSCOL_RIGHTS_HUMAN_REVIEW=APPROVED` ;
- `EDUSCOL_RIGHTS_HUMAN_DECISION_SOURCE=NEXUS_REUSSITE` ;
- `EDUSCOL_GENERIC_RIGHTS_BLOCKER=false` ;
- scope : `01_EDUSCOL_OFFICIEL/` ;
- manifest :
  `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` ;
- une restriction explicite propre à un document reste fail-closed et ne
  bloque que cet artefact ;
- les deux documents DEPP restent `REVIEW_REQUIRED` ;
- les 39 contenus Nexus sont liés à l'ensemble exact de leurs SHA par le
  digest `877591ddc3a1be85da2c09b61bd4e161020bb0a7cb135ad33c68b5c27de0eb38`,
  sans signature fabriquée.

## Réconciliation du corpus réel

| Mesure | Valeur réelle |
|---|---:|
| Objets distants | 2 584 |
| Entrées de `SHA256SUMS.txt` | 2 583 |
| SHA-256 du manifest | `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` |
| Objets physiques, manifest self inclus | 2 584 |
| Identités de contenu | 2 583 |
| Artefacts Eduscol uniques | 2 451 |
| Placements Eduscol | 2 956 |
| Placements classifiés | 2 109 |
| Placements non classifiés | 847 |
| Artefacts multi-placement | 433 |

`00_ADMIN/SHA256SUMS.txt` est représenté séparément comme
`EXCLUDE/MANIFEST_SELF_OBJECT` ; le manifest scellé n'a pas été modifié.

### Formats physiques

| Format | Nombre |
|---|---:|
| PDF | 2 476 |
| GGB | 37 |
| TSV | 29 |
| YAML | 18 |
| JSON | 9 |
| TXT | 4 |
| MD | 4 |
| ZIP | 3 |
| SHA256 | 3 |
| CSV | 1 |
| OTHER | 0 |
| **Total** | **2 584** |

## Scan PII réel

La tentative intégrale a rencontré le quota Google Drive
`403 rateLimitExceeded`. Elle a échoué fermée, n'a écrit aucune preuve finale
et son scratch a été nettoyé. Conformément au repli explicitement autorisé, le
scan final couvre tous les 64 PDF susceptibles de finir `INGEST` dans la
promotion initiale ; les 2 412 autres PDF sont `EXEMPT`, jamais déclarés
scannés.

Le téléchargement Drive est resté en lecture seule. Chaque SHA a été vérifié
avant extraction, le contenu identique n'a été scanné qu'une fois, l'extraction
est native et la sortie est aseptisée. Aucun OCR de masse n'a été utilisé.

| Mesure PII | Valeur |
|---|---:|
| PDF total corpus | 2 476 |
| Scope | `INITIAL_PRODUCTION_ELIGIBLE_PDFS` |
| Requis | 64 |
| Exempt | 2 412 |
| Scannés | 64 |
| Cleared | 63 |
| Review required | 0 |
| Quarantined | 1 |
| Extraction failed | 0 |
| Non scannés dans le scope requis | 0 |
| Couverture du scope requis | 100 % |
| Mismatches SHA | 0 |

L'unique signal `postal_address` place le SHA
`b81201b857c67e4e928a079cfe9d5b9b402537d0101bfccc730465631d5e8376`
en `QUARANTINE`. Aucun texte détecté n'est consigné.

- preuve PII :
  `76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311` ;
- manifest externe de preuve :
  `641ad5b10e21c9b18a79e63feb7cf380cf1aa8b06026f50fd79ab997c30cd95e` ;
- `RAW_PII_IN_OUTPUT=false` ;
- `RAW_PII_IN_LOGS=false` ;
- `REMOTE_WRITE_OPERATIONS=0`.

## Compilation gouvernée finale au gate courant

La preuve droits et le scan PII sont joints au vrai manifest. L'autorité réelle
reste absente, donc aucun candidat ne devient `INGEST`.

| Disposition | Nombre |
|---|---:|
| INGEST | 0 |
| REVIEW_REQUIRED | 2 471 |
| QUARANTINE | 2 |
| ARCHIVE_ONLY | 19 |
| EXCLUDE | 55 |
| UNSUPPORTED | 37 |
| **Somme** | **2 584** |

`UNCLASSIFIED=0`

`MULTIPLE_PRIMARY_DISPOSITION=0`

`BLOCKED_INGEST_CANDIDATES=64`

`BLOCKED_GATE_AUTHORITY=64`

`BLOCKED_GATE_PII=1`

Le catalogue réel temporaire est scellé par
`52d63a0ccf16bd2a0ed42fb62f468ef9c817bf3b7242ce9594200a24d1e34c54`.
Il n'est pas committé car il contient des chemins machine temporaires dans ses
métadonnées de compilation ; les entrées sources, compteurs et digests restent
reproductibles depuis les preuves nommées ci-dessus.

## Autorité LOT41A/LOT42

Les 83 tests d'intégration du mécanisme LOT41A/LOT42 passent sur PostgreSQL
isolé : octets exacts, contenu, manifest, artefacts de gouvernance, expiration,
révocation et mauvais scope refusent correctement les dérives.

Cela ne constitue pas une autorisation réelle. Le dépôt ne contient aucun
`governance/authorizations/<authorization_id>.json` approuvé pour ce corpus et
les ADR-0032/0033 restent `Proposé — non Accepté`. Ils exigent une review GitHub
humaine `APPROVED` du Code Owner sur le HEAD exact. La consigne organisationnelle
de Nexus Réussite ne peut pas être transformée par l'agent en cette review.

Le compilateur a donc été durci : droits et PII verts ne suffisent plus ; sans
autorité réelle, le candidat reste `REVIEW_REQUIRED`.

`EXTERNAL_AUTHORITY_MECHANISM_TESTS=83/83`

`REAL_SCOPE_AUTHORIZATION_PRESENT=false`

`AUTHORITY_CLEARED_OBJECTS=0`

## Retrieval et multi-placement

La répétition PostgreSQL/pgvector éphémère passe : migrations et rollbacks
atomiques, rôles minimaux, schéma, retrieval hybride, identité signée et
isolation des scopes existants sont verts.

`EPHEMERAL_PGVECTOR_REHEARSAL=PASS`

`LOT40_HYBRID_INTEGRATION=PASS`

Le schéma de production `rag_chunks` porte un seul niveau, une seule matière et
une seule collection par ligne. Il ne contient ni relation de placements 1:N,
ni métadonnée équivalente. Le compilateur de contrôle conserve bien les 2 956
placements, mais `rag-engine` ne peut pas encore les consommer sans dupliquer
les lignes de chunks. Le test réel demandé sur le SHA multi-placement
`371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d`
ne peut donc pas passer sur le chemin runtime actuel.

`CORPUS_COMPILER_USES_ARTIFACT_PLACEMENT_MODEL=true`

`COVERAGE_REPORT_USES_ARTIFACT_PLACEMENT_MODEL=true`

`RAG_ENGINE_CONSUMES_PLACEMENT_METADATA=false`

`MULTI_SCOPE_METADATA_PRESERVED_CONTROL_PLANE=true`

`MULTI_SCOPE_METADATA_PRESERVED_DATA_PLANE=false`

`MULTI_PLACEMENT_RETRIEVAL_PASS=false`

## Mutations

Le harnais `h2b_true_mutation_harness.py` exécute désormais douze mutations
réelles et indépendantes : droits, PII, actualité, exclusion, format non pris
en charge, objet inconnu, SHA contenu, manifest, autorité de scope, révocation,
échec d'extraction et disposition primaire unique. Chaque cas a prouvé :
baseline verte, neutralisation d'une ancre exacte, rouge du test nommé pour la
raison attendue, restauration SHA-256 octet pour octet, puis retour au vert.
La révocation a été exercée sur PostgreSQL jetable avec la chaîne LOT41A
réelle ; aucune base de production n'a été ciblée.

`H2B_TRUE_MUTATIONS_NON_VACUOUS=12/12`

`TEMPORARY_MUTATIONS_RESTORED=true`

`H2B_TRUE_MUTATION_EVIDENCE_SHA256=6a84327e188e67fde1e10693d1c0670b8c850fea6130e69bec4237e2e687dbe4`

## CI locale

La relance canonique complète, avec Python 3.12.3 et Node 22.22.0, a exécuté
les seize cibles sans tolérance d'échec : contrats, `rag-pedago` (Ruff, mypy,
1 904 tests), `rag-engine` (mypy sur 92 fichiers, suite unitaire et intégration
PostgreSQL/pgvector), cockpit (178 tests, deux builds, audits npm), gouvernance
et contrôles du dépôt. Elle a produit `15 PASS / 1 FAIL` sur le head source
`c97ed283213f916a1620681e929be840becfde75`.

L'unique échec venait de la sonde topologique LOT41V : elle lançait une copie
instrumentée de la CI tout en héritant de `NEXUS_CI_LOCAL_RUNNING=1`, ce qui
déclenchait le garde anti-réentrance avant d'observer les trois cibles. La sonde
utilise maintenant explicitement un contexte frais. Après correction :

- `test-ci-local-topology.sh` : PASS, y compris les 22 mutations hybrides et le
  mutant qui place les contrôles après `exit 0` ;
- `test-ci-local-failsafe.sh` : 51 PASS, 0 FAIL ;
- `git diff --check` : PASS.

La CI exhaustive n'est pas requalifiée verte sur le nouveau head sur la seule
base de ces tests ciblés. Elle doit être rejouée après les trois remédiations
H2-B bloquantes et avant l'audit indépendant.

`LOCAL_CI_FULL_CURRENT_HEAD=NOT_RERUN_AFTER_TARGETED_FIX`

`LOCAL_CI_TARGETED_TOPOLOGY=PASS`

## Arrêt gouverné

Conformément aux hard stops, aucune des opérations suivantes n'a été exécutée :

- audit H2 indépendant ;
- passage de la PR 95 en ready ;
- merge H2 ;
- déploiement P1/P2/P3/P4 ;
- activation LOT42 live ;
- ingestion de production.

`LOT42_LIVE_PIPELINE_WIRED=false`

`PUBLIC_WRITER=false`

`HIDDEN_WRITER=false`

`SECRETS_EXPOSED=0`

`RAW_PII_LOGGED=0`

## Remédiations obligatoires

1. Introduire une représentation data-plane des placements 1:N, avec migration,
   rollback, test réel multi-placement et isolation des tuples de scope.
2. Produire les autorisations LOT41A et attestations LOT42 réelles, puis obtenir
   la review GitHub Code Owner exigée sur le HEAD exact.
3. Exécuter et sceller les douze vraies mutations temporaires.
4. Rejouer CI et sécurité sur le HEAD final avant audit indépendant.

Tant que ces remédiations ne sont pas toutes vertes, aucune disposition ne peut
être promue vers `INGEST` et aucun déploiement n'est autorisé par le gate
technique.

## Matrice de clôture demandée

```text
=== RIGHTS HUMAN DECISION ===
EDUSCOL_RIGHTS_HUMAN_REVIEW=APPROVED
EDUSCOL_GENERIC_RIGHTS_BLOCKER=false
EDUSCOL_RIGHTS_SCOPE_MANIFEST=d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e

=== H2 CORPUS ===
REMOTE_OBJECTS=2584
MANIFEST_ENTRIES=2583
EDUSCOL_UNIQUE_ARTIFACTS=2451
EDUSCOL_PLACEMENTS_TOTAL=2956
PDF_TOTAL=2476
INGEST=0
REVIEW_REQUIRED=2471
QUARANTINE=2
ARCHIVE_ONLY=19
EXCLUDE=55
UNSUPPORTED=37
UNCLASSIFIED=0
MULTIPLE_PRIMARY_DISPOSITION=0

=== PII ===
PII_SCAN_SCOPE=INITIAL_PRODUCTION_ELIGIBLE_PDFS
PII_SCAN_REQUIRED=64
PII_SCANNED=64
PII_CLEARED=63
PII_REVIEW_REQUIRED=0
PII_QUARANTINED=1
PII_EXTRACTION_FAILED=0
INGEST_WITHOUT_PII_CLEARANCE=0

=== RIGHTS SAFETY ===
INGEST_WITHOUT_RIGHTS_CLEARANCE=0
DEPP_INGEST_WITHOUT_RIGHTS=0

=== AUTHORITY ===
EXTERNAL_AUTHORITY_TESTS=83/83_MECHANISM_ONLY
INGEST_WITHOUT_AUTHORITY=0
REAL_SCOPE_AUTHORIZATION_PRESENT=false
BLOCKED_INGEST_CANDIDATES_WITHOUT_AUTHORITY=64

=== MUTATIONS ===
H2B_TRUE_MUTATIONS_NON_VACUOUS=12/12
TEMPORARY_MUTATIONS_RESTORED=true
H2B_TRUE_MUTATION_EVIDENCE_SHA256=6a84327e188e67fde1e10693d1c0670b8c850fea6130e69bec4237e2e687dbe4

=== RETRIEVAL ===
EPHEMERAL_INDEXING_PASS=PASS_EXISTING_SCOPE_MODEL
RETRIEVAL_SCOPE_ISOLATION_PASS=PASS_EXISTING_SCOPE_MODEL
MULTI_PLACEMENT_RETRIEVAL_PASS=false
CONTENT_SHA_TRACEABILITY_PASS=UNVERIFIED_REAL_MULTIPLACEMENT_PATH
CITATION_TRACEABILITY_PASS=UNVERIFIED_REAL_MULTIPLACEMENT_PATH

=== H2 ===
H2_B_IMPLEMENTATION_COMPLETE=false
H2_B_TECHNICAL_GATE=BLOCKED
LOCAL_CI_FULL_CURRENT_HEAD=NOT_RERUN_AFTER_TARGETED_FIX
INDEPENDENT_H2_AUDIT=NOT_RUN
H2_HUMAN_DEPLOYMENT_AUTHORIZATION=GRANTED_STANDING_BUT_NOT_REACHED
H2_MERGED=false
H2_MERGE_COMMIT=NONE

=== P1 ===
P1_PASS=NOT_RUN
BACKUP_VERIFIED=false
ROLLBACK_PLAN_READY=false

=== P2 ===
P2_REHEARSAL_PASS=NOT_RUN

=== P3 ===
P3_CANARY_PASS=NOT_RUN

=== P4 ===
P4_DEPLOYMENT_PASS=NOT_RUN
LOT42_LIVE_PIPELINE_WIRED=false
PUBLIC_WRITER=false

=== PRODUCTION INGESTION ===
FINAL_INGEST_ELIGIBLE=0
FINAL_INGEST_ATTEMPTED=0
FINAL_INGEST_SUCCESS=0
FINAL_INGEST_FAILED=0
UNAUTHORIZED_INGESTED_ARTIFACTS=0

=== PRODUCTION RETRIEVAL ===
PRODUCTION_RETRIEVAL_SMOKE_PASS=NOT_RUN
PRODUCTION_SCOPE_ISOLATION_PASS=NOT_RUN
PRODUCTION_CITATION_TRACEABILITY_PASS=NOT_RUN

=== SAFETY ===
SECRETS_EXPOSED=0
RAW_PII_LOGGED=0
PUBLIC_WRITER=false
HIDDEN_WRITER=false
PRODUCTION_BACKUP_AVAILABLE=false
ROLLBACK_AVAILABLE=false

=== FINAL ===
GO_LIVE_READY=false
GO_LIVE_COMPLETED=false
PRODUCTION_HEALTH=NOT_DEPLOYED
NEXT_ACTION=GO_LIVE_REMEDIATION
```
