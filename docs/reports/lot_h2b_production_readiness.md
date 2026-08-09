# Rapport de lot — H2-E autorité de contenu et préparation corpus

## Verdict technique au 9 août 2026

Ce rapport remplace les états H2-B/H2-C devenus obsolètes. La tête PR finale
sera figée par le commit qui porte ce rapport, puis toute la CI canonique, les
migrations jetables, la sécurité, les preuves externes et l'audit H2
indépendant seront rejoués sur cette tête exacte. Une preuve antérieure ne
vaut jamais pour cette future tête.

```text
LOT41A_V2_IMPLEMENTED=true
CONTENT_ALLOWLIST_ENFORCED=true
REAL_SCOPE_AUTHORIZATION_PRESENT=false
REAL_SCOPE_AUTHORIZATION_DEFERRED_UNTIL_POST_MERGE=true
LIVE_INGESTION=false
LOT42_LIVE_PIPELINE_WIRED=false
PUBLIC_WRITER=false
H2_TECHNICAL_GATE=PENDING_FINAL_EXACT_HEAD_VERIFICATION
```

L'absence d'autorisation réelle n'empêche plus la fusion du code inerte : le
protocole V2 doit d'abord être présent sur `main` avant que la PR d'autorité 96
puisse publier et faire relire un artefact V2. Elle reste néanmoins un verrou
absolu avant toute promotion réelle, tout démarrage P1 et toute ingestion.

## État GitHub observé au début de H2-E

- `START_H2_HEAD=f843c8fe89a8ebca76d0ee0037f13456ca4ec378` ;
- branche : `track-a/lot-h2b-corpus-production-readiness` ;
- PR d'implémentation : `#95`, ouverte et draft ;
- PR d'autorité : `#96` ;
- `PR96_HEAD=f0f8b723debc8d4d1038c1e33de2f808f5d37ba8` ;
- `PR96_BASE_SHA=a956441645d48107ab983fad62b80f0848345e81` ;
- PR 96 ouverte, prête, non fusionnée et marquée `DO NOT APPROVE` ;
- le finding P1 de la PR 96 sur l'absence d'allowlist positive reste ouvert
  jusqu'à la fusion de LOT41A-V2 sur `main`.

Aucun challenge PR 96 n'a été généré et aucune approbation n'a été demandée.

## Contrat partagé et ADR

Le contrat distingue strictement les deux protocoles :

- `LOT41A-V1` conserve exactement sa sémantique historique et n'accepte pas
  de champ V2 ;
- `LOT41A-V2` exige `allowed_content_sha256`, liste positive non vide de
  SHA-256 minuscules, triés, uniques et présents directement dans les octets
  canoniques revus sur GitHub ;
- un protocole inconnu, un champ inconnu, une liste absente, vide, non triée,
  dupliquée, majuscule ou mal formée échoue fermé ;
- changer un seul SHA change les octets canoniques et le digest
  d'autorisation ;
- `pii_absence_evidence` reste une référence d'audit et n'est jamais interprété
  comme une allowlist machine.

`nexus-contracts` passe de `0.6.0` à `0.7.0`, incrément mineur pour l'ajout
rétro-compatible d'un protocole public. L'ADR
`ADR-0034-lot41a-v2-autorite-liee-contenu.md` reste
`Proposé — non Accepté`, conformément à la gouvernance.

```text
OLD_LOT41A_PROTOCOL=LOT41A-V1
NEW_LOT41A_PROTOCOL=LOT41A-V2
CONTENT_ALLOWLIST_FIELD=allowed_content_sha256
OLD_NEXUS_CONTRACTS_VERSION=0.6.0
NEW_NEXUS_CONTRACTS_VERSION=0.7.0
V1_SEMANTICS_PRESERVED=true
V1_CAN_SATISFY_H2_PRODUCTION_POLICY=false
```

## Plan de contrôle : migration 009 et vérification live

La migration additive
`009_scope_authorization_content_allowlist.sql` ajoute
`allowed_content_sha256 TEXT[]` et autorise exactement V1/V2. PostgreSQL
réplique indépendamment de Python les invariants de forme, dimension, borne,
cardinalité, ordre, unicité et casse. V1 exige `NULL`; V2 exige une liste
canonique non vide. Le rollback refuse explicitement de supprimer la frontière
si une ligne V2 existe.

Les répétitions PostgreSQL jetables ont prouvé :

- upgrade d'une base V1, insertion V2 et contraintes SQL directes ;
- rejet de `NULL`, vide, hash invalide/majuscule, doublon, désordre, tableau
  multidimensionnel ou à borne non canonique et membre `NULL` ;
- rollback V1, réapplication et conservation de la ligne ;
- refus fail-closed du rollback lorsqu'une autorité V2 existe ;
- projection exacte par l'opérateur depuis le blob Git revu, sans argument CLI
  permettant d'injecter un SHA ;
- rejet live d'un élargissement, rétrécissement, remplacement ou réordre de la
  liste DB, d'un downgrade V2→V1 et des dérives digest/blob ;
- rôle de retrieval en lecture seule, rôle review sans droit de publication et
  rôle opérateur limité aux écritures requises.

```text
INGESTION_CONTROL_SCHEMA_HEAD=009_scope_authorization_content_allowlist
AUTH_MIGRATION_009_APPLY=PASS
AUTH_MIGRATION_009_SCHEMA=PASS
AUTH_MIGRATION_009_EXISTING_V1_COMPATIBILITY=PASS
AUTH_MIGRATION_009_V2_CONSTRAINTS=PASS
AUTH_MIGRATION_009_ROLLBACK=PASS_FAIL_CLOSED
AUTH_MIGRATION_009_REAPPLY=PASS
```

## Frontière de contenu avant extraction

Le worker vérifie l'autorité live avant fetch, applique les règles de
destination et de redirection, télécharge en stockage temporaire borné, calcule
le SHA des octets bruts, revérifie l'autorité live puis applique l'allowlist
avant tout stockage, extraction ou agent. Une révocation pendant le fetch
empêche donc l'extraction.

Le cas d'attaque P1 — autre ressource du même domaine Eduscol — passe le gate
de domaine puis est refusé au checkpoint `content`. Le buffer est libéré et
aucun appel extractor, rights, quality, LOT42 ou pgvector n'a lieu. Un SHA
autorisé ne peut jamais sauver une URL ou redirection interdite.

```text
SAME_DOMAIN_UNLISTED_CONTENT=DENY_AT_CONTENT
ALLOWED_CONTENT=PASS
WRONG_BYTES_AT_ALLOWED_URL=DENY_AT_CONTENT
ALLOWED_SHA_AT_EXCLUDED_URL=DENY_AT_DESTINATION
UNAUTHORIZED_CONTENT_EXTRACTED=false
UNAUTHORIZED_CONTENT_PERSISTED=false
UNAUTHORIZED_CONTENT_PUBLISHED=false
```

## Plan de données : artefacts et placements 1:N

La migration produit `004_artifact_placements` est additive :

- `rag_artifacts` porte l'identité stable liée au SHA du contenu ;
- `rag_artifact_placements` porte N placements pédagogiques canoniques ;
- `rag_chunks.artifact_id` est nullable pour préserver les lignes legacy ;
- un artefact gouverné est extrait, chunké et vectorisé une seule fois ;
- l'ajout d'un placement n'entraîne ni ré-extraction ni ré-embedding ;
- la retrieval gouvernée filtre par `EXISTS` sur les placements et déduplique
  par identité de chunk ; le chemin legacy ne peut pas être élargi ;
- le publisher interne exige l'attestation vérifiée, écrit atomiquement et
  reste idempotent ; aucune route HTTP d'écriture n'est ajoutée.
- le rollback 004 prend `ACCESS EXCLUSIVE` sur les trois relations avant sa
  garde de vacuité. Un test PostgreSQL concurrent prouve qu'une publication
  committée pendant l'attente rend le rollback rouge et conserve ses lignes.

```text
PRODUCT_SCHEMA_HEAD=004_artifact_placements
MIGRATION_004_APPLY=PASS
MIGRATION_004_ROLLBACK=PASS
MIGRATION_004_REAPPLY=PASS
LEGACY_COMPATIBILITY=PASS
PUBLIC_WRITER=false
HIDDEN_WRITER=false
```

## LOT42 lié à l'autorité V2

L'événement durable `FETCHED` lie le SHA réel, l'identifiant, le digest et le
protocole d'autorisation. Il appartient aux faits revus par LOT42. L'unique
ancre `RETRIEVAL_ELIGIBLE` exige structurellement une autorité V2 et ne propose
aucun paramètre de downgrade. Le publisher revérifie la chaîne avant et dans
la transaction produit ; un refus ne peut être masqué par l'écriture best-effort
du cache d'invalidation.

Le chemin dormant STAGED → NEEDS_REVIEW → REVIEWED → LOT42 →
RETRIEVAL_ELIGIBLE est implémenté sous tests. Son activation production reste
désactivée et les attestations de publication production seront créées plus
tard à partir des événements durables réels.

```text
LOT42_MECHANISM_IMPLEMENTED=true
LOT42_PIPELINE_PATH_IMPLEMENTED=true
LOT42_V2_CONTENT_BOUND=true
REAL_PRODUCTION_PUBLICATION_ATTESTATIONS=DEFERRED_TO_P4_BY_DESIGN
LOT42_LIVE_PIPELINE_WIRED=false
```

## Répétition H2-E réelle et scellée

La répétition utilise le vrai PDF scellé
`371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d`,
classé PII `CLEARED` sur 60 pages, et ses 7 placements réels. Le matérialiseur
effectue exactement trois copies Drive en lecture seule dans un scratch direct
sous `/tmp`, propriétaire et mode 0700 ; les destinations finales et
temporaires refusent les liens. Le catalogue doit être marqué réel, vérifié,
lié au manifest scellé et à son propre digest.

La répétition PostgreSQL/pgvector jetable prouve :

- 7 vrais appels réseau au fetcher, un par ressource/scope, avec destination,
  revérification live, SHA et allowlist effectivement exécutés ;
- 7 callbacks de stockage et 7 artefacts control liés au même SHA, mais une
  seule écriture de blob content-addressed sur stockage temporaire réel ;
- une seule relecture vérifiée taille/SHA et un seul parse PDF après `STORED` ;
- transitions CAS `EXTRACTED`/`CLASSIFIED` liées au catalogue scellé, puis
  rights, quality, review, LOT42, publication et retrieval sur les 7 chaînes ;
- une ligne artefact, 7 placements, un seul jeu de chunks/vecteurs ;
- zéro doublon vecteur, chunk et résultat ;
- retrieval dans deux scopes réels et blocage du mauvais scope ;
- traçabilité citation et placement ;
- exactement un parse/extraction pour le parcours positif ;
- parcours négatif via le vrai fetcher HTTP : domaine `PASS`, contenu `DENY`,
  état `CANDIDATE`, zéro store/extractor/rights/quality, zéro artefact contrôle,
  zéro éligibilité retrieval et zéro ligne produit.

Le scelleur valide indépendamment chaque métrique substantielle. Une matrice
adversariale de 28 cas refuse champ absent, métrique altérée et confusion
`bool`/`int`.

```text
REAL_MULTI_PLACEMENT_SHA=371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d
REAL_MULTI_PLACEMENT_PLACEMENTS=7
ARTIFACT_ROWS_FOR_SHA=1
PLACEMENT_ROWS=7
CHUNK_SET_COUNT=1
DUPLICATE_VECTOR_SETS=0
DUPLICATE_CHUNK_SETS=0
DUPLICATE_RESULT_CHUNKS=0
SCOPE_A_RETRIEVAL_PASS=true
SCOPE_B_RETRIEVAL_PASS=true
WRONG_SCOPE_RETRIEVAL_BLOCKED=true
V2_FULL_GOVERNED_REHEARSAL_PASS=true
V2_NEGATIVE_REHEARSAL_PASS=true
POSITIVE_NETWORK_FETCHES=7
POSITIVE_STORE_CALLBACKS=7
POSITIVE_PHYSICAL_BLOB_WRITES=1
POSITIVE_BLOB_READBACKS=1
POSITIVE_CONTROL_ARTIFACT_ROWS=7
POSITIVE_UNIQUE_CONTENT_SHA=1
POSITIVE_PDF_PARSES=1
```

La preuve antérieure à l'audit indépendant est explicitement obsolète. La
nouvelle `h2e_v2_governed_rehearsal.json` sera régénérée seulement après le
commit final. Son sceau inclura le HEAD, le tree Git et les SHA-256 du runner,
du scelleur et du test d'intégration exacts, vérifiés avant et après le run.
Le digest final sera publié dans le corps de la PR et le rapport machine,
jamais deviné dans ce commit. Aucun chemin local, secret ou contenu brut ne
sera inclus.

## Findings de l'audit indépendant et remédiation

Le premier audit indépendant de la tête `b7449fdb11a14748545881b9a6a3c7eedc337344`
a correctement rendu `FAIL` sur trois P1 : parcours positif H2-E simulé,
preuve non liée à la tête exacte et fenêtre TOCTOU du rollback 004. Aucun de
ces findings n'est ignoré : les trois remédiations sont décrites ci-dessus et
ont chacune un test rouge→vert. Cette tête candidate doit encore subir une
nouvelle répétition scellée, la CI complète et un nouvel audit indépendant ;
le verdict final reste donc fermé jusque-là.

## Mutations vraies

Le harnais couvre désormais treize gardes indépendantes : droits, PII,
actualité, exclusion, format non supporté, objet inconnu, SHA contenu,
manifest, scope, révocation, extraction, disposition unique et appartenance à
l'allowlist positive. Chaque mutant part d'une baseline verte, neutralise la
garde exacte, rend rouge le test ciblé pour la cause attendue, restaure les
octets originaux dans `finally`, vérifie leur SHA puis revient au vert.

```text
H2B_TRUE_MUTATIONS_NON_VACUOUS=13/13
MUT_CONTENT_ALLOWLIST=PASS_NON_VACUOUS
TEMPORARY_MUTATIONS_RESTORED=true
MUTATED_FILE_BYTES_MATCH_ORIGINAL=true
```

Preuve externe : `h2b_true_mutations_h2e.json`, SHA-256
`e29668c5b76cec89565c6c6f722c945bc42d86d5198657ea9ec96867547e6211`.
Le SHA restauré de `scope_enforcement.py` est
`eee1d2ee885155f0c079d80e8a9555982ae2f2e81553474faa5160a5820964e5`.

## Corpus réel et PII

Les compteurs sont dérivés des métadonnées Drive scellées, jamais d'un
catalogue synthétique :

| Mesure | Valeur |
|---|---:|
| Objets distants/physiques | 2 584 |
| Entrées du manifest | 2 583 |
| PDF | 2 476 |
| Artefacts Eduscol uniques | 2 451 |
| Placements Eduscol | 2 956 |
| Artefacts multi-placement | 433 |
| Placements classifiés | 2 109 |
| Placements historiques non classifiés | 847 |

`SHA256SUMS.txt` est l'objet physique 2 584 et reste
`EXCLUDE/MANIFEST_SELF_OBJECT`. Le manifest vaut
`d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e`.

Le scope PII initial comprend les 64 PDF qui pouvaient être promus : 64
scannés, 63 `CLEARED`, un `QUARANTINED_PII`, zéro échec et zéro non scanné.
La preuve PII externe vaut
`c559891f8f636a5b25fc97e25ab959c143b1e352e36d150139c8737ee33060d6`.
Le SHA quarantiné
`b81201b857c67e4e928a079cfe9d5b9b402537d0101bfccc730465631d5e8376`
n'apparaît dans aucune allowlist de répétition.

Faute d'autorisation PR 96 réelle, la compilation production reste fermée :

| Disposition | Nombre |
|---|---:|
| INGEST | 0 |
| REVIEW_REQUIRED | 2 471 |
| QUARANTINE | 2 |
| ARCHIVE_ONLY | 19 |
| EXCLUDE | 55 |
| UNSUPPORTED | 37 |
| **Somme** | **2 584** |

`UNCLASSIFIED=0` et `MULTIPLE_PRIMARY_DISPOSITION=0`. Cet `INGEST=0` est
attendu pour la clôture du code H2 ; la compilation non vacante sera effectuée
après fusion H2 et approbation réelle de la PR 96 V2.

## Décisions humaines de droits

La décision explicite de Nexus Réussite reste enregistrée comme décision
organisationnelle humaine, sans avis juridique ni signature fabriqués :

```text
EDUSCOL_RIGHTS_HUMAN_REVIEW=APPROVED
EDUSCOL_RIGHTS_HUMAN_DECISION_SOURCE=NEXUS_REUSSITE
EDUSCOL_GENERIC_RIGHTS_BLOCKER=false
EDUSCOL_RIGHTS_SCOPE_MANIFEST=d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e
```

Une restriction spécifique reste fail-closed au niveau de l'artefact. Les
documents DEPP non clarifiés restent `REVIEW_REQUIRED` sans bloquer le reste.

## Gates encore à exécuter sur la tête finale

Après le présent commit de rapport, aucun fichier versionné ne sera modifié
avant la fin des gates. La tête résultante devra passer :

1. migration produit 004 apply/rollback/reapply et migration autorité 009
   apply/contraintes/rollback/reapply sur PostgreSQL jetable ;
2. nouvelle répétition H2-E et matrice 13/13 liées à la tête exacte ;
3. `scripts/ci-local.sh` complet avec l'environnement valide ;
4. scans secrets, PII, PDF réel et credentials sur `main..HEAD` ;
5. push fast-forward et tous les checks GitHub techniques sur le même SHA ;
6. audit H2 véritablement indépendant avec zéro finding bloquant ;
7. passage de la PR 95 en ready et génération de son challenge propre.

Jusqu'à leur réussite :

```text
H2_IMPLEMENTATION_READY=PENDING_FINAL_GATES
H2_TECHNICAL_GATE=PENDING_FINAL_GATES
H2_READY_FOR_HUMAN_REVIEW=false
INDEPENDENT_H2_AUDIT=NOT_RUN_ON_FINAL_HEAD
REAL_SCOPE_AUTHORIZATION_PRESENT=false
PR96_APPROVAL_REQUESTED=false
PRODUCTION_DATABASE_TOUCHED=false
PRODUCTION_DEPLOY=false
LIVE_INGESTION=false
PUBLIC_WRITER=false
HIDDEN_WRITER=false
LOT42_LIVE_PIPELINE_WIRED=false
```

La prochaine étape après gates et audit verts est
`NEXT_ACTION=H2_TRUSTED_HUMAN_REVIEW`. Si un gate rougit, elle redevient
`NEXT_ACTION=LOT41A_V2_REMEDIATION`.
