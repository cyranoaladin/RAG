# Plan d'exécution — publication de V4 sur une base staging dédiée (lots DB, DC)

**Autorisation :** `docs/reports/go_live/authorizations/staging_v4_publication_authorization.json`
(lot DC). Elle remplace celle du lot DB, jamais consommée, et complète
`staging_ssh_authorization.json`, à laquelle elle est liée par empreinte, sans
la modifier.

**Orchestrateur :** `scripts/go_live/staging_v4_publication.sh`, lancé depuis
un checkout de `main` qui porte l'autorisation.

**Release :** `production-profile-gate-2026-2027-v4`, manifeste
`bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be`. Elle
compte 11 collections, 315 artefacts, 479 placements et 8 268 chunks. Elle
sert l'actualité `official_snapshot`, la visibilité `internal` et le
programme officiel de chaque collection (ADR-0061).

**Base :** `ragdb_profile_gate_v4`, une base **dédiée**, créée additivement
dans le cluster du conteneur `nexus-staging-pgvector-1`.

`ragdb` porte l'acquisition V2 (479 ressources, restées en `NEEDS_REVIEW`) et
26 placements pilotes du 27/08. Elle reste **intacte et hors du chemin V4** :
- le pré-vol la mesure (têtes, comptes, empreintes des lignes) ;
- chaque étape qui écrit la revérifie ensuite ;
- la moindre variation arrête le plan.

## 0. Préconditions (aucune n'est supposée)

| Précondition | Vérifiée par |
|---|---|
| autorisation de base valide et fusionnée | `check_staging_authorization.py` (code 0) |
| autorisation V4 (DC) fusionnée, liée à la base et à ce plan par empreinte | `check_staging_authorization.py --operation <op> --cible <json>` avant **chaque** étape |
| images worker et de sonde par digest, du même commit (`0569aff6`) | `runtime_image`, `probe_image` + `staging_worker_image_provenance_db.json` |
| base dédiée absente, ou présente et **vierge** | pré-vol (`TARGET_EXISTS`, `TARGET_ROWS`) ; tout contenu est un refus |
| chaque mot de passe source authentifie son rôle (huit rôles) | pré-vol, connexion en lecture seule à `ragdb`, sans afficher de valeur |
| `infra/.env` du checkout serveur ne fixe ni base ni conteneur | pré-vol, puis revérifié avant la migration produit |
| `psql` et `python3` sur l'hôte | pré-vol |
| manifeste de readiness de staging signé nommant V4 et l'image worker | gate de readiness ; Worker B en déduit sa qualification (ADR-0060) |
| jeton GitHub en lecture présent en 0600 sous 0700 | contrôlé avant chaque conteneur qui le monte, jamais lu par l'orchestrateur |
| PR #252 (onze r4) **ouverte**, approuvée à son HEAD `2590a172…`, check épinglé vert | revérifié en direct par `authorize_scope_cli` à l'enregistrement |

## 1. Rôles, jamais confondus

| Rôle | Utilisé par | Jamais transmis à |
|---|---|---|
| superutilisateur du conteneur (`POSTGRES_USER`) | `createdb` et runners canoniques de migration et de provisionnement | tout conteneur |
| `ingestion_control_migrator` | provisionné par le runner de contrôle | tout conteneur |
| `ingestion_control_authority` | enregistrement des r4, dans un conteneur ponctuel dédié | tout worker, l'attestor |
| `ingestion_control_app` | Worker A et Worker B | — |
| `ingestion_control_attestor` | proposition et enregistrement de la revue batch | Worker B |
| `rag_publisher` | Worker B, écriture produit | runners, attestor |
| `rag_reader` | sonde de retrieval | — |
| `rag_reviewer` | droits posés par le runner produit ; non utilisé par ce plan | — |

Les conteneurs ne reçoivent que des fichiers **par rôle**, placés sous
`/srv/nexus-staging/secrets/v4-roles/` (0700, fichiers 0600), plus
`readiness.env`, qui ne contient aucun DSN. `staging.env` et
`ingestion_control.env` ne sont jamais montés : seules les étapes de
migration et de dérivation les lisent, sur l'hôte.

## 2. Étapes, dans l'ordre

Chaque étape s'arrête au premier écart. L'état est tenu dans `STATE_DIR`
(0700).

1. **`preflight_measurement`** (lecture seule) : toutes les préconditions de
   la section 0 sont mesurées. La référence de `ragdb` est enregistrée dans
   `legacy_baseline.txt`, et l'état de la base dédiée (`absente` ou `vierge`)
   dans `cible`.
2. **`backup_before_migration`** : `pg_dump -Fc ragdb` (lecture) vers
   `/srv/nexus-staging/backups/dc-<horodatage>/`, en 0600. Le cluster va
   changer (nouvelle base, droits) ; `ragdb`, non.
3. **`database_creation`** : `createdb -T template0 -E UTF8 --locale=C
   ragdb_profile_gate_v4`, à l'identique de `ragdb` (UTF8/C/C). Une base de
   ce nom déjà présente est un refus (`BASE_DEJA_PRESENTE`), sauf reprise :
   si le pré-vol l'a trouvée vierge, l'étape la revérifie vierge et
   n'exécute pas `createdb`. Après : encodage vérifié, base vide, `ragdb`
   inchangée.
4. **`product_migrations`** : `apply_pgvector_migrations.sh` avec
   `PGVECTOR_DB=ragdb_profile_gate_v4`.
   - Avant : tête 0 sur la base dédiée.
   - Le runner applique 001 à 005 dans l'ordre et pose, à 004, les droits
     de `rag_reader`, `rag_reviewer` et `rag_publisher`. Les rôles existent :
     aucun mot de passe n'est changé.
   - Après : tête 5, `ragdb` inchangée (tête produit 4).
5. **`control_migrations`** : `provision_and_bootstrap_ingestion_control.sh`
   avec `PGDATABASE=ragdb_profile_gate_v4`.
   - Avant : tête 0.
   - Le runner applique 001 à 019, puis provisionne les quatre rôles de
     contrôle. Leurs `ALTER ROLE … PASSWORD` réimposent les valeurs en
     vigueur, que le pré-vol a vérifiées.
   - Après : tête 19, `ragdb` inchangée (tête contrôle 15).
6. **`role_env_derivation`** : `scripts/go_live/staging_v4_role_env.py`
   s'exécute sur l'hôte. Il reçoit les valeurs **par l'environnement** (les
   deux fichiers sources, sourcés), jamais par argument.
   - Il écrit cinq fichiers de façon atomique : `ingestion-control-app.env`,
     `ingestion-control-attestor.env`, `ingestion-control-authority.env`,
     `rag-publisher.env` et `rag-reader.env`.
   - Chaque fichier contient un DSN libpq vers la base dédiée.
   - Aucun nouveau secret n'est créé, et un contenu différent n'est jamais
     écrasé.
   - Après : chaque fichier doit authentifier **son** rôle sur **la base
     dédiée**.
7. **`model_artifact_install`** : l'artefact E5 que V4 déclare,
   `e5-large-prerentree-2026-2027-20260828-materialise`, avec
   l'inventaire `SHA256SUMS` = `58ad18db…`. Il n'est pas sur l'hôte (le
   pré-vol DB a mesuré `e2c7384b…` pour `models/e5-large`).
   - Avant copie : inventaire et fichiers revérifiés sur le poste.
   - Copie par `rsync` vers `<nom>.partiel` (0700/0600), revérification de
     l'inventaire et de chaque fichier sur l'hôte, puis renommage.
   - Un artefact existant n'est jamais écrasé.
8. **`readiness_manifest_install`** : dépôt de `staging-readiness-v4.json`
   (0600), signé localement par le détenteur de la clé.
9. **`transfer_manifest_v4`** (lecture) : rehachage des 315 objets du magasin.
10. **`scope_authorization_registration_r4`** : jeton présent, puis
    `authorize_scope_cli record-authorization` pour chacune des onze r4, dans
    le conteneur qui ne reçoit que `ingestion-control-authority.env`. Cette
    étape a lieu pendant que #252 est ouverte ; **#252 est fusionnée
    ensuite**.
11. **`sealed_ingestion_v4`** : la base dédiée doit être vierge (0 ressource,
    0 placement). Ensuite, `sealed_release_ingestion_cli` sous les onze r4 ;
    attendu : 479 ressources.
12. **`batch_review_proposal`** : chaîne PII réelle (jeu `1b70d91b…`, reçu
    `22361dd1…`, qui expire le 2026-10-23). **Approbation humaine requise** ;
    l'orchestrateur s'arrête ici.
13. **`batch_review_record`** : au HEAD exact approuvé.
14. **`worker_b_publication`** : démarrage exigé en
    `RELEASE_BOUND_STAGING_QUALIFICATION` ; les chunks publiés sont
    exactement ceux que V4 scelle.
15. **`independent_verification`** (lecture) : la base dédiée doit compter
    11/315/479 et 8 268 chunks. Puis la sonde de retrieval
    (`staging_retrieval_probe.py`) tourne dans l'image ingestor épinglée,
    sous `rag-reader.env`, donc sur la base dédiée. Enfin, `ragdb` est
    revérifiée inchangée.

## 3. Arrêts

Les causes d'arrêt :
- une précondition non satisfaite ;
- un écart mesuré ;
- une signature ou une approbation manquante ;
- un contenu trouvé dans la base dédiée ;
- une variation de `ragdb`.

Un arrêt de sécurité arrête les processus lancés par ce plan. Il ne supprime
jamais ni base, ni volume, ni sauvegarde, ni preuve.

## 4. Retour arrière

* **Service** : arrêter les processus de ce plan. Le service API continue
  de pointer vers `ragdb` : ce plan ne le bascule pas.
* **Base dédiée** : l'abandonner, sur décision humaine. `ragdb` n'a jamais
  été touchée.
* **Rôles** : leurs mots de passe sont ceux en vigueur (vérifiés au
  pré-vol). La sauvegarde de l'étape 2 reste disponible.
* **Gouvernance** : les preuves, attestations et journaux ne sont jamais
  supprimés.

## 5. Interdits

Ce plan n'autorise jamais :
- la modification ou la suppression de `ragdb` ;
- la suppression des données V2 ;
- la réutilisation des 26 placements pilotes dans la qualification V4 ;
- la publication de V2 ou de V3, ni une adoption ;
- l'usage d'une base, d'un service, d'un secret ou d'une ingestion de
  production ;
- la bascule du service API, ni une bascule `current` ;
- une exposition publique ;
- une modification de Nginx, du DNS ou d'un certificat ;
- un build sur l'hôte ;
- `docker prune`, ou une suppression de volume hors du projet.
