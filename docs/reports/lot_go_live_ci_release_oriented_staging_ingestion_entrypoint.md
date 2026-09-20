# LOT_GO_LIVE_FINAL_CI_RELEASE_ORIENTED_STAGING_INGESTION_ENTRYPOINT

- **Branche** : `go-live/release-oriented-staging-ingestion-entrypoint`
- **Base** : `5355dd7f` (migration 014, #235)
- **Décision attendue** : `GO_LIVE_CI_RELEASE_ORIENTED_INGESTION_ENTRYPOINT_PR_OPEN`
- **S'appuie sur** : ADR-0032 (LOT41A), ADR-0033 (LOT42), **ADR-0056**
  (protocole batch pour release scellée), migration 014

> Ce lot **ne publie rien**, **n'atteste rien**, n'exécute pas Worker B,
> n'écrit pas dans `PG_RAG_DSN`, ne touche pas `rag_pgvector`, ne bascule
> aucun `current`, n'expose rien publiquement et ne rend pas V2 promotable.
> Il s'arrête à `NEEDS_REVIEW`.

## Pourquoi un second point d'entrée

Le pipeline `resource_pipeline` **découvre** : il part d'une URL, en tire une
ressource, et propose un `type_doc` que le mapping gouverné confronte ensuite.
C'est exact pour ce qu'on trouve sur le web.

`production-profile-gate-2026-2027-v2` est l'inverse : le corpus est déjà
choisi, typé, chunké et relu au scellement. Le faire passer par le front de
découverte exigeait deux **fabrications**, mesurées sur la release elle-même :

| Grandeur | Valeur mesurée |
|---|---|
| Subjects | 11 |
| Artefacts uniques | 315 |
| Placements | 479 |
| Chunks | 8 268 |
| Pages de découverte distinctes | **19** |
| URL de provenance d'artefact distinctes | **27** |
| `canonical_url` documentaire par artefact | **inexistante** |

1. **Le type de document.** Un job est identifié par son URL. 315 artefacts
   pour 19 pages : un seul `proposed_type_doc` par job écraserait les six types
   que la release a scellés (`ressource_officielle` 155, `autre` 54,
   `programme_officiel` 38, `modalite_examen` 35, `diaporama` 30, `annale` 3).
2. **L'URL canonique.** Promouvoir une page de provenance en identité de
   document affirmerait ce que personne n'a établi (ADR-0056 § 3).

Ce point d'entrée itère donc sur les **placements**, lit les PDF du store
transféré et vérifié plutôt que de recrawler, et écrit
`pipeline_kind = 'sealed_release_pipeline'` avec `canonical_url = NULL` — ce
que la migration 014 rend non seulement possible mais **obligatoire** pour
cette origine : une URL y serait refusée par PostgreSQL.

## Ce que le lot livre

| Fichier | Rôle |
|---|---|
| `services/rag-engine/src/ingestor/ingestion_worker/sealed_release_ingestion.py` | Le point d'entrée : chargement vérifié, refus, écriture jusqu'à `NEEDS_REVIEW` |
| `services/rag-engine/src/ingestor/ingestion_worker/sealed_release_ingestion_cli.py` | La frontière CLI fail-closed, refus de la production |
| `services/rag-engine/src/ingestor/ingestion_control/provisioning.py` | Deux primitives d'écriture scellée + `pipeline_kind` sur `create_resource` |
| `services/rag-engine/tests/test_sealed_release_ingestion.py` | 51 tests |
| `services/rag-engine/tests/integration/test_sealed_release_ingestion_pg.py` | 13 tests sur PostgreSQL réel |
| `services/rag-engine/Makefile` | Le test d'intégration rejoint `test-governance-pg` |

### Les quatre digests, vérifiés deux fois

Chaque autorité est vérifiée contre **les octets lus** *et* contre ce que le
manifeste de release **déclare** pour elle. Un appelant qui nommerait un
`artifacts.release.json` cohérent avec lui-même mais étranger à cette release
est refusé par la seconde vérification.

| Autorité | sha256 |
|---|---|
| `production-profile-gate.release.json` | `e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864` |
| `artifacts.release.json` | `42c71df3c3ddbab83f71ea20bc6624237608bb77f064db3018f9d15f63eabeb0` |
| `candidate_inventory.json` | `d906663b91b7bfac9dab0c05e4374cdb61b2eef8556ad2e86ceee3d529ab8123` |
| `external_staging_v2_artifact_transfer_manifest.json` | `1f63939b4e1510ad261d1076f16f15b47422d6745f69145fab3789f466eb6e47` |

Les 11 subjects sont vérifiés un par un contre le `sha256` que le manifeste
leur attribue.

### Trois choix qui méritent d'être dits

**La clé de déduplication dérive du contenu, jamais de l'URL.**
`(collection, content_sha256)` est unique sur les 479 placements — vérifié.
Une clé dérivée de la page de découverte les réduirait à 19 ressources, et de
l'URL d'artefact à 27 : dans les deux cas, le reste du corpus disparaîtrait.

**Le `proposed_type_doc` écrit est le type Nexus gouverné, pas le type
externe.** L'inventaire observe un vocabulaire externe
(`ressource-accompagnement`, `programme-officiel`, …) ; `artifacts.release.json`
porte sa traduction gouvernée dans `TypeDoc`. La correspondance est totale et
univoque sur les 479 placements (8 valeurs externes → 6 valeurs `TypeDoc`,
aucun artefact ne porte deux types). Écrire `programme-officiel` tel quel
serait un type inventé, qu'aucun contrat ne reconnaît.

**Le scope vient du profil gouverné, confronté à la release.** Le profil
`v2_livraison_319` porte les dix dimensions — dont `audience`, que la release
ne déclare pas ; la release porte le fait que ce placement appartient à ce
scope. Le moindre désaccord sur les neuf dimensions communes est un refus.
L'autorisation LOT41A est ensuite revérifiée **contre ce scope**, pas
seulement nommée.

**Aucune autorisation n'est cherchée.** Elle est nommée collection par
collection (`--scope-authorization COLLECTION=AUTHORIZATION_ID`), puis
intégralement revérifiée par `verify_scope_authorization` (révocation, fenêtre
de validité, revue humaine vivante, artefact relu). Choisir « la plus
récente » ferait dépendre l'ingestion d'un tri plutôt que d'une décision. Une
collection sans autorisation, et une autorisation pour une collection hors
release, sont **toutes deux** refusées.

## Preuves

### Les 22 tests obligatoires

| # | Exigence | Test |
|---|---|---|
| 1 | release non scellée refusée | `test_1_une_release_sans_expected_counts_est_refusee`, `test_1bis_…kind…`, `test_1ter_…autorites…` |
| 2 | digest release divergent refusé | `test_2_…manifeste…`, `test_2bis_…artefacts…`, `test_2ter_…subject…`, `test_2quater_…transfert…` |
| 3 | artifact-store incomplet refusé | `test_3_un_store_incomplet_est_refuse`, `test_3bis_un_seul_artefact_manquant_suffit_a_refuser` |
| 4 | digest PDF divergent refusé | `test_4_un_pdf_au_digest_divergent_est_refuse`, `test_4bis_…transfert…` |
| 5 | autorisation LOT41A manquante refusée | `test_5_…`, `test_5bis_…hors_release`, `test_5ter_…`, `test_5quater_…scope…`, `test_5quinquies_…domaines…` |
| 6 | collection manquante refusée | `test_6_une_collection_manquante_est_refusee` |
| 7 | collection supplémentaire refusée | `test_7_une_collection_supplementaire_est_refusee` |
| 8 | 11 collections couvertes | `test_8_les_onze_collections_sont_couvertes` |
| 9 | 315 artefacts uniques couverts | `test_9_les_315_artefacts_uniques_sont_couverts` |
| 10 | 479 placements couverts | `test_10_les_479_placements_sont_couverts` |
| 11 | 8268 chunks couverts | `test_11_les_8268_chunks_sont_couverts`, `test_11bis_…recomptes…`, `test_11ter_…compte_annonce_faux…` |
| 12 | HGGSP première couverte | `test_12_hggsp_premiere_est_couverte` (39) |
| 13 | HGGSP terminale couverte | `test_13_hggsp_terminale_est_couverte` (35) |
| 14 | HLP terminale couverte | `test_14_hlp_terminale_est_couverte` (89) |
| 15 | `canonical_url` reste NULL | `test_15…` (×3, statiques) + `test_15_canonical_url_reste_null_pour_sealed_release_pipeline` et `test_15bis_la_base_refuse_une_canonical_url_fabriquee_apres_coup` (PostgreSQL réel) |
| 16 | source_url reste provenance | `test_16…` (×3) + `test_16_source_url_reste_une_provenance` (PostgreSQL réel) |
| 17 | aucune publication | `test_17_aucune_publication_nest_atteignable_depuis_ce_point_dentree`, `test_17_aucune_ligne_publiee` |
| 18 | aucune attestation | `test_18_aucune_attestation_nest_atteignable…`, `test_18_aucune_attestation_enregistree` |
| 19 | état final `NEEDS_REVIEW` | `test_19…` (×2) + `test_19_letat_final_est_needs_review`, `test_19bis_chaque_etat_intermediaire_est_journalise` |
| 20 | LOT42-V1 inchangé | `test_20_lot42_v1_est_inchange` |
| 21 | `resource_pipeline` inchangé | `test_21_le_resource_pipeline_est_inchange`, `test_21bis_…`, `test_21_le_resource_pipeline_reste_ecrivable_a_cote` (PostgreSQL réel) |
| 22 | production impossible | `test_22_la_production_est_impossible`, `test_22bis_le_cli_refuse_de_demarrer_hors_rehearsal`, `test_22ter_…` |

Les preuves 17 et 18 sont **structurelles** : le code exécutable des deux
modules (commentaires et docstrings retirés) ne contient ni `PG_RAG_DSN`, ni
`rag_chunks`, ni `rag_artifacts`, ni `publication_attestations`, ni
`attest_publication`, ni `PUBLISHED`. Il n'y a pas de chemin vers la
publication à désactiver : il n'y en a pas.

La preuve 19 ne se contente pas de l'état final : les dix transitions passent
par `cas_transition`, qui refuse toute transition que
`is_valid_resource_transition` n'autorise pas. Le test vérifie aussi que
`DISCOVERED -> NEEDS_REVIEW` reste impossible — le raccourci n'existe pas.

### Exécution mesurée

```
services/rag-engine
  ruff check .                          All checks passed!
  mypy src                              Success: no issues found in 142 source files
  pytest -m "not integration"           1 failed, 3802 passed, 11 skipped, 441 deselected
  pytest tests/test_sealed_release_ingestion.py                 51 passed
  pytest tests/integration/test_sealed_release_ingestion_pg.py  13 passed
```

Le test d'intégration tourne contre un conteneur `pgvector/pg16` jetable
migré par le vrai script de bootstrap (`schema_head = 14`). Les comptes y sont
mesurés par `SELECT`, pas lus dans le rapport que le module rend de lui-même.

### Échec préexistant, antériorité prouvée

`tests/test_openapi_schema_drift.py::test_le_schema_publie_est_celui_du_runtime`
échoue **déjà** sur le commit parent. Vérifié en exécutant ce même test depuis
un worktree détaché sur `origin/main` (`5355dd7f`) : même échec, même
diff (`OPENAPI_SCHEMA_DRIFT=1`, premier écart à l'octet 14836). Ce lot ne
touche ni l'API, ni le schéma publié, ni les dépendances. Dette déjà connue
(désalignement pydantic local / contrat OpenAPI publié) ; aucun test vert ne
passe au rouge.

## Conformité au périmètre

| Interdit | État |
|---|---|
| exécuter Worker B | non touché |
| publier dans `PG_RAG_DSN` | aucune référence dans le code |
| créer / enregistrer une attestation LOT42 | aucune référence dans le code |
| inventer `canonical_url` | le paramètre n'existe pas ; l'INSERT pose `NULL` littéral ; PostgreSQL refuse le contraire |
| mettre `source_url` dans `canonical_url` | impossible, même raison |
| modifier release V2 / la rendre promotable | release lue seule, aucune écriture |
| écrire en DB production / `rag_pgvector` | aucune connexion produit |
| `current switch` | hors code |
| exposer publiquement | hors code |

## Ce que ce lot ne fait pas et qui reste à faire

L'exécution sur staging vient **après** merge. Elle produira les comptes réels
(11 / 315 / 479 / 8268), l'état `NEEDS_REVIEW`, et la preuve que l'index
produit reste inchangé tant que Worker B n'a pas tourné.

Le lot suivant, `LOT_GO_LIVE_FINAL_CI_LOT42_RELEASE_BATCH_ATTESTATION`, ne
peut pas commencer avant. **Worker B ne tourne pas avant qu'une attestation
LOT42 batch soit enregistrée.**
