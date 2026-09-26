# Lot DI — reprise partielle de Worker B V4 après l'incident de #262

Branche : `go-live/di-partial-v4-worker-recovery`, depuis `main`
`0cb6dde73fcf69ee903760ea1f89fca0815c0b99`.
Aucune opération serveur, aucune base réelle, aucun Worker B réel : tout ce qui
suit est mesuré sur le dépôt et sur PostgreSQL jetable dans la session cloud,
sauf les faits d'incident (§ 1), rapportés par l'opérateur et **non remesurés**.

## 1. Incident (donnée opérateur, non remesurée ici)

- Release `production-profile-gate-2026-2027-v4`, manifeste `bab9c398…4cda4be` ;
  image Worker B `ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:57e0797…bb20d` ;
  readiness `368ed1ea…689f8`.
- Revue active #262, head `079461659b60f8a8ce9458145a199599ad822bbc`, ouverte, approuvée.
- Contrôle après le premier Worker B : 479 attestations actives, 479 jobs
  (76 `succeeded`, 403 `queued`, 0 `dead_letter`), 77 `RETRIEVAL_ELIGIBLE`,
  402 `NEEDS_REVIEW`, 77 pins. Produit : 9 collections, 72 artefacts,
  76 placements, 1532 chunks.
- Worker B : 482 lignes d'itération (76 `succeeded`, 406 `retried`, 479 jobs
  distincts, 0 `lease_lost`) ; 390 échecs `GitHub returned HTTP 403 for
  repos/cyranoaladin/RAG/pulls/262 — failing closed` ; 13 échecs
  `external subject 'hggsp' is not governed`.
- Après l'arrêt, le même jeton rend 200 sur la même route,
  `x-ratelimit-remaining: 4999`.

## 2. Causes racines

### 2.1 HGGSP — prouvée

- Le mapping de sujets que V4 scelle (`authorities.subject_mapping_sha256` =
  `85a8efa1…c71c`, `services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml`)
  ne contient pas `hggsp`. Les deux collections HGGSP (39 + 35 placements) ont
  `external_subject: hggsp` dans l'inventaire candidat et `matiere: hggsp` dans
  la configuration : `ClosedMultilevelMapping.resolve` refuse, à chaque job.
- Pourquoi rien ne l'a vu :
  - V2, V3 et V4 ont été produites en mode `rehearsal`, qui **recopie** les
    autorités de la release source (V1, `authority_bindings.json`) sans les
    re-dériver (`build_production_profile_release.py:3692-3694`) ;
  - aucune qualification ne résolvait les sujets de la release par le mapping
    scellé : le producteur construit `external_subject` par un dictionnaire
    inverse codé en dur et ne fait que hacher le mapping ;
  - le banc réel V4 ne publie par défaut que dgemc, nsi et svt.
- **Épreuve A** : `tests/test_di_release_subject_governance.py` charge les VRAIS
  fichiers de V4 par les chargeurs canoniques, liés par les empreintes du
  manifeste. Le nouveau contrôle `ungoverned_release_collections` refuse
  exactement les deux collections HGGSP, avec la raison exacte de Worker B, et
  elles seules.

### 2.2 403 GitHub — hypothèse bornée, fortement étayée, non prouvée

Le client ne conservait que `GitHub returned HTTP <statut> for <chemin>` : aucun
en-tête, aucun message. La cause exacte ne peut donc pas être prouvée
rétroactivement.

Coût GitHub **mesuré** d'une publication (banc DI, un relecteur gouverné) :
**63 GET**, dont 9 vérifications live exigées par ADR-0033 § 7bis, aucune
supprimée. Une reprise de job déjà épinglé en coûte 56.

| Poste | GET |
|---|---|
| 76 publications × 63 | 4 788 |
| 13 échecs HGGSP (vérification live avant le mapping, ~7) | ~91 |
| **Total avant le premier 403** | **~4 880** |

Le quota primaire REST est de 5 000 requêtes/heure **par utilisateur** : il est
partagé par tous les jetons de cet utilisateur, et donc aussi par toute autre
activité de ce compte dans la même heure.

- **Hypothèse retenue : épuisement du quota primaire.** Elle est cohérente avec
  les faits observés : 403 et non 401, même route, même jeton, un seul jeton,
  retour à 200 après l'arrêt, et `remaining=4999`, c'est-à-dire une fenêtre
  neuve.
- **Condition pour qu'elle tienne :** les 76 publications doivent tenir dans la
  même heure. Les horodatages du journal Worker B le diront.
- **Autre hypothèse, non exclue :** une limitation secondaire.
- **Ce qui l'aggravait :** le worker a continué d'appeler GitHub pendant la
  limitation, à chaque job (406 retries).
- **Ce que la mesure « 4999 après l'arrêt » ne prouve pas :** elle est seulement
  compatible avec une fenêtre neuve. Elle n'exclut pas un épuisement antérieur.

### 2.3 Pin sans placement — explication, chemin existant correct

Un job publie en trois transactions :

1. La promotion `REVIEWED → RETRIEVAL_ELIGIBLE`, dans une transaction control.
2. Les pins, dans une deuxième transaction control, committée **avant** toute
   transaction produit (point de linéarisation d'ADR-0033 § 7bis).
3. Puis revérification live et transaction produit.

Un 403 à l'étape 3 laisse la ressource `RETRIEVAL_ELIGIBLE`, le pin présent, le
placement absent, et le job en file (1/3) : c'est le cas NSI terminale.

La reprise du **même** job repart ainsi :

- les deux événements de promotion portant le même `job_id` sont vérifiés, et
  la promotion est sautée ;
- le pin fait `ON CONFLICT DO NOTHING`, puis est relu octet pour octet ;
- le placement fait `ON CONFLICT DO NOTHING` ;
- les chunks ne sont créés qu'avec l'artefact.

**Épreuve D** (PostgreSQL réel) : l'état est reproduit à l'identique par un 403
injecté APRÈS l'écriture du pin. La reprise publie sans nouvelle promotion
(2 événements), sans second pin (1) et sans doublon. **Aucun changement de ce
mécanisme.**

## 3. Décisions

### 3.1 V4 immuable ; HGGSP exige une release successeur

- ADR-0050 § 1 et § 5 : toute modification d'une autorité qui en change la
  sémantique exige une nouvelle identité.
- ADR-0059 : « une release honnête est un successeur ».
- Ajouter `hggsp` au mapping change `subject_mapping_sha256`. Worker B refuse
  alors de démarrer sur V4 (`release allowlist authority digest differs`), et
  la reprise non-HGGSP serait bloquée elle aussi.

Ce lot ne touche **ni** au fichier scellé de V4, **ni** à aucun SHA, **ni** à
`ClosedMultilevelMapping`, et ne dérive rien du nom de collection. Il fournit
l'autorité de sujets du successeur, sous un **nouveau chemin**
(`eduscol_profile_gate_subjects_hggsp.yml`, `b909c1fb…bb6a`) : c'est le mapping
V4 plus `hggsp: hggsp`, et il résout les onze collections (**épreuve B**). Il
ne peut pas être chargé à la place de celui de V4 : son empreinte diffère.

**La release successeur n'est PAS produite dans ce lot.** Deux choix de
gouvernance non équivalents sont ouverts, voir § 8.

### 3.2 Les 329 non-HGGSP : repris sous V4, AVANT HGGSP

- Leur autorité V4 est valide.
- Seule la vérification live a échoué, sur la limitation.
- Les artefacts sont disjoints de HGGSP : 0 partagé.

Les reprendre ne publie donc rien de HGGSP et ne consomme aucun job HGGSP.

### 3.3 Sélection gouvernée : implémentée par Worker B, jamais par SQL

- `claim_job(collections=…)` réclame un job seulement si la collection de sa
  RESSOURCE figure dans la liste d'autorisation. Les jobs écartés ne sont pas
  modifiés.
- La liste arrive par `--collection` (CLI Worker B).
- Au démarrage, `require_collections_governed(liste)` refuse toute collection
  hors release, ou que les mappings scellés ne résolvent pas. Sans liste, c'est
  toute la release qui est vérifiée, et Worker B **refuse désormais de démarrer
  sur toute la file V4** (**épreuve F**).

### 3.4 GitHub : fail-closed, limitation nommée, cadence

- **Diagnostic sûr.** Un non-200 porte :
  - le statut ;
  - les seuls en-têtes de limitation documentés (`retry-after`,
    `x-ratelimit-*`, `x-github-request-id`, valeurs filtrées) ;
  - le champ `message` du corps, borné à 200 caractères et filtré.

  Aucun en-tête de requête n'est recopié, et le jeton est masqué s'il apparaît.
- **Classification** : `GitHubRateLimitedError`, sous-classe de
  `GitHubAuthorityError`, donc tout appelant existant échoue fermé comme avant.
  Une limitation est reconnue par l'un de ces signes :
  - `Retry-After` ;
  - `x-ratelimit-remaining: 0` (attente jusqu'à `x-ratelimit-reset`) ;
  - un 429 ;
  - un message GitHub qui nomme une limitation.

  Un autre 403 (droits) n'est **pas** une limitation.
- **Worker B.** Une limitation dans la chaîne de causes (jamais le texte) rend
  le job à la file **sans tentative consommée**, pas avant le délai imposé
  (plancher 60 s), via `defer_job_for_external_throttle` : même garde de bail,
  même effet qu'un bail expiré repris.
- **Boucle.** Toute réclamation est suspendue pendant l'attente. Au-delà de
  900 s ou de 3 limitations consécutives, arrêt avec le code **75**.
  `--min-job-interval-s` fixe la cadence et `--max-idle-polls` arrête le
  worker quand la file est vide.
- **Inchangé** : aucune décision mise en cache, les 9 vérifications live par
  publication, aucune permission élargie. Un 403 n'est jamais une approbation
  (**épreuve C**).

## 4. Stratégies

| Ensemble | Stratégie |
|---|---|
| **76 succès** | Intouchés : jobs `succeeded` jamais re-réclamés ; épreuve E : rejeu sans effet, lignes de jobs réussis identiques, aucun doublon produit |
| **329 non-HGGSP** (dont le cas épinglé) | Worker B DI : image corrigée, `--collection` × 9, cadence 60 s (≤ 3 780 GET/h), arrêt 75 sur limitation persistante, `--max-idle-polls 5` ; relance idempotente (`DI_RELAUNCH=1`) |
| **74 HGGSP** | Ni réclamés, ni annulés, ni retentés, ni reportés : empreinte exacte relevée au pré-vol et exigée à la fin ; aucune tentative consommée ; attendent la décision § 8 |

Cible après DI : **9 collections, 263 artefacts, 405 placements, 5678 chunks**
(calculé depuis les fichiers de V4). Cible finale inchangée :
**11 / 315 / 479 / 8268**, atteinte seulement après la décision HGGSP.

## 5. Impacts

- **#262** : reste OUVERTE, approuvée, inchangée. Rien n'a été poussé sur
  `review/dh-v4-staging-20260926`. Elle fonde encore les 405 reprises et les
  74 attestations HGGSP. `closure-check` (DH) refuse tant que HGGSP attend
  (épreuve G) ; le contrôle partiel DI rend `review_closure=NOT_SAFE`.
- **Attestations et jobs existants** :
  - aucune ligne modifiée par ce lot ;
  - la reprise DI ne crée ni attestation ni job ; elle consomme les jobs
    existants des neuf collections ;
  - les 74 attestations et jobs HGGSP V4 restent actifs et en file. Leur sort
    (annulation et invalidation motivées « remplacé par le successeur ») est
    une opération future, gouvernée, APRÈS la publication du successeur.
- **Fermeture future de #262** : `closure-check` (DH) attend 479 publications.
  Une fois les 74 HGGSP V4 invalidées au profit du successeur, un contrôle de
  fermeture qui en tient compte sera nécessaire. Il est hors de ce lot.

## 6. Image et autorisation

- **Nouvelle image : nécessaire.** L'image `sha256:57e0797…` (commit `0569aff6`)
  ne contient pas le correctif.
  - Construction : workflow canonique `.github/workflows/production-image-provenance.yml`
    (`workflow_dispatch`, `main` seulement), APRÈS fusion.
  - Aucun digest n'existe encore. Ce lot n'en invente aucun.
- **Nouvelle autorisation : proposée, inactive.** Le fichier est
  `docs/reports/go_live/authorizations/proposed/staging_v4_partial_recovery_authorization.json`
  (`453f72fc…187b`).
  - Elle est liée par empreinte à DH, V4, au plan DI et à l'identité DI.
  - Son `runtime_image` est `PENDING_BUILD_FROM_MAIN`. Le vérificateur refuse
    toute opération :
    - tant que le fichier n'est pas à l'emplacement canonique ;
    - tant que l'image est en attente ;
    - tant que `origin/main` ne porte pas les mêmes octets.
  - Il refuse aussi toute image qui ne porte pas le correctif :
    - le digest de DH ;
    - un commit sans les marqueurs du correctif ;
    - un commit hors de `main`.
  - Opérations nommées : `partial_readiness_resign`, `partial_readiness_install`,
    `partial_preflight`, `partial_worker_b_publication`,
    `partial_independent_verification`, `partial_closure_check`.
  - La PR d'activation ne sera PAS un pur `git mv` : elle remplacera le bloc
    image par l'image épinglée et sa preuve de provenance.
- **Readiness** : le manifeste signé épingle l'image worker. Une signature
  locale DI (`sign_staging_v4_di_readiness_manifest.sh`) produit
  `staging-readiness-v4-di.json`, déposé à côté de celui de V4, qui n'est
  jamais remplacé.

## 7. Fichiers

Code (`services/rag-engine/src/ingestor/`) :
- `ingestion_control/github_authority.py` : diagnostics sûrs,
  `GitHubRateLimitedError`, classification.
- `ingestion_control/jobs.py` : `claim_job(collections=…)`,
  `defer_job_for_external_throttle`.
- `ingestion_worker/publication_resume.py` : report sur limitation, liste
  d'autorisation.
- `ingestion_worker/multilevel_publication_resume_cli.py` : `--collection`,
  `--min-job-interval-s`, `--rate-limit-max-wait-s`,
  `--max-consecutive-rate-limits`, `--max-idle-polls`, contrôle de démarrage,
  boucle extraite `_run_worker_loop`.
- `multilevel_verified_placement.py` : `ungoverned_release_collections`,
  `require_collections_governed`.

Autorité : `services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml` (nouvelle).

Go-live :
- `scripts/go_live/check_staging_authorization.py` : section DI.
- `scripts/go_live/staging_v4_partial_recovery.py` : outil.
- `scripts/go_live/staging_v4_partial_recovery.sh` : orchestrateur.
- `scripts/go_live/sign_staging_v4_di_readiness_manifest.sh`.
- `scripts/go_live/staging_retrieval_probe.py` : `--collection`.
- `docs/reports/go_live/recovery/di_partial_v4_262.json`.
- `docs/reports/go_live/authorizations/proposed/staging_v4_partial_recovery_authorization.json`.
- `docs/runbooks/staging_v4_partial_recovery_DI_EXECUTION_PLAN.md`.

Tests :
- `services/rag-engine/tests/test_lot41a_github_authority_transport.py` :
  +10 épreuves de limitation, faux GitHub étendu.
- `services/rag-engine/tests/test_di_worker_b_rate_limit.py` (nouveau).
- `services/rag-engine/tests/test_di_release_subject_governance.py` (nouveau,
  vrais fichiers V4).
- `services/rag-engine/tests/integration/test_di_partial_recovery_pg.py`
  (nouveau, PostgreSQL réel).
- `services/rag-engine/tests/_local_github.py` : injection de panne.
- `services/rag-engine/tests/test_multilevel_worker_cli.py` : trois
  résolveurs factices exposent la nouvelle méthode.
- `scripts/qualification/tests/test_staging_v4_partial_recovery.py` (nouveau).

Non modifiés :
- le mapping scellé de V4 et tout artefact scellé ;
- les migrations et les GRANT ;
- l'autorisation DH, l'outil DH et `closure-check` ;
- #262 et sa branche.

## 8. Décision humaine requise : le successeur HGGSP

Deux voies conformes aux ADR, non équivalentes :

| | A. Successeur complet (V5 = 11 collections, 479) | B. Successeur complémentaire (2 collections HGGSP, 74) |
|---|---|---|
| Identité | Nouvelle, remplace V4 comme release de référence | Nouvelle, coexiste avec V4 (9 collections sous V4, 2 sous V5) |
| Les 405 déjà publiés sous V4 | Adoption par V5 (ADR-0059 § 5, table d'adoption) ou republication : décision distincte | Restent des publications V4 |
| Revue, attestations, jobs | 479 (ou 74 + adoption de 405) | 74 |
| Scopes de retrieval | Successeurs V5 pour les 11 | Successeurs V5 pour les 2 HGGSP seulement |
| Surface de gouvernance | Plus grande, lignée unique | Plus petite, lignée mixte par collection |

Dans les deux cas :
- **Producteur.** Le producteur canonique ne peut PAS produire le successeur
  tel quel : il recopie l'autorité de sujets de V1 en mode rehearsal, et
  `build_profile_gate_successor.sh` exige `PDF_ROOT`, c'est-à-dire les PDF
  réels, absents du cloud. Il faut le faire re-dériver
  `subject_mapping_sha256` depuis le nouveau chemin, avec motif et commit cité
  (`--authority-change-motive`). C'est un lot rag-pedago, exécuté sur le poste
  qui porte les PDF.
- **Chaîne complète à refaire pour le successeur :** readiness, arguments
  Worker B, r4 et revue de scopes, revue batch, attestations, jobs.
- **Fin des HGGSP V4 :** les 74 jobs et attestations HGGSP V4 sont clos par une
  opération gouvernée, après la publication du successeur.

Recommandation : **B**, sous réserve. Son périmètre suffit à la seule cause
(HGGSP), il ne republie ni n'adopte 405 placements sains, et il réduit la
revue humaine à 74 attestations. Le choix reste humain : il fixe la lignée de
release servie par collection.

## 9. Qualification (session cloud, code au commit `653ef792`)

Le commit suivant ne modifie que ce rapport.

| Suite | Environnement | Résultat |
|---|---|---|
| `services/rag-engine` unitaires (`-m "not integration"`) | venv du service, `PYTHONPATH=src` | **4205 tests, 0 échec**, 16 ignorés |
| `ruff check .` + `mypy src` (rag-engine) | idem | propres (149 fichiers) |
| `scripts/qualification/tests` | environnement du job CI | **772 tests, 0 échec**, 4 ignorés (préexistants) |
| Ciblés DI + DH (PostgreSQL jetable, Docker) | `NEXUS_DH_RECOVERY_PG=1 NEXUS_DI_RECOVERY_PG=1` | **80 tests, 0 échec** : DH 25, DI 1 (parcours), transport GitHub 25 (dont 10 de limitation), Worker B 18, gouvernance des sujets 11 |
| `scripts/tests` | environnement du job CI | 552 tests, **4 échecs préexistants** (`test_go_live_readiness`, `disk_policy_ok` : dépendent de l'espace disque du conteneur ; identiques sur `0cb6dde7`) |
| Contrôles du dépôt (`check-repository-hygiene`, `check-authority-uniqueness`, topologie CI) | local | verts |
| `scripts/check-governance-locks.sh` | local | OK, 18 clés conformes |

Contre-épreuves de mutation du parcours PostgreSQL DI :

- sans le report sur limitation, l'épreuve C échoue (`retried` au lieu de
  `rate_limited`) ;
- sans le filtre de collections, les épreuves E/F échouent (des jobs exclus
  sont réclamés).

Non exécuté ici :

- le CLI Worker B sur E5 réel (poste opérateur) ;
- l'orchestrateur sur l'hôte ;
- la construction de l'image.

## 10. Risques résiduels

- **Cause du 403 non prouvée.** L'hypothèse primaire est quantitativement
  étayée ; la confirmer par les horodatages du journal. La cadence de 60 s
  couvre les deux hypothèses, et une limitation persistante arrête proprement
  (code 75, file intacte).
- **Quota partagé.** Le quota primaire est commun à tout ce qui utilise le
  compte du jeton : éviter d'autres usages de ce compte pendant la reprise
  (~5,5 h pour 329 jobs à 60 s).
- **Embeddings de test.** Le banc PostgreSQL DI utilise des embeddings de test
  (identité DEBUG), comme DH. Le CLI Worker B sur E5 réel reste une épreuve du
  poste opérateur.
- **Orchestrateur.** Il n'est éprouvé qu'en essai à blanc hors ligne et par
  ses gardes sourcées. Aucune exécution sur l'hôte.
- **Pas d'ADR.** Aucun ADR n'est ajouté. Le report sans tentative est une
  sémantique de file nouvelle, bornée à une cause extérieure (limitation
  GitHub) ; elle n'affaiblit aucune vérification d'ADR-0033. Un ADR peut
  l'inscrire si le relecteur le demande.

## 11. Prochaine action opérateur exacte

1. Relire et approuver la PR DI, puis la fusionner. C'est une décision humaine.
2. Sur `main` fusionné : `Actions → production-image-provenance → Run workflow`
   (branche `main`). Relever ensuite le digest `rag-multilevel-worker-production`
   et l'inventaire `NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1`.
3. Demander la PR d'activation DI, qui porte l'image épinglée et sa preuve.
4. Trancher § 8 (A ou B) pour HGGSP. Rien ne touche HGGSP d'ici là.
