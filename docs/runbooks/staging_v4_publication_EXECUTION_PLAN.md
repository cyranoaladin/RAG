# Plan d'exécution — publication de V4 sur le staging cloisonné (lot DB)

Autorisation : `docs/reports/go_live/authorizations/staging_v4_publication_authorization.json`,
qui complète `staging_ssh_authorization.json` (liée par empreinte) sans le
modifier. Orchestrateur : `scripts/go_live/staging_v4_publication.sh`.

Release : `production-profile-gate-2026-2027-v4`, manifeste
`bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be`. Elle
compte 11 collections, 315 artefacts, 479 placements et 8 268 chunks. Elle
sert l'actualité `official_snapshot` et la visibilité `internal`, et chaque
collection porte son programme officiel (ADR-0061). Ses profils sont ceux de
`v3_livraison_315`.

Les prédécesseurs V2 et V3 ne sont ni publiés ni adoptés. Cette autorisation
couvre le **chemin direct seul** : reprendre des lignes acquises sous V2
changerait leur `placement_id` et leur programme, et ADR-0061 réserve cette
reprise à une décision distincte.

## 0. Préconditions (aucune n'est supposée)

| Précondition | Vérifiée par |
|---|---|
| autorisation de base valide et fusionnée | `check_staging_authorization.py` (code 0) |
| autorisation V4 fusionnée, liée à la base et à ce plan par empreinte | `check_staging_authorization.py --operation <op> --cible <json>` avant **chaque** étape |
| image worker et image de sonde par digest, même commit (`0569aff6`, fusion de #251), provenance vérifiée | `runtime_image`, `probe_image` + `staging_worker_image_provenance_db.json` |
| manifeste de readiness de staging signé nommant V4, son manifeste et l'image worker | gate `enforce_staging_readiness_gate` ; Worker B en déduit sa qualification (ADR-0060) |
| PR #252 (onze r4) **ouverte**, approuvée à son HEAD `2590a172…`, check épinglé vert | revérifié en direct par `authorize_scope_cli` à l'enregistrement |
| hôte `nexus-prod`, projet `nexus-staging`, conteneur exact `nexus-staging-pgvector-1` | mesure de pré-vol |
| base `ragdb` vierge d'acquisition : 0 ressource, 0 artefact, 0 placement produit | mesure de pré-vol ; sinon **arrêt** |
| disque de l'hôte : au moins deux fois la taille de `ragdb` libre sous `/srv/nexus-staging/backups` | mesure de pré-vol |

## 1. Rôles — jamais confondus

| Rôle | Utilisé par | Jamais transmis à |
|---|---|---|
| superutilisateur du conteneur (`POSTGRES_USER`) | runners canoniques de migration et de provisionnement | tout worker |
| `ingestion_control_authority` | enregistrement des r4, conteneur ponctuel dédié | tout worker, l'attestor |
| `ingestion_control_app` | Worker A (ingestion scellée), Worker B | — |
| `ingestion_control_attestor` | proposition et enregistrement de la revue batch | Worker B |
| `rag_publisher` | Worker B, écriture produit | runners, attestor |
| `rag_reader` | vérification et sonde de retrieval | — |

## 2. Étapes, dans l'ordre

Chaque étape s'arrête au premier écart. L'état est écrit dans un répertoire
local (`STATE_DIR`, 0700). Une étape terminée n'est rejouée que si sa
post-condition ne se vérifie plus.

1. **`preflight_measurement`** (lecture) :
   * mesures : disque, conteneur, têtes réelles des deux schémas, comptes
     `resources`, `artifacts` et placements produit ;
   * fichiers d'environnement : présence et mode, noms seulement ;
   * présence de `psql` sur l'hôte.

   Toute ligne acquise entraîne un **arrêt** (reprise hors de cette
   autorisation).
2. **`backup_before_migration`** : `pg_dump -Fc ragdb` vers
   `/srv/nexus-staging/backups/db-<horodatage>/`, empreinte consignée. Ce
   plan ne supprime jamais cette sauvegarde.
3. **`product_migrations`** : le dépôt de l'hôte est placé au commit autorisé,
   puis `apply_pgvector_migrations.sh` s'exécute sur le conteneur exact.
   Tête mesurée : 5.
4. **`control_migrations`** : `provision_and_bootstrap_ingestion_control.sh`
   applique les migrations manquantes dans l'ordre, dont 019 (autorités de
   publication liées), **puis** provisionne les rôles. Tête mesurée : 19.
5. **`model_artifact_install`** : l'artefact E5 de l'hôte doit porter
   l'inventaire que V4 déclare (`58ad18db…`). S'il manque, il est copié puis
   revérifié. Aucun artefact existant n'est écrasé.
6. **`readiness_manifest_install`** : `staging-readiness-v4.json`, signé
   localement par le détenteur de la clé (`sign_staging_v4_readiness_manifests.sh`),
   est déposé sous `/srv/nexus-staging/readiness/` (0600).
7. **`transfer_manifest_v4`** (lecture) : les 315 objets du magasin sont
   rehachés. Un manifeste `NEXUS-STAGING-ARTIFACT-TRANSFER-V1` est produit au
   `release_id` de V4. Un objet absent ou divergent entraîne un arrêt.
8. **`scope_authorization_registration_r4`** : `authorize_scope_cli
   record-authorization` enregistre les onze r4 (identifiants dérivés de V4
   par le générateur), dans un conteneur ponctuel qui reçoit seul le DSN
   authority. La CLI relit en direct la revue de #252 et chaque artefact à son
   HEAD approuvé, puis scelle la revue (ADR-0058). **#252 est fusionnée
   ensuite.**
9. **`sealed_ingestion_v4`** : `sealed_release_ingestion_cli` sur V4, rôle
   `ingestion_control_app`, onze `--scope-authorization collection=r4`.
   Attendu : 479 ressources, `NEEDS_REVIEW`, aucune écriture produit.
10. **`batch_review_proposal`** : `propose-release-batch-review`, rôle
    attestor, chaîne PII réelle (jeu `1b70d91b…`, reçu `22361dd1…`, qui expire
    le 2026-10-23). L'artefact est soumis en PR : **approbation humaine
    requise**, et l'orchestrateur s'arrête ici.
11. **`batch_review_record`** : `record-release-batch-attestation` au HEAD
    exact approuvé, dans la fenêtre de validité.
12. **`worker_b_publication`** : `multilevel_publication_resume_cli`, rôle
    `ingestion_control_app`, avec un DSN produit `rag_publisher` distinct. Il
    démarre en `authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION`, qualifié
    par la readiness de staging vérifiée. Seuls les placements couverts par
    l'attestation enregistrée sont publiés, et leurs chunks sont exactement
    ceux que V4 scelle.
13. **`independent_verification`** (lecture) :
    * comptes 11/315/479 et 8 268 chunks, programme et visibilité relus ;
    * puis la **sonde de retrieval** (`staging_retrieval_probe.py`), dans
      l'image ingestor épinglée, en conteneur ponctuel, rôle `rag_reader`.

    Pour chacune des onze collections, la sonde :
    * signe un jeton `teacher` sous le scope V4 émis ;
    * interroge chaque chunk publié par son vecteur et pose une requête
      lexicale ;
    * exige qu'aucun candidat ne sorte du jeu publié et que le rôle `student`
      soit refusé ;
    * ne compte un refus dense que s'il est constaté à sa source.

## 3. Arrêts

Toute précondition non satisfaite, tout écart mesuré, toute signature ou
approbation manquante, toute ligne acquise au pré-vol. Un arrêt de sécurité
arrête les processus lancés par ce plan. Il n'exécute **jamais**
`docker compose down -v`, et ne supprime jamais ni volume, ni sauvegarde, ni
preuve.

## 4. Retour arrière

* **Service** : arrêter les processus de ce plan ; rien n'est exposé de plus.
* **Base** : restaurer la sauvegarde de l'étape 2 (`pg_restore`), sur décision
  humaine, ou lancer les scripts `rollback_*` canoniques pour une migration
  isolée.
* **Gouvernance** : les preuves, attestations et journaux ne sont jamais
  supprimés. Un retour arrière du service n'efface pas ce qui a eu lieu.

## 5. Interdits

Ce plan n'autorise jamais :
* la publication de V2 ou de V3 ;
* une adoption ;
* l'usage d'une base, d'un service, d'un secret ou d'une ingestion de
  production ;
* une modification de Nginx, du DNS ou d'un certificat ;
* une bascule `current` ou une exposition publique ;
* un build sur l'hôte ;
* `docker prune`, ou une suppression de volume hors du projet.
