# Plan d'exécution DI — reprise partielle de la publication V4 sous la revue #262

Orchestrateur : `scripts/go_live/staging_v4_partial_recovery.sh`.
Outil : `scripts/go_live/staging_v4_partial_recovery.py`.
Identité de la reprise partielle : `docs/reports/go_live/recovery/di_partial_v4_262.json`.
Autorisation : `docs/reports/go_live/authorizations/staging_v4_partial_recovery_authorization.json`.
La PR d'activation la porte avec l'image épinglée ; le vérificateur refuse toute
opération tant que ce document et le plan ne sont pas fusionnés à l'identique
sur `main`.

## 0. État de départ (donnée d'incident)

| Fait | Valeur |
|---|---|
| Release | `production-profile-gate-2026-2027-v4`, manifeste `bab9c398…4cda4be` |
| Revue active | #262 au head `079461659b60f8a8ce9458145a199599ad822bbc`, ouverte, approuvée |
| Attestations actives (#262) | 479 |
| Jobs de reprise | 479 : 76 `succeeded`, 403 `queued`, 0 `dead_letter` |
| Ressources | 77 `RETRIEVAL_ELIGIBLE`, 402 `NEEDS_REVIEW` ; 77 pins |
| Produit | 9 collections, 72 artefacts, 76 placements, 1532 chunks |
| Cas épinglé | `rag_nexus_nsi_terminale_specialite` : `RETRIEVAL_ELIGIBLE`, pin, aucun placement, job `queued` 1/3 |

Les 403 jobs en file se partagent entre :

- **329 non-HGGSP**, bloqués par la seule limitation GitHub (dont le cas
  épinglé) : leur autorité V4 est valide ;
- **74 HGGSP** (39 + 35) : **non publiables sous V4**, le mapping de sujets que V4
  scelle ne gouverne pas `hggsp`.

## 1. Principes

- Même base dédiée `ragdb_profile_gate_v4`, mêmes attestations #262, mêmes
  jobs. Ni nouvelle base, ni réingestion, ni nouvelle release, ni nouvelle
  revue. `ragdb` mesurée au pré-vol et revérifiée après chaque étape.
- **Aucune écriture SQL manuelle** sur `jobs` : ni `status`, ni
  `next_attempt_at`, ni `attempt_count`. La sélection est faite par Worker B
  lui-même (`--collection`, `claim_job(collections=…)`), et il refuse de
  démarrer si une collection de sa liste ne se résout pas par les mappings
  scellés.
- **Les 74 jobs HGGSP ne sont ni réclamés, ni annulés, ni retentés, ni
  reportés.** Leur empreinte (statut, tentatives, échéance, dernier motif,
  bail) est relevée au pré-vol et exigée identique à la fin.
- **La revue #262 reste ouverte** : tant que les 74 HGGSP attendent,
  `closure-check` (DH) refuse, et le contrôle partiel annonce
  `review_closure=NOT_SAFE`.
- **Image Worker B DI**, construite depuis `main` par le workflow canonique :
  l'image de V4/DH (`sha256:57e0797…`) ne contient pas le correctif.
- Vérifications live d'ADR-0033 inchangées (63 GET GitHub mesurés par
  publication, aucune mise en cache) ; seule la **cadence** change : 60 s entre
  deux réclamations, soit au plus ~3 780 requêtes/heure.

## 2. Avant toute exécution (hors hôte)

1. **PR DI fusionnée** : le commit `fb8a7cc8e85448115a64de8ff5325d639ef9ee70`
   est sur `main` et porte le correctif.
2. **Image DI construite depuis ce commit** : run de provenance
   `36321957702` (`workflow_dispatch`, tentative 1, `success`) ; inventaire
   `NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1`, artefact
   `nexus-deployment-image-inventory` n° `10932683454` ; image Worker B
   `ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:8980977c6eda1fe2f7545cd9e2cedee4655a6afbd5abea45765780af067175e6`.
3. **PR d'activation DI**, distincte : déplacement de la proposition dans
   `authorizations/`, image épinglée et preuve de provenance. Elle doit être
   approuvée au HEAD exact et fusionnée avant toute opération. Le vérificateur
   exige ce document et ce plan à l'identique sur `origin/main`, le commit de
   build sur `origin/main` avec le correctif, et la même sonde que DH.
4. **Signature locale** de la readiness pour l'image DI (détenteur de la clé) :
   `scripts/go_live/sign_staging_v4_di_readiness_manifest.sh` →
   `~/nexus-staging-v4-di-readiness/staging-readiness-v4-di.json`.

## 3. Étapes (orchestrateur)

| # | Étape | Rôle | Écrit | Arrêt |
|---|---|---|---|---|
| 1 | `partial_readiness_install` | hôte, fichier | manifeste DI à côté de celui de V4 (jamais écrasé) | — |
| 2 | `partial_preflight` | app (lecture), jeton | non | refus au moindre écart |
| 3 | `partial_worker_b_publication` | app + publisher + jeton | produit (9 collections) | code 75 : limitation persistante |
| 4 | `partial_independent_verification` | reader | non | comptes exacts |
| 5 | `partial_closure_check` | app (lecture) | non | **humain** : #262 reste ouverte |

```
scripts/go_live/staging_v4_partial_recovery.sh --dry-run run   # essai à blanc
scripts/go_live/staging_v4_partial_recovery.sh run             # réel, après activation
scripts/go_live/staging_v4_partial_recovery.sh status
```

### 3.1 Pré-vol (`partial_preflight`)

Refus si : un Worker B en cours (`nexus-v4-worker-b`, `-dh`, `-di-*`) ; jeton
absent ou mal protégé ; mesure de `ragdb` incomplète. Puis, en lecture seule :

- `partial-precondition` : base, rôle, 479 attestations actives toutes de
  #262 au head exact, release V4 ; collections exclues **dérivées des mappings
  scellés de V4** et égales à l'identité versionnée ; chaque attestation HGGSP :
  ressource `NEEDS_REVIEW`, aucun pin, **un** job `queued` sans bail avec au
  moins une tentative restante, aucun `dead_letter` ; chaque attestation reprise :
  publiée (job réussi) ou **un** job vivant, aucun `dead_letter`, aucun bail
  actif ; une ressource déjà promue (`RETRIEVAL_ELIGIBLE`) sans publication
  est admise, avec ou sans pin (le cas NSI terminale : avec pin) — le même job
  reprend sans nouvelle promotion ; un pin sur une ressource non promue est un
  refus. Sous le rôle produit `rag_reader`, le pré-vol vérifie la base et le
  rôle de la connexion, puis lit tous les placements, artefacts et identités de
  chunks de la base dédiée. Il dérive les placements attendus des seules
  attestations dont le job est `succeeded`, avec `placement_id` et
  `source_placement_id` des sujets scellés de V4, puis les artefacts et
  `chunk_id` du registre de la release. Il refuse tout
  produit supplémentaire ou manquant, toute discordance job réussi/placement
  et tout placement HGGSP. Cette garde est réévaluée avant Worker B lors de
  chaque reprise partielle ; elle n'impose pas les comptes initiaux
  72/76/1532.
  Sortie : `PARTIAL_PRECONDITION_OK claim_scope=… excluded_jobs_sha256=… already_published=76 to_publish=329 pinned_awaiting_product=1 promoted_awaiting_pin=0 excluded_pending=74`.
- `review-precondition --pull-request 262 --expected-head 0794… --stage worker-b`
  (outil DH) : #262 approuvée **en direct** au head exact, artefact relu.

L'empreinte des jobs exclus du **premier** pré-vol est la référence ; une
relance doit la reproduire à l'identique.

### 3.2 Worker B (`partial_worker_b_publication`)

Conteneur `nexus-v4-worker-b-di-<n>`, image DI, readiness DI, arguments
canoniques V4 **plus** :

```
--collection <chacune des 9 collections gouvernées>
--min-job-interval-s 60 --rate-limit-max-wait-s 900
--max-consecutive-rate-limits 3 --max-idle-polls 5
--max-iterations <3 × to_publish + 50>
```

Au démarrage, Worker B imprime
`MULTILEVEL_PUBLICATION_WORKER_CLAIM_SCOPE collections=…` et refuse si une
collection n'appartient pas à la release ou ne se résout pas.

Sur limitation GitHub (403/429 identifiée par `Retry-After`,
`x-ratelimit-remaining: 0` ou le message GitHub) : le job est rendu à la file
**sans tentative consommée**, pas avant le délai imposé (au moins 60 s), et
toute réclamation est suspendue. Au-delà de 900 s d'attente ou de 3 limitations
consécutives : **arrêt code 75**, file intacte. L'orchestrateur s'arrête ; la
relance se fait plus tard avec `DI_RELAUNCH=1` (le pré-vol est refait et doit
reproduire l'empreinte des exclus).

Un 403 qui n'est pas une limitation (droits, jeton révoqué) reste un refus
ordinaire : il consomme une tentative comme avant, et son message GitHub est
désormais conservé.

### 3.3 Vérification (`partial_independent_verification`)

`PLACEMENTS=9 263 405`, `CHUNKS=5678`, `HGGSP=0`, sonde de retrieval sous les
**neuf** scopes (`staging_retrieval_probe.py --collection …`).

### 3.4 Contrôle partiel (`partial_closure_check`)

`DI_PARTIAL_PUBLICATION_COMPLETE published=405 excluded_pending=74 excluded_jobs_sha256=<référence> review_closure=NOT_SAFE`.
Jamais `REVIEW_CLOSURE_SAFE` : la PR #262 reste ouverte, approuvée, inchangée.

## 4. Conditions d'arrêt

Tout écart du pré-vol, toute exclusion non dérivée de l'autorité scellée, tout
job exclu modifié, #262 non approuvée en direct, arrêt 75 de Worker B, toute
variation de `ragdb`. Arrêt sans suppression ni réécriture.

## 5. Retour arrière

Arrêt du conteneur Worker B DI (conservé comme preuve). Aucune ligne supprimée
ni réécrite à la main. Les placements publiés restent : ils sont attestés,
épinglés et vérifiés.

## 6. Hors de ce plan

Les 74 placements HGGSP : décision de gouvernance sur la release successeur
(voir le rapport de lot DI). Aucune opération de ce plan ne les touche.
