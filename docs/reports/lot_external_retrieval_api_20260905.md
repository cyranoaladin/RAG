# LOT — API de retrieval externalisée : portées, taxonomie, OpenAPI

**Branche** `glr/external-api` · **Base** `origin/main` (`8ad5206`) · 2026-09-05

## Ce que ce lot ferme

Le moteur savait déjà servir `POST /search/v2` contre le contrat
`RetrievalResponse`. Ce qui manquait, pour qu'un agent extérieur puisse s'en
servir, tenait en quatre points : une frontière d'autorisation, une taxonomie
consultable, une spécification qui ne dérive pas, et une trace par requête.

Aucune route parallèle n'a été créée. `/search/v2` reste le seul spine de
retrieval.

## La propriété qui décide de tout : le filtre ne peut que restreindre

Les dix dimensions de **placement** — `audience`, `candidat`, `collection`,
`matiere`, `niveau`, `programme_version`, `school_year`, `tenant`, `visibility`,
`voie` — décident de ce qui *peut* être vu. `chapitre`, `notion` et
`type_document` vivent sur les métadonnées de chunk et ne décident de rien.

La règle appliquée est donc :

```
AUTORISÉ_PAR_PLACEMENT  ET  CORRESPOND_AUX_MÉTADONNÉES
```

jamais un `OU`. Le fragment `CHUNK_METADATA_FILTER_SQL` est injecté par `AND`
dans les **deux** canaux (dense et lexical) et reste neutre quand aucun filtre
n'est demandé : sur un filtre présent il ne peut que retirer des lignes.

### Preuve par sabotage, sur PostgreSQL réel

`tests/integration/test_c6_chunk_metadata_filters_never_widen_placement.py`
exerce le vrai `PgCandidateStore`, sur une image pgvector épinglée par digest et
un schéma appliqué depuis les vraies migrations `001..004` — pas une requête
réécrite pour le banc.

| sabotage | attendu | observé |
|---|---|---|
| placement REFUSE + notion CORRESPOND | 0 résultat | 0 |
| placement AUTORISE + notion NE CORRESPOND PAS | 0 résultat | 0 |
| placement AUTORISE + notion CORRESPOND | le chunk | le chunk |

Mutations exécutées et vérifiées :

```
BASELINE                        .....   5/5 vert
notion rendue toujours vraie    ..F..   1 rouge (sabotage 2)
AND → OR sur les deux canaux    .FF.F   3 rouges (dont sabotage 1)
RESTAURÉ                        .....   5/5 vert, octet-identique (cmp)
```

Un filtre de métadonnée ne peut donc pas rendre visible un contenu que son
placement interdit — c'est prouvé par l'échec, pas affirmé par le code.

## Deux filtres refusés plutôt que simulés

`desired_doc_types` et `difficulty_max` sont refusés en `422`. Aucune colonne ne
permet de les appliquer, et annoncer à un agent une restriction inopérante serait
lui mentir : un filtre qui ne filtre pas est pire que son absence.

## Portées

`rag:search`, `rag:read-source`, `rag:ingest`, `rag:admin` sont **disjointes** :
aucune n'en implique une autre. Le banc bloquant présente une clé `rag:search`
par ailleurs valide comme jeton d'agent d'ingestion à la vraie porte
`ingest_v2_endpoint._enforce_security`, qui la refuse en `403`.

Le registre ne contient que des empreintes SHA-256 — une valeur en clair est
refusée — et se lit depuis `RAG_API_CLIENTS` **ou** `RAG_API_CLIENTS_FILE`,
jamais les deux, jamais depuis le dépôt. La clé voyage dans `X-RAG-API-Key` :
`Authorization` reste occupé par le credential BFF.

## `specialite` : une vue, pas une seconde vérité

`statut_enseignement` n'est pas une dimension de placement — il est absent de
`ResourceScope` et de `_canonical_scope`. Sa vérité canonique est le champ
`statut` du catalogue `configs/rag_collections.yml`, typé `StatutEnseignement`,
d'où découle aussi le nom de collection (`rag_nexus_{matiere}_{niveau}_{statut}`,
ADR-0013).

`GET /taxonomy/v2` l'expose comme **vue**, relue simultanément du catalogue et du
scope serveur. Une divergence entre les deux ferme la vue en `403` au lieu
d'élire arbitrairement une source. Aucune écriture, aucune autorité nouvelle.

## OpenAPI

`scripts/generate_openapi.py` dérive le schéma de `app.openapi()` — les mêmes
modèles Pydantic que les routes servent —, jamais un YAML tenu à la main qui
finirait par diverger.

```
OPENAPI_SCHEMA_DRIFT=0
```

Le banc vérifie en outre que la surface documentée égale la surface montée et que
`/search/v2` référence bien `RetrievalRequest`/`RetrievalResponse` : sans cela un
schéma vide serait stable, donc vert, et ne prouverait rien.

## Observabilité

Une ligne JSON par requête sur `nexus.retrieval.access` : `request_id`,
`client_id`, portées accordées, filtres, `candidate_count`, `returned_count`,
latence, et l'état de chaque canal (`embedding`, `dense`, `lexical`, `reranker`).

**La requête brute ne sort jamais** : seuls `query_sha256` et `query_length` sont
journalisés. `X-Request-ID` est borné avant journalisation.

## Un défaut silencieux attrapé en chemin

La lecture du client authentifié par `isinstance` échouait à travers le double
chemin d'import du service (`ingestor.x` contre runtime aplati). La requête était
servie, le journal restait anonyme, aucun appel ne cassait — invisible en test
isolé, révélé par la suite complète. Corrigé en lecture structurelle, avec une
épreuve qui croise volontairement les deux modules.

## Qualité

```
ruff check .                All checks passed
mypy src                    135 fichiers, aucun problème
intégration C6              5/5 vert (aussi sous NEXUS_REQUIRE_DOCKER=1)
suite unitaire              2 échecs = exactement la baseline origin/main
                            (pypdf 4.2.0 local vs 6.14.2 déclaré — hors lot)
```

Aucune régression. C6 est ajouté à `make test-governance-pg` pour être bloquant.

## À traiter avant le staging externe

La porte de portée est **fail-closed** sur l'app v2 : tout appelant du cockpit
devra présenter un `X-RAG-API-Key` en plus de son jeton BFF. C'est un changement
de contrat côté façade. Déployer sans l'avoir traité fermerait le cockpit sur
lui-même.
