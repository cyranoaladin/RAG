# Lot CY — autoriser et outiller la publication de V3 sur le staging cloisonné

- Branche : `go-live/cy-staging-v3-publication-amendment`
- Base : `7c65ec4b9eeeb2db62905e0e258ba3d5ea3e90f4` (main après #250)
- Mandat : construction des images autorisée ; périmètre staging confirmé
  (message du propriétaire, 2026-09-23). Aucune publication ni bascule de
  production n'est autorisée par ce lot.

## 1. Runtime construit

| | |
|---|---|
| Workflow | `production-image-provenance.yml`, run `35919194803`, tentative 1, `workflow_dispatch` sur `main` |
| Commit construit | `7c65ec4b9eeeb2db62905e0e258ba3d5ea3e90f4`, arbre `488818ae3d5ea39f796c667973ab411d50e45706` |
| Worker (A et B, même image) | `ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:f931f59cb75aecacfb88959aa7b0d85302fd7b40e60851bdb8b1c6860dd35002` |
| Ingestor | `ghcr.io/cyranoaladin/rag-ingestor@sha256:360eb30a00fe495d021a78ecd8c7844e000c8716baef73924bd67edcf3cfaa2b` |
| Inventaire de build | artefact `nexus-deployment-image-inventory`, `c0a38691…d727` |
| Preuve | `docs/reports/evidence/staging_worker_image_provenance_cy.json` |

Aucune exécution antérieure n'existait pour ce commit ; un seul build. Le
contenu a été vérifié sur l'image tirée par digest, exécutée hors réseau :
contrats `0.20.0`, points d'entrée d'ingestion scellée, d'attestation, de
Worker B, de readiness et d'adoption importables ; sous-commandes
`adopt-predecessor-release`, `propose-release-batch-review`,
`record-release-batch-attestation`, `verify-release-sources` présentes ; aucune
variable de secret. Le commit de build reste distinct du commit qui
l'autorise : aucun commit documentaire n'impose de reconstruction.

## 2. Ce que le staging contient vraiment, et les deux chemins

Les dernières preuves versionnées (20–21/09) mesurent, sur la base de contrôle
du staging, `ingestion_runs = 0` et `resources = 0` : l'ingestion V2 y a été
bloquée avant exécution, et aucun lot postérieur n'en consigne l'exécution. Le
plan ne suppose donc rien ; le pré-vol mesure et choisit :

- **A** — aucune ressource acquise : ingestion scellée de V3 elle-même ;
- **B** — les placements V2 acquis : rattrapage d'attribution, puis adoption.

## 3. Rattrapage V2 et adoption V3, éprouvés sur banc isolé

`services/rag-engine/tests/integration/test_v2_backfill_v3_adoption_real_releases.py`
(gardé par `NEXUS_REAL_RELEASE_ADOPTION=1`), sur les **vrais** fichiers V2/V3 et
les vraies commandes, PostgreSQL jetable :

- `--only-attributions` sur V2 : `examined=479 written=479 already_present=0
  missing_rows=0` ; ressources, artefacts (empreintes de payload comprises),
  candidats et 4 790 transitions identiques avant et après ; seule
  `artifact_attributions` passe de 0 à 479 ; rejeu : `written=0
  already_present=479`.
- `adopt-predecessor-release` : refusée avec le manifeste de transfert V2
  (`release_id` V2 ≠ V3) — garde légitime, conservée. Avec un manifeste de
  transfert au `release_id` de V3 : `placements=479 written=479`, bijection
  479/479, aucun fait historique réécrit, aucune ligne de ressource, d'artefact
  ou d'événement ajoutée ; rejeu idempotent.
- Aucune correction de code. Le manifeste de transfert V3 est un artefact
  opérationnel : l'étape `transfer_manifest_v3` le produit en rehachant, en
  lecture, les 315 objets du magasin de l'hôte.

Ce que chaque commande exige : le rattrapage, un manifeste de readiness signé
nommant **V2** pour l'image courante ; l'adoption, **aucun** manifeste de
readiness (rôle attestor seul).

## 4. L'amendement : une autorisation gouvernée distincte

`docs/reports/go_live/authorizations/staging_v3_publication_authorization.json`
(`NEXUS-STAGING-V3-PUBLICATION-AUTHORIZATION-V1`) complète l'autorisation SSH de
base, liée par empreinte, **sans la modifier** : la base continue d'interdire
Worker B, la base produit, les migrations et l'adoption. La nouvelle
autorisation nomme 14 opérations, dans l'ordre du plan, chacune sur sa cible
exacte — hôte `nexus-prod`, projet `nexus-staging`, conteneur
`nexus-staging-pgvector-1`, base `ragdb`, schéma (`public` produit,
`ingestion_control` contrôle), rôle (`ingestion_control_app` pour les workers,
`ingestion_control_attestor` pour l'adoption et la revue batch,
`rag_publisher` pour l'écriture produit, `rag_reader` pour la vérification) et
release. V2 n'est nommée que pour le rattrapage ; sa publication est interdite.
Le worker ne reçoit ni les identifiants du migrateur ni les DSN attestor ou
authority. Toutes les interdictions de production sont maintenues.

Le vérificateur évolue sans perdre sa protection :
`check_staging_authorization.py --operation <op> --cible <json>` refuse toute
opération de publication sous la seule autorisation de base, et n'accepte, sous
l'autorisation V3 fusionnée et conforme, que la cible exacte. Épreuves :
`scripts/qualification/tests/test_staging_v3_publication_authorization.py`.

Deux faits relevés en chemin, qui ne sont pas des défauts de V3 mais des pièges
d'interprétation : le manifeste de release déclare l'empreinte **canonique** du
manifeste de profils (`c11b2b1f…`) alors que Worker B vérifie celle de ses
**octets** (`d8b99a1d…`), toutes deux liées par `authority_bindings.json` ; et
l'artefact E5 que V3 déclare (`58ad18db…`) n'est pas celui que le plan de
staging d'origine citait. `staging_v3_arguments.py` confronte chaque empreinte à
la release et refuse tout écart ; l'étape `model_artifact_install` installe
l'artefact exact s'il manque.

## 5. Outillage

| Élément | Rôle |
|---|---|
| `scripts/go_live/staging_v3_publication.sh` | orchestrateur : 14 étapes, contrôle d'autorisation avant chacune, journal expurgé, reprise par état, arrêt au premier écart et devant l'approbation de la revue batch ; `--dry-run` sans aucune connexion |
| `scripts/go_live/staging_v3_arguments.py` | arguments des commandes canoniques dérivés de la release, empreintes confrontées au manifeste |
| `scripts/go_live/sign_staging_v3_readiness_manifests.sh` | signature locale, par le détenteur de la clé, des deux manifestes de readiness (V3 ; V2 rattrapage, 7 jours), objets affichés avant confirmation, revérifiés contre l'ancre |
| `docs/runbooks/staging_v3_publication_EXECUTION_PLAN.md` | plan lié par empreinte à l'autorisation |

## 6. ADR-0059

Statut porté à « Accepté » en citant la décision déjà enregistrée : review
`APPROVED` d'`abenrhouma` sur le HEAD `afe0b5c9` de #247, fusionnée en
`d7611667`. Aucune modification de fond.

## 7. Disque du poste

Une seule partition porte `/`, `/tmp`, `/home` et Docker. Libéré dans le
périmètre RAG : les deux venvs régénérables d'un worktree inactif depuis le
09/09 (11,9 Go) et des éléments que ce lot avait créés. Espace libre ~24 Go :
**sous le seuil de 40 Go** du gate de readiness go-live. Le reste relève de
volumes Docker anonymes (884, ~47 Go) dont le propriétaire n'est pas établi et
d'images d'autres projets : non touchés.

## 8. Ce qui reste, avec ses verrous

1. Approbation de cette PR au head exact (humain).
2. Signature locale des deux manifestes de readiness (détenteur de la clé).
3. Accès SSH de cette session à `nexus-prod` : refusé par le classifieur de
   permissions de l'outil ; à accorder par le propriétaire.
4. Puis, sans nouvel accord : orchestrateur jusqu'à la proposition de revue
   batch ; approbation humaine de la revue batch ; enregistrement, Worker B,
   vérification indépendante et retrieval.
