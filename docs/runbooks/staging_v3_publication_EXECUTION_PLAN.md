# Plan d'exécution — publication de V3 sur le staging cloisonné (lot CY)

Autorisation : `docs/reports/go_live/authorizations/staging_v3_publication_authorization.json`,
qui complète `staging_ssh_authorization.json` (liée par empreinte) sans le
modifier. Orchestrateur : `scripts/go_live/staging_v3_publication.sh`.

Release : `production-profile-gate-2026-2027-v3`, manifeste
`c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16` —
11 collections, 315 artefacts, 479 placements, 8 268 chunks, actualité servie
`official_snapshot`. Prédécesseur V2 (`e9506f5a…`) : nommé pour le rattrapage
d'attribution et l'adoption **seulement** ; sa publication est interdite.

## 0. Préconditions (aucune n'est supposée)

| Précondition | Vérifiée par |
|---|---|
| autorisation de base valide et fusionnée | `check_staging_authorization.py` (code 0) |
| autorisation V3 fusionnée, liée à la base et à ce plan par empreinte | `check_staging_authorization.py --operation <op> --cible <json>` avant **chaque** étape |
| image worker par digest, provenance vérifiée | autorisation V3 `runtime_image` + preuve `staging_worker_image_provenance_cy.json` |
| manifeste de readiness signé nommant V3 (et V2 si rattrapage) pour cette image | gate `enforce_staging_readiness_gate` du worker |
| hôte `nexus-prod`, projet `nexus-staging`, conteneur exact `nexus-staging-pgvector-1` | mesure de pré-vol |
| base `ragdb` ; produit : schéma `public` ; contrôle : schéma `ingestion_control` | mesure de pré-vol |
| disque de l'hôte : au moins deux fois la taille de `ragdb` libre sous `/srv/nexus-staging/backups` | mesure de pré-vol |

## 1. Rôles — jamais confondus

| Rôle | Utilisé par | Jamais transmis à |
|---|---|---|
| superutilisateur du conteneur (`POSTGRES_USER`) | runners canoniques de migration et de provisionnement | tout worker |
| `ingestion_control_app` | Worker A (ingestion scellée, rattrapage), Worker B | — |
| `ingestion_control_attestor` | adoption, proposition et enregistrement de la revue batch | Worker B |
| `ingestion_control_authority` | aucune étape de ce plan | tous |
| `rag_publisher` | Worker B, écriture produit | runners, attestor |
| `rag_reader` | vérification et retrieval | — |

## 2. Étapes, dans l'ordre

Chaque étape s'arrête au premier écart. L'état est écrit dans un répertoire
local (`STATE_DIR`, 0700) ; une étape terminée n'est rejouée que si sa
post-condition ne se vérifie plus.

1. **`preflight_measurement`** (lecture) — disque, conteneurs du projet, têtes
   réelles `public.rag_schema_migrations` et `ingestion_control.schema_migrations`,
   comptes `ingestion_control.resources` / `artifacts` / `artifact_attributions`,
   présence de `psql` sur l'hôte. Décide du chemin :
   * **A** — aucune ressource acquise : ingestion scellée de V3 ;
   * **B** — les 479 placements V2 acquis : rattrapage puis adoption ;
   * tout autre état : **arrêt**, écart à instruire.
2. **`backup_before_migration`** — `pg_dump -Fc ragdb` vers
   `/srv/nexus-staging/backups/cy-<horodatage>/`, empreinte consignée. Jamais
   supprimée par ce plan.
3. **`product_migrations`** — dépôt de l'hôte au commit autorisé, puis
   `PGVECTOR_CONTAINER=nexus-staging-pgvector-1 BACKUP_ROOT=/srv/nexus-staging/backups
   ./scripts/apply_pgvector_migrations.sh` ; tête mesurée = 5.
4. **`control_migrations`** — `provision_and_bootstrap_ingestion_control.sh`
   (migrations manquantes dans l'ordre, **puis** provisionnement des rôles :
   une migration n'accorde aucun droit) ; tête mesurée = 18.
5. **`model_artifact_install`** — l'artefact E5 de l'hôte doit porter
   l'inventaire que V3 déclare (`58ad18db…`). Mesuré au pré-vol ; s'il manque,
   copie de `e5-large-prerentree-2026-2027-20260828-materialise` vers
   `/srv/nexus-staging/models/`, puis revérification de `SHA256SUMS` et de
   chaque fichier. Aucun artefact existant n'est écrasé.
6. **`readiness_manifest_install`** — dépôt, sous `/srv/nexus-staging/readiness/`
   (0600), des manifestes signés localement par le détenteur de la clé
   (`sign_staging_v3_readiness_manifests.sh`) : `staging-readiness-v3.json`
   (V3, image autorisée) et, pour le chemin B seulement,
   `staging-readiness-v2-backfill.json` (V2, validité courte). Chaque étape
   worker désigne explicitement le manifeste qui la couvre.
7. **`transfer_manifest_v3`** (lecture) — rehachage des 315 objets de
   `/srv/nexus-staging/artifact-store` ; manifeste `NEXUS-STAGING-ARTIFACT-TRANSFER-V1`
   au `release_id` de V3, empreinte consignée. Un objet absent ou divergent : arrêt.
8. **`sealed_ingestion_v3`** (chemin A) — `sealed_release_ingestion_cli` sur V3,
   rôle `ingestion_control_app`, onze autorisations LOT41A.
9. **`attribution_backfill_v2`** (chemin B) — `sealed_release_ingestion_cli
   --only-attributions` sur V2 ; attendu `examined=479 written=479 missing_rows=0`,
   identités historiques inchangées (prouvé sur banc isolé,
   `test_v2_backfill_v3_adoption_real_releases.py`).
10. **`adoption_v3`** (chemin B) — `attest_publication_cli adopt-predecessor-release`,
   rôle attestor ; attendu `placements=479 written=479`, bijection.
11. **`batch_review_proposal`** — `propose-release-batch-review`, rôle attestor,
   chaîne PII V3 (jeu `1b70d91b…`, reçu `22361dd1…`). L'artefact est soumis en PR :
   **approbation humaine requise** ; l'orchestrateur s'arrête ici.
12. **`batch_review_record`** — `record-release-batch-attestation` au head exact
    approuvé, dans la fenêtre de validité.
13. **`worker_b_publication`** — `multilevel_publication_resume_cli`, rôle
    `ingestion_control_app` et DSN produit `rag_publisher` distinct ; seuls les
    placements couverts par l'attestation enregistrée.
14. **`independent_verification`** (lecture) — relecture des deux schémas :
    `RETRIEVAL_ELIGIBLE`, jobs, artefacts, droits, type, provenance, placements
    par collection, chunks (modèle, dimension) ; comptes 11/315/479/8 268 **et**
    identités ; actualité `official_snapshot` ; retrieval par le tunnel
    `127.0.0.1:18003`.

## 3. Arrêts

Toute précondition non satisfaite, tout écart mesuré, toute signature ou
approbation manquante. Arrêt de sécurité : arrêt des processus lancés par ce
plan ; **jamais** `docker compose down -v`, jamais de suppression de volume, de
sauvegarde ou de preuve.

## 4. Retour arrière

* **Service** : arrêter les processus de ce plan ; rien n'est exposé de plus.
* **Base** : restaurer la sauvegarde de l'étape 2 (`pg_restore`), sur décision
  humaine, ou les scripts `rollback_*` canoniques pour une migration isolée.
* **Gouvernance** : les preuves, attestations et journaux ne sont jamais
  supprimés — un retour arrière du service n'efface pas ce qui a eu lieu.

## 5. Interdits

Ni publication de V2, ni base, service, secret ou ingestion de production, ni
modification de Nginx, DNS ou certificat, ni bascule `current`, ni exposition
publique, ni build sur l'hôte, ni `docker prune`, ni suppression de volume hors
projet.
