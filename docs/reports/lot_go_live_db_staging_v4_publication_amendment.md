# Lot DB — autoriser et outiller la publication de V4 sur le staging cloisonné

- Branche : `go-live/db-staging-v4-amendment`
- Base : `0569aff60092251eef691ed2a730dec3bdf7ec81` (main après #251, lot CZ)
- Reprend le lot CY (commit `fe9140b3`, jamais soumis). CY visait V3, qu'ADR-0061
  rend non servable. Ce lot en conserve la méthode : une autorisation distincte,
  chaque opération contrôlée sur sa cible exacte, un orchestrateur à reprise et
  un journal expurgé. Il refond le périmètre pour V4.

## 1. Ce que l'approbation de cette PR autorise

`docs/reports/go_live/authorizations/staging_v4_publication_authorization.json`
(`NEXUS-STAGING-V4-PUBLICATION-AUTHORIZATION-V1`) est liée par empreinte à
l'autorisation SSH de base et au plan d'exécution
(`docs/runbooks/staging_v4_publication_EXECUTION_PLAN.md`). Elle est à usage
unique et ne vaut qu'une fois **fusionnée** sur `main`.

| Dimension | Valeur |
|---|---|
| Release | `production-profile-gate-2026-2027-v4`, manifeste `bab9c398…`, profils `v3_livraison_315`, 11/315/479/8 268 |
| Actualité et visibilité servies | `official_snapshot`, `internal` |
| Cibles | `nexus-prod`, projet `nexus-staging`, conteneur `nexus-staging-pgvector-1`, base `ragdb`, schémas `public` et `ingestion_control` |
| Image worker | `rag-multilevel-worker-production@sha256:57e07979…`, run 36017565965, commit `0569aff6` (fusion de #251), contrats 0.21.0 |
| Image de sonde | `rag-ingestor@sha256:9dbc8f55…`, même run et même commit ; conteneur ponctuel en lecture, aucun service démarré |
| Autorisations r4 | PR #252 à son HEAD approuvé `2590a172…`, enregistrées avant sa fusion |
| Prédécesseurs | V2 et V3 : ni publication, ni adoption |

Les treize opérations nommées, dans l'ordre :
1. pré-vol ;
2. sauvegarde ;
3. migrations produit (tête 5) ;
4. migrations de contrôle (tête 19, avec provisionnement des rôles) ;
5. installation du modèle ;
6. installation de la readiness V4 ;
7. manifeste de transfert V4 ;
8. **enregistrement des onze r4** ;
9. ingestion scellée V4 ;
10. proposition de revue batch ;
11. enregistrement de la revue batch ;
12. **Worker B qualifié** ;
13. vérification indépendante avec **sonde de retrieval**.

Toute autre opération est refusée.

## 2. Ce qui change par rapport à CY

| CY (V3) | DB (V4) | Pourquoi |
|---|---|---|
| chemins A (direct) et B (rattrapage V2 puis adoption) | chemin direct seul ; une base non vierge arrête le pré-vol | reprendre des lignes V2 sous V4 change leur `placement_id` et leur programme (ADR-0061) |
| aucune opération d'autorité | `scope_authorization_registration_r4`, conteneur ponctuel qui reçoit seul le DSN authority | Worker A exige les r4 (LOT41A-V2) ; le rôle authority n'est remis à aucun worker |
| `--scope-authorization <id>` | `--scope-authorization collection=r4`, identifiants dérivés de V4 par le générateur | forme exigée par la CLI ; vérifiée sur le banc |
| tête de contrôle 18 ; cible nommant `bootstrap_ingestion_control_schema.sh` | tête 19 ; cible nommant `provision_and_bootstrap_ingestion_control.sh`, le runner réellement invoqué | migration 019 ; CY citait un runner différent de celui qu'il lançait |
| Worker B sans protocole explicite | `NEXUS_ENVIRONMENT=rehearsal` et `NEXUS_EXPECTED_READINESS_PROTOCOL=NEXUS-STAGING-READINESS-V1` posés par l'orchestrateur ; démarrage exigé en `RELEASE_BOUND_STAGING_QUALIFICATION` | la qualification (ADR-0060) ne dépend pas du fichier d'environnement de l'hôte |
| deux manifestes de readiness (V3, V2) | un seul, V4 | plus de rattrapage |
| vérification : deux comptes | comptes exacts **et** sonde de retrieval sous les onze scopes V4 | le retrieval servi doit être exercé, pas supposé |
| image `f931f59c…` (contrats 0.20.0) | écartée ; image `57e07979…` et image de sonde `9dbc8f55…` | l'image de CY précède ADR-0060/0061 et la publication exacte des chunks scellés |

## 3. La sonde de retrieval

`scripts/go_live/staging_retrieval_probe.py` s'exécute dans l'image ingestor
épinglée, sous le rôle `rag_reader` (`PG_RAG_DSN`). Pour chacune des onze
collections, la sonde :
* signe un jeton `teacher` sous le scope que nomme
  `production-profile-scope-successors-v4.yml`, avec un secret éphémère tenu
  en mémoire ;
* confronte le scope dérivé par le code servi au registre de programme de V4
  et à la visibilité `internal` ;
* interroge **chaque** chunk publié par son vecteur et pose une requête
  lexicale ;
* exige qu'aucun candidat ne sorte du jeu publié ;
* n'admet un refus dense que s'il est constaté à sa source
  (`dense ann tie overflow`, escalade du lot CZ) ;
* vérifie que le rôle `student` est refusé.

`test_4` du banc réel V4 appelle désormais **ce même code**, restreint aux
collections publiées par le banc, au lieu d'en tenir une réplique.

## 4. Preuve de provenance des images

`docs/reports/evidence/staging_worker_image_provenance_db.json` : les deux
images ont été tirées par digest sur le poste de travail, puis exécutées hors
réseau (`--network none`).

**Image worker :**
* contrats 0.21.0 ;
* points d'entrée présents, dont `authorize_scope_cli` et
  `release_qualification` ;
* sous-commande `bind-publication-authorities` ;
* `select_publication_chunks` présent ;
* aucun module de retrieval, d'où l'image de sonde distincte.

**Image ingestor :**
* contrats 0.21.0 ;
* registre de 63 scopes, dont les onze scopes V4 ;
* modules de retrieval à plat sous `/app`.

Seule variable d'environnement dont le nom évoque un secret : `GPG_KEY`.
C'est l'empreinte publique de la clé qui signe les sources Python, posée par
l'image officielle, et non un secret.

## 5. Épreuves

- `scripts/qualification/tests/test_staging_v4_publication_authorization.py`
  et `test_staging_v4_arguments.py` : 109 réussis. Ils couvrent :
  * l'autorisation de base, qui refuse encore chaque opération ;
  * la cible exacte de chaque opération ;
  * le refus de V2, V3, du rattrapage et de l'adoption ;
  * le rôle authority, cantonné à l'enregistrement des r4 ;
  * la PR et le HEAD des r4 ;
  * le mode qualifié de Worker B ;
  * les images écartées, et les deux images tirées du même commit ;
  * l'impossibilité de retirer un interdit ou une mention de la déclaration ;
  * le document réel, lié à la base, au plan et à la preuve.
- Essai à blanc de l'orchestrateur, sans SSH ni écriture : les treize
  commandes sont assemblées. Chaque étape est refusée en réel pour une seule
  raison, « l'autorisation V4 n'est pas sur origin/main ».
- Banc réel V4 (`test_v4_staging_direct_real_chain.py`) avec la sonde : 10
  réussis sur 10. La sonde couvre les trois collections publiées par le banc :
  * 1 489 chunks interrogés, 1 486 retrouvés en tête, 0 manqué ;
  * 3 refus pour égalité, constatés à la source ;
  * `student` refusé partout.

  Le nombre de refus varie d'un run à l'autre (5 au run du lot CZ), car
  l'index HNSW est reconstruit à chaque run. Voir l'escalade du lot CZ.

## 6. Ce qui reste, dans l'ordre

1. Revue et fusion de cette PR. C'est elle qui autorise.
2. Accès réseau au staging (Tailscale), puis pré-vol : chemin direct, ou arrêt
   si la base porte des lignes acquises.
3. Signature locale de `staging-readiness-v4.json` par le détenteur de la clé.
4. Exécution jusqu'à la proposition de revue batch, dont l'enregistrement des
   r4 pendant que #252 est ouverte, puis fusion de #252.
5. Approbation de la revue batch, puis Worker B et vérification.

Aucune écriture de staging ni de production n'a été faite par ce lot.
