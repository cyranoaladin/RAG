# LOT 1.2 — release candidate V2 post-revue PII

## Ce que cette candidate est, et ce qu'elle n'est pas

Elle porte le **corpus final autorisé** : 320 contenus, 488 placements, 11
collections, dont les 23 contenus détectés puis admis par la revue humaine
scellée `pii-review-2026-09-03-final`.

Elle n'est **pas activable**. Le gate PII n'est qu'un des gates de go-live ;
C1 à C6 restent ouverts. La release est donc émise `NOT_PROMOTABLE` /
`NO_PRODUCTION_ACTIVATION`, statuts que le runtime refuse déjà mécaniquement.

Corpus final ≠ permission de déployer.

## Identité

```
PRODUCER_COMMIT      = 80e08de (release-chain: chaîne d'autorité de la revue PII)
PRODUCER_TREE        = arbre propre au lancement ; commit à 08:37:39 UTC, run à 08:45:21 UTC
RUN_ID               = candidate-v2-20260904T084521Z
TOP_LEVEL_RC         = 0
CANDIDATE_RELEASE_ID = production-profile-gate-2026-2027-v2-candidate-candidate-v2-20260904T084521Z
AGGREGATE_SHA256          = f9ca9829f793236f71f9542fed0a3c1f2aac4ac5f07a91ac976dfa166666b371
ARTIFACT_REGISTRY_SHA256  = 08595a1b86953e31e13dc62871139114afd6a25bc9351c4d5db5a90c4788ddd1
REGISTRY_SHA256           = b82feaf29145c156b10826c71a9291d14bc81a97b01aa6fa3a401b8be07d6b31
AUTHORITY_BINDINGS_SHA256 = ed654d1c4ba1921dd6fd9b944d1ea5399732724d4d65b1bd0c7373c29219876b
PII_EVIDENCE_SHA256       = add76f75f5d1ce09b82a418a56f5d2a1ea2021bdf092777c1633526addf26dd8
CURRENTNESS_EVIDENCE_SHA256 = f7c6d813aa07484efc388e54dc18a302ce0ebf395b50b417388dbc889dd15df0
```

Réserve cosmétique : `release_id` porte `candidate-candidate-`, le préfixe
passé et le `RUN_ID` se recouvrant. L'identifiant reste unique et distinct de
l'identité historique, ce qui est la propriété qui compte ; le doublon sera
corrigé au prochain tirage plutôt qu'en relançant neuf minutes de production.

## Lignée — pourquoi elle est démontrable et non postulée

```
matrice_production_20260831  ∩  11 profils v2_livraison_319
  = 320 contenus, 488 placements, 11 collections
  digest de l'ensemble = 77f01c824c6be14ba6fd66eda99c2179fd87d9a2aaaf3c58e56a917d1ad5c31d
```

Ce digest est **aussi** le `content_set_sha256` déclaré par l'index de la
campagne de revue PII : le corpus produit et le corpus revu sont le même
ensemble, établi par deux artefacts indépendants.

## Hard gate de dérive — PASS

Comparaison par `content_sha256`, `chunk_index`, `chunk_sha256`, `page_start`,
`page_end`, contre la base servie lue en SELECT seul.

```
HISTORICAL_ARTIFACTS_COMPARED = 319     HISTORICAL_ARTIFACT_DRIFT = 0
HISTORICAL_CHUNKS_COMPARED    = 8324    HISTORICAL_CHUNKS_IDENTICAL = 8324
  changed = 0     missing = 0     extra = 0
```

## Delta d'ensembles — exact

```
CANDIDATE_ARTIFACTS  - DB = { 8848f0732cc1a51ac173422805ca63ce837a94acbad916714dfaedc0ffb1f04f }
DB - CANDIDATE_ARTIFACTS  = vide
CANDIDATE_PLACEMENTS - DB = { (8848…, rag_nexus_nsi_premiere_specialite),
                              (8848…, rag_nexus_nsi_terminale_specialite) }
DB - CANDIDATE_PLACEMENTS = vide
NEW_CHUNKS = 97, tous rattachés à 8848…     UNIQUE_CHUNKS = 8421 = 8324 + 97
```

## PII — sept dimensions, toutes dérivées

```
SCANNED = 320   DETECTED = 23   CLEARED = 297   REVIEWED_ACCEPTED = 23
REJECTED = 0    AUTHORIZED = 320    QUARANTINED = 0
```

`REVIEWED_ACCEPTED_SET == APPROVED_SET`. `ACCEPTED ∩ CLEARED = ∅`. Les 23
contenus admis conservent `pii_detected=true` ; les 297 autres sont à `false`.
Aucun compte n'existe comme littéral dans le code : un test lit l'arbre
syntaxique et refuse 297, 23 et 320.

## `8848f0732cc1…`

```
page_count = 54     ignored_empty_pages = [2, 54]     chunks = 97
PII = CLEARED       placements = nsi_premiere_specialite, nsi_terminale_specialite
covered ∩ ignored = ∅          covered ∪ ignored = {1..54}
```

Pagination sans décalage : la première citation après la page ignorée porte la
page physique 3 (chunk 1), la dernière porte la page 53 (chunk 96).

## Currentness — trois portes distinguées

```
CURRENTNESS_SCHEMA_BINDING = PASS
CURRENTNESS_SCOPE_BINDING  = PASS   (ensemble de la preuve == ensemble candidat, 320/320)
CURRENTNESS_FRESHNESS      = UNVERIFIED_SOURCE_UNREACHABLE
```

La dette « preuve 26 contre corpus 319 » ne survit pas. La fraîcheur reste
non vérifiée, déclarée comme telle par le document lui-même
(`network_mode=UNVERIFIED`, `attempts=[]`, `verified_at=null`), et devient un
gate GO_LIVE_READY — pas une raison de falsifier LOT 1.2.

## Modèles

```
HF_EMBEDDING_REVISION = 3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3
HF_RERANKER_REVISION  = c5ee24cb16019beea0893ab7796b1df96625c6b8
MODEL_SOURCE_INPUT_FILES      = 10 (embedding) / 6 (reranker)
GENERATED_INVENTORY_ENTRIES   = 11 / 7   — la différence est le manifest.json produit
EMBEDDING_INPUT_SET_SHA avant == après   RERANKER_INPUT_SET_SHA avant == après
```

Le run n'a modifié ni les poids ni leur inventaire.

## Base de production

```
PROD_DB_WRITES = 0    DEPLOYMENTS = 0    CURRENT_SWITCH = 0
Base servie inchangée : 319 artefacts | 8324 chunks | 486 placements
```

L'écart 320/488 est un **delta non appliqué**, reconnu comme tel.

## Sept tentatives, six refus, une production

Aucun refus n'a été traité en abaissant une garde. Les quatre sabotages de
contrôle rendent `PRODUCER_RC=1` et `PUBLISHED_FILES=0`.

Le décompte précédent parlait de « sept refus » alors que la ligne 5 du tableau
est un SUCCÈS — scan, projection et chunking réussis, l'échec survenant plus
loin. Sept tentatives, dont six refusées.

| # | Refus | Nature |
|---|-------|--------|
| 1 | instantané de modèle non canonique | garde correcte ; mauvais chemin d'entrée |
| 2 | audit de currentness scellé | dette antérieure D4 |
| 3 | contenu décidé hors corpus | lignée par défaut divergente — défaut fermé |
| 4 | `context_sha256` divergent | fenêtre 50 c. au lieu de 240 c. — défaut fermé |
| 5 | — | scan, projection et chunking réussis |
| 6 | chaîne d'autorité fermée à 19 champs | contrat trop étroit — élargi de 4 champs indivisibles |
| 7 | écarts d'empreinte d'autorité | motif écrit fourni, comparaison jamais désactivée |

## CI locale — 19 cibles PASS, avec un écart déclaré

`scripts/ci-local.sh` déclare **19 cibles** `run_target`, mesurées dans le
script. Les dix-neuf passent.

Le décompte précédent, « vingt-et-une cibles », était faux à deux titres :
il comptait les opérations de mon script de rejeu — qui éclate les deux cibles
de service en lint / typecheck / test, soit 21 opérations pour 17 cibles — et
il omettait `services/cockpit` et `main-protection-policy-tests`, exécutées
depuis (respectivement RC=0 sur lint+tests+build, et 34 tests OK).
Elles ont été exécutées contre les venvs existants et épinglés, **sans** son
étape `rm -rf .venv && make install`, que le cgroup mémoire de cette machine
tue systématiquement pendant l'installation de torch et triton (31 Gio dont 22
déjà utilisés, swap saturé ; deux tentatives, même point d'arrêt, trace OOM du
noyau à l'appui).

Ce qui est prouvé : le code passe toutes les vérifications.
Ce qui ne l'est pas localement : qu'une installation propre depuis
`requirements.lock` aboutit sur cette machine. La CI distante couvre ce point,
dont C1 dépend également.
