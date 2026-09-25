# Lot DH — récupération de la publication V4 après la fermeture de la revue #257

- Branche : `claude/lot-dh-publication-recovery` (session cloud)
- Base : `e8d125eac58ac8176c1fc92c1def63f1210f0883` (main après #258), vérifiée
  égale à `origin/main` (`git ls-remote`) au démarrage.
- Environnement : VM cloud isolée (4 vCPU, 15 Go de RAM, Python 3.11.15,
  PostgreSQL/pgvector jetables sous Docker, image épinglée
  `pgvector/pgvector:pg16@sha256:00ba258a…`). Aucun accès au serveur Nexus,
  aucune base réelle, aucun secret.
- **Cette PR ne vaut pas autorisation d'exécution sur le serveur.**

## 1. Incident (contexte opérateur, NON remesuré ici)

- V4 ingérée dans `ragdb_profile_gate_v4` : 479 ressources, 315 contenus,
  11 collections ; `ragdb` inchangée.
- #257 (revue `lot42-release-batch-v4-staging-20260924`, artefact
  `…-19ba49a2….json`) a été **fusionnée** avant l'usage des attestations.
  Worker B refuse : `human_review is no longer approved
  (reason=pull_request_not_open)`. C'est le comportement prescrit par
  ADR-0033 § 5 ; le protocole LOT42 n'est **pas** modifié.
- Le rôle applicatif ne peut pas persister l'invalidation
  (`_mark_invalidated` échoue sans bruit, par conception) : 479 attestations
  restent « actives » mais inutilisables ; 479 jobs, dont un sous bail lors
  du relevé ; Worker B arrêté ; aucune publication.
- Tête de #257 : `85f9000115df34cab3060a52de6594bebe24c73c`, relevée par
  `git ls-remote origin refs/pull/257/head` (l'API REST GitHub n'est pas
  ouverte à cette session). Le pré-vol DH refuse toute ligne qui ne porte pas
  cette tête.

Ces états peuvent avoir évolué : le pré-vol DH les **constate** avant toute
écriture et s'arrête au moindre écart.

## 2. Ce que la PR ajoute

| Pièce | Rôle |
|---|---|
| `scripts/go_live/staging_v4_publication_recovery.py` | `preview` (lecture seule imposée au serveur), `cancel-stale-jobs` (rôle app), `invalidate-stale-attestations` (rôle attestor, constat live que #257 n'autorise plus rien), `review-precondition` (avant mise en file / avant Worker B), `closure-check` |
| `docs/reports/go_live/recovery/dh_stale_review_257.json` | identité de la revue périmée : dépôt, PR, tête, artefact (empreinte recalculée), base, comptes attendus |
| `scripts/go_live/staging_v4_publication_recovery.sh` | orchestrateur DH : sourcé sur l'orchestrateur V4 (aucune fonction recopiée), contrôle d'autorisation DH par étape, trois arrêts humains |
| `scripts/go_live/check_staging_authorization.py` | section DH : `OPERATIONS_DH`, `GABARIT_DH`, `evaluer_dh`, `verifier_operation_dh` ; V4 inchangée |
| `docs/reports/go_live/authorizations/proposed/staging_v4_publication_recovery_authorization.json` | **proposition** d'autorisation (inactive) : liée par empreinte à l'autorisation de base, à la V4, au plan DH et à l'identité de #257 ; images exigées identiques à la V4 |
| `docs/runbooks/staging_v4_publication_recovery_DH_EXECUTION_PLAN.md` | plan d'exécution DH |
| `services/rag-engine/tests/integration/test_dh_publication_recovery_pg.py` | banc PostgreSQL DH (§ 5) |
| `scripts/qualification/tests/test_staging_v4_publication_recovery.py` | identité, proposition, orchestrateur (sans serveur) |
| `services/rag-engine/tests/integration/_banc_multiniveaux.py` | correction d'un défaut préexistant du banc (§ 6) |

Aucune migration, aucun `GRANT`, aucun artefact scellé, aucun fichier de
permissions, aucun verrou de gouvernance n'est modifié. Aucun code de
`services/rag-engine/src` n'est modifié.

## 3. Conception

### 3.1 L'ensemble exact, pas un compte

L'aperçu rattache une attestation à #257 par sa **clé de revue complète**
(dépôt, PR, tête, chemin d'artefact, digest), puis exige, ligne par ligne :
protocole `LOT42-RELEASE-BATCH-V1` ; `review_id` et
`release_batch_review_digest` de #257 ; les **cinq empreintes de release**
lues dans l'artefact versionné (dont le manifeste `bab9c398…`) ; artefact
existant, de la même ressource, du même contenu, acquis sous V4 ; ressource
de la même collection, `sealed_release_pipeline`, en `NEEDS_REVIEW`, sans
bail actif ; collection et autorisation r4 couvertes par la revue ; une seule
base, un seul relecteur, une seule revue GitHub, un seul blob ; une
autorisation par collection. Puis la **couverture** : l'ensemble attesté est
exactement celui des ressources de la release, et la base ne porte aucune
autre ressource. Côté jobs : type `publication_resume` seulement ; chaque job
nomme une attestation de #257 et la même ressource, le même artefact, le même
run, la clé `publication:<attestation>` et la version d'état courante ; un job
par attestation ; aucun job `succeeded`, aucun pin de commit sous #257.
**Tous** les écarts sont listés ; un seul suffit à refuser.

Deux empreintes d'ensemble en sortent (`attestation_set_sha256`,
`job_set_sha256`). Chaque écriture re-dérive l'ensemble **sous verrou**
(`FOR UPDATE`, `lock_timeout`) et exige ces empreintes ; sinon rien n'est
validé.

### 3.2 Rôles et droits : rien de nouveau

- Annulation : `ingestion_control_app`, qui détient `UPDATE` sur `jobs`
  depuis LOT44e. L'attestor n'a aucun droit sur `jobs` (prouvé en base).
- Invalidation : `ingestion_control_attestor`, qui détient
  `UPDATE (invalidated_at, invalidated_reason)` depuis LOT42. Le rôle app n'a
  aucun `UPDATE` sur les attestations (prouvé en base).
- Worker B : inchangé, aucun privilège ajouté.

### 3.3 Baux, expiration, complétions tardives

- Un job `running` à bail **actif** est un refus : arrêter Worker B, attendre.
- Un bail **expiré** n'est pas une annulation. Il est constaté
  (`running_lease_expired`), puis le job est annulé explicitement avec
  `previous_lease=expired_not_released` et le détenteur précédent. Point
  important relevé à l'examen : la boucle du CLI Worker B appelle
  `reap_expired_job_leases` à **chaque** itération ; relancé avant DH, il
  remettrait ce job en file. Worker B reste donc arrêté jusqu'à l'annulation
  (le pré-vol refuse un Worker B actif).
- Complétion tardive : `complete_job`/`record_job_retry` exigent le jeton de
  bail, `status='running'` et un bail non expiré (`clock_timestamp()`).
  L'annulation efface le bail : toute complétion tardive lève
  `JobLeaseConflictError` (prouvé au banc).
- Baux de **ressources** : un bail actif est un refus ; un bail expiré est
  compté (`resource_leases_expired`) et jamais modifié — DH ne touche aucune
  ressource.
- `dead_letter`/`failed` : terminaux, conservés tels quels.

### 3.4 Historique, motifs, rejeu

- Jobs : `status='cancelled'`, bail effacé, `last_error` **conservé** (le
  refus de Worker B reste lisible), marque ajoutée sous
  `payload.recovery_cancellation` (lot, motif, empreintes, statut, bail et
  détenteur précédents, `cancelled_at`).
- Attestations : `invalidated_at = clock_timestamp()`, motif
  `DH-RECOVERY attestation_set_sha256=<…> : revue cyranoaladin/RAG#257@85f9000115df …(reason=<live>)`.
- Rejeu identique : reconnu par la marque et l'empreinte, **rien n'est
  réécrit** (`deja_annules`, `deja_invalidees`) ; motifs et horodatages
  inchangés (prouvé au banc, instantané complet avant/après).
- Aucune ligne supprimée, aucun ancien job réaffecté : les nouveaux jobs
  portent une nouvelle clé (`publication:<nouvelle attestation>`).

### 3.5 Cycle de vie de la revue

- **r4 (LOT41A-V2)** : preuve scellée (ADR-0058), enregistrée pendant que
  #252 était ouverte ; indépendante de l'état ultérieur de #252.
- **Attestation batch** : revue GitHub revérifiée **en direct** à chaque
  usage (`verify_publication_attestation`), puis un pin de commit
  (`publication_commit_pins`, migration 011) linéarise la décision avant la
  transaction produit.
- Examen des reprises : une ressource interrompue après promotion
  (`RETRIEVAL_ELIGIBLE`, job remis en file par expiration) repasse par
  `verify_publication_attestation` avec `require_content_bound_authority` ;
  le publisher relit en direct et refait le pin. Une PR fermée à ce moment
  bloque la reprise. D'où la **condition de fermeture** (`closure-check`) :
  toutes les ressources `RETRIEVAL_ELIGIBLE`, un pin par attestation active à
  son head, aucun job `publication_resume` en file ou en cours, vérification
  indépendante faite. Avant cela, la PR reste ouverte, approuvée au head
  exact, inchangée.
- **Préconditions** ajoutées, sans retirer aucune vérification par
  publication : avant mise en file et avant le lancement de Worker B, une
  seule revue derrière les attestations actives, différente de #257,
  approuvée en direct au head nommé, artefact relu identique au blob attesté ;
  avant Worker B, chaque job vivant nomme une attestation de cette revue.
- Pas de fusion automatique : l'orchestrateur s'arrête sur `ATTENTE_HUMAINE`.

### 3.6 Code du dépôt ou code de l'image

| Exécuté | Où | Conséquence |
|---|---|---|
| outil DH, mise en file DG | `/repo` (dépôt de l'hôte au commit de l'autorisation DH) dans l'image worker épinglée | n'importe que `nexus_contracts.authority_artifacts` et `ingestor.ingestion_control.github_authority`, présents dans l'image |
| `attest_publication_cli`, Worker B | code de l'image | inchangés |

`git diff 0569aff6 e8d125ea -- services/rag-engine/src packages/*/src` est
**vide** (0569aff6 = commit de build de l'image V4) : l'image épinglée porte
exactement le code qualifié ici. **Aucune reconstruction, aucune nouvelle
readiness** ne sont nécessaires ; la proposition DH exige d'ailleurs des
images identiques à la V4.

## 4. Autorisation : proposée, pas active

La PR DH ne crée **pas** `staging_v4_publication_recovery_authorization.json`
à son chemin canonique : le vérificateur refuse donc toutes les opérations DH
(testé pour chacune). L'activation exige une PR distincte qui déplace
(`git mv`) la proposition vers le chemin canonique, approuvée au head exact
par `abenrhouma` et fusionnée. L'autorisation V4 (DG) n'est ni rejouée ni
modifiée.

## 5. Qualification

### 5.1 Banc PostgreSQL DH (réel, jetable)

`NEXUS_DH_RECOVERY_PG=1 pytest tests/integration/test_dh_publication_recovery_pg.py`
— trois conteneurs `pgvector` épinglés (contrôle du parcours, contrôle
périmé partagé, produit), migrations et rôles réels, **vrais CLI**
(`authorize_scope_cli`, `attest_publication_cli`), vrai outil DG, vrai outil DH
en sous-processus, décision de revue rendue par le code réel d'ADR-0025 sur
`LocalGitHub`.

Parcours `test_recuperation_de_bout_en_bout` :

1. revue de test #7001 approuvée → 4 attestations → 4 jobs (outil DG, rôle app) ;
2. fermeture de #7001 → **vraie itération Worker B** : 4 refus
   `reason=pull_request_not_open`, attestations toujours actives ;
3. un job épuisé (`dead_letter`), un autre réclamé par un worker qui s'arrête
   sous bail (2 s) ;
4. aperçu : `running_lease_active` → refus nommé ; annulation refusée ; base
   inchangée ;
5. mauvais rôle : refus de l'outil **et** `InsufficientPrivilege` de
   PostgreSQL dans les deux sens ;
6. bail expiré → aperçu `{dead_letter:1, queued:2, running_lease_expired:1}`,
   mêmes empreintes → annulation `annules_bail_expire=1 annules_en_file=2
   preserves_dead_letter=1` ; complétion et retry tardifs refusés ;
   `last_error` conservé ;
7. rejeu : `deja_annules=3`, instantané identique ;
8. invalidation refusée tant que #7001 vérifie encore ; puis
   `invalidees=4` ; rejeu `deja_invalidees=4`, instantané identique ;
9. nouvelle revue de test #7002 : projection **réutilisée**
   (`already_present=4`), `written=4`, rejeu `written=0 already_present=4` ;
10. préconditions : #7001 refusée, mauvaise tête refusée, #7002 acceptée ;
    mise en file `crees=4`, rejeu `deja_en_file=4` ; précondition Worker B ;
11. aperçu rejoué : 4 successeurs reconnus, empreinte #257 inchangée ;
    `closure-check` refusé (rien de publié) ;
12. Worker B : 4 publications, plus rien en file ; comptes produit
    (2 artefacts, 4 placements, chunks) ; **retrieval** par le chemin réel ;
13. rejeu après écriture produit : aucun doublon ;
14. `closure-check` accepté ; historique : 4 attestations #7001 invalidées,
    4 #7002 actives ; jobs `{dead_letter:1, cancelled:3, succeeded:4}` ;
    4 pins, tous sous #7002.

Contre-épreuves sur un état périmé partagé : état conforme ; **mauvaise base**
(`ragdb_profile_gate_v4` attendue), **mauvaise revue**, **mauvaise tête** :
aperçu et annulation refusés, base inchangée ; base historique toujours
refusée ; **mêmes comptes, mauvaises identités** — 20 mutations d'un
instantané réel, toutes refusées à compte égal (5 empreintes de release,
release de l'artefact, base/relecteur/identifiant de revue, collection
croisée, autorisation étrangère, contenu, ressource promue, bail de
ressource, jobs échangés, artefact/version/clé du job, job étranger,
ressource hors release, pin) ; **interruption au milieu** d'une annulation et
d'une invalidation : rien n'est validé ; empreinte non approuvée : refus avant
écriture.

**Autorités de test** : #7001/#7002 et les autorisations de scope du banc
sont des fixtures de `LocalGitHub`, jamais des approbations réelles.
**Embeddings de test** : faute d'E5 ici (§ 7), la publication du banc passe par
la vraie itération de Worker B avec `CallableEmbeddingProvider`, l'adaptateur
de test du dépôt dont l'identité de modèle est `DEBUG` ; il ne peut pas se
faire passer pour E5. Le même banc exécute le **vrai CLI Worker B sur E5**
avec `NEXUS_DH_WORKER_B_CLI=1` (préparé, non exécuté ici).

Résultat : **24 réussis sur 24**, aucun skip ni xfail (`rc=0`), en environ 4 minutes.

### 5.2 Autres épreuves

| Épreuve | Résultat |
|---|---|
| `scripts/qualification/tests` en environnement **hermétique** identique à la cible CI (pytest + trois paquets locaux) | 683 réussis, 4 ignorés préexistants (aucun DH), dont 39 tests DH |
| `rag-engine` `make test` (`-m "not integration"`) | 4 136 réussis, 1 ignoré préexistant, 0 échec |
| `ruff check .` (rag-engine) et `ruff` sur les scripts modifiés | conformes |
| `mypy src` (rag-engine) | aucun problème, 149 fichiers |
| `scripts/check-governance-locks.sh` | 18 clés conformes à la référence |
| `scripts/tests/test-governance-locks.sh` | 16/16 |
| essai à blanc hors ligne de l'orchestrateur DH | jusqu'à l'arrêt humain de revue, puis jusqu'au `closure-check` ; #257 refusée |

`scripts/ci-local.sh` complet n'a pas été rejoué : ses cibles rag-engine,
qualification et gouvernance l'ont été ci-dessus ; rag-pedago et cockpit ne
sont pas touchés par ce lot.

## 6. Défaut préexistant corrigé dans le banc multi-niveaux

`_banc_multiniveaux._artefact_de_registre` scellait des empreintes de chunks
fabriquées (`sha256("texte:<contenu>:<index>")`), qu'aucun texte réel ne peut
reproduire. Depuis ADR-0060, le publisher recompare exactement les empreintes
scellées : toute publication batch du banc était donc impossible. Preuve
d'antériorité : au commit parent `e8d125ea` (banc et `src/` identiques), le
chunker canonique suivi de `select_publication_chunks` refuse
(`published chunks differ from the sealed release: 3 produced, 3 sealed`).
Correction : l'empreinte scellée est celle du texte de page extrait (une page
du banc est très en deçà du budget de tokens, quel que soit le tokenizer).
Aucun code de production n'est touché.

## 7. Limites réelles

- **Push impossible depuis cette session** : le proxy git refuse
  `cyranoaladin/RAG` (403, dépôt absent des sources autorisées de la session).
  Tous les commits sont **locaux** ; aucun n'est sur GitHub ; aucune PR n'a pu
  être ouverte.
- API REST GitHub fermée à la session : l'état de #257 et ses revues n'ont pas
  été relus ; la tête vient de `refs/pull/257/head`.
- Modèle E5 : téléchargement refusé par la politique réseau (huggingface.co,
  403). Non exécutés ici : le vrai CLI Worker B sur E5, le banc réel V4
  (`test_v4_staging_direct_real_chain.py`, qui exige aussi les PDF des miroirs
  de l'opérateur).
- Aucune mesure du staging : les états du § 1 restent ceux transmis.

Commandes reproductibles (machine opérateur) :

```bash
cd services/rag-engine
# banc DH avec le vrai CLI Worker B et E5 réel
NEXUS_DH_RECOVERY_PG=1 NEXUS_DH_WORKER_B_CLI=1 \
RAG_EMBEDDING_MODEL_CACHE_DIR=<artefact E5, inventaire 58ad18db…> \
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_dh_publication_recovery_pg.py -q
# essai à blanc de l'orchestrateur DH (aucune connexion)
DRY_RUN_OFFLINE=1 BATCH_REVIEW_ID=<id> EVALUATOR=<identité> \
scripts/go_live/staging_v4_publication_recovery.sh --dry-run run
```

## 8. Prochaines approbations requises

1. Revue et fusion de la PR DH (code, tests, proposition) par le relecteur
   gouverné — elle n'autorise rien sur le serveur.
2. PR d'activation : `git mv` de la proposition vers
   `docs/reports/go_live/authorizations/staging_v4_publication_recovery_authorization.json`,
   approuvée au head exact et fusionnée.
3. Pré-vol DH sur le serveur (lecture seule), relecture humaine de
   `preview.out`, accusé `DH_PREVIEW_ACK=<attestation_set_sha256>`.
4. Nouvelle PR de revue batch avec le nouvel artefact : approuvée au head
   exact et **laissée ouverte** jusqu'au `closure-check`.
5. Décision humaine de fusion ou de fermeture de cette PR après le
   `closure-check`.

Escalade (hors DH, arrêt) : tout pin, placement, chunk ou job `succeeded`
sous #257 ; toute ressource hors `NEEDS_REVIEW` ; tout bail actif persistant.
