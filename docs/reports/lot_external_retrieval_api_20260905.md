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

---

# Remédiation de revue — 2026-09-06

Dix-neuf findings ouverts par la revue automatique, plus trois échecs
d'intégration que la CI a fait remonter. Traités avant fusion.

## P0 — l'image ne portait pas ce que son runtime importe

`api_scopes.py`, `retrieval_metadata_v2.py` et `retrieval_observability.py`
n'étaient dans aucun `COPY` : le service démarrait sur un poste de
développement (le module venait du checkout hôte) et aurait échoué à
l'`ImportError` une fois l'image construite.

Trois gardes, du plus faible au plus fort :

1. l'allowlist du `Dockerfile` et du `.dockerignore` est complétée ;
2. une épreuve statique calcule la **fermeture transitive** des imports du
   runtime aplati et refuse tout module importé mais non copié — l'énumération
   à la main est remplacée par un calcul ;
3. `tests/integration/test_ingestor_v2_image_boot.py` **construit l'image
   réelle** et l'exécute. Aucun montage hôte.

```
docker build -f services/rag-engine/infra/Dockerfile.ingestor-v2 .
docker run --rm --entrypoint python <image> -c "import api_v2"   → IMPORT_OK
docker run --rm --entrypoint python <image> -c "import api_scopes; …"
    → /app   (et non le checkout hôte)
5 passed
```

Le banc est branché au job CI `worker image integration (docker)`, le seul qui
dispose d'un démon Docker réel.

## P0 — le registre de clients d'API n'était injecté par aucun Compose

`load_api_clients()` est appelé dans le lifespan : sans autorité configurée, le
service échouait au démarrage. Le Compose canonique monte désormais **une seule**
autorité, un fichier de secrets en lecture seule, et exige un secret HMAC dédié
pour le journal d'accès.

Porte prouvée **sur l'image réelle**, pas seulement en unité :

```
zéro source configurée  → refus  ("no API client registry configured")
deux sources            → refus  ("both API client sources are configured")
exactement une          → la porte est franchie ; l'échec suivant n'est plus
                          celui du registre
```

## P1 — deux credentials réellement distincts

`extract_api_key` retombait sur `Authorization` quand `X-RAG-API-Key` manquait :
un seul secret suffisait alors à passer les deux portes, et « deux
credentials » était une fiction. Le repli est supprimé — y compris sur
`X-API-Token`.

Ses appelants suivent dans le même lot, comme la revue l'exigeait :

- **Cockpit/BFF** — `RAG_ENGINE_API_KEY` en plus de `RAG_ENGINE_INTERNAL_TOKEN`,
  avec un refus explicite avant tout appel réseau si l'un manque ;
- **client externe** `scripts/rag_query_external.py` — `RAG_API_KEY`, même refus
  anticipé : « Unauthorized » côté serveur ne dirait pas ce qui manque ;
- **documentation** — README Cockpit et checklist go-live.

## P1 — OpenAPI décrit l'authentification réelle

`app.openapi()` ne voit rien : l'authentification vit dans un middleware, pas
dans des dépendances FastAPI. Le document annonçait donc des routes ouvertes que
le runtime refuse en 401 — un générateur de client produisait du code incapable
d'appeler `/search/v2`.

Les trois credentials sont maintenant déclarés (`bffServiceToken`, `ragApiKey`,
`nexusSignedIdentity`), et chaque opération porte sa `security` **dérivée des
tables du runtime** (`_ROUTE_SCOPES`, `_ROUTE_SIGNED_IDENTITY`) — jamais
recopiée. Un test confronte la table d'identité au code qui appelle réellement
la porte : une route qui quitte l'une sans quitter l'autre se voit.

## P2 — `/taxonomy/v2` typé et non muet

`dict[str, Any]` est publié comme un objet sans forme. Contrat partagé
`TaxonomyV2Response` dans `packages/contracts` (0.17.0, **ADR-0049**), schéma
JSON exporté, `response_model` sur la route.

Les dimensions décrites sont celles que le moteur dérive réellement ;
`chapitre`, `notion` et `type_document` sont **délibérément absents** — aucune
taxonomie fermée ne les borne, et annoncer une énumération que rien ne peut
produire serait une promesse fausse.

La route absorbait par ailleurs **toute** `HTTPException` pour passer à la
collection suivante : une panne d'autorité (500, 503) rendait une taxonomie vide
en 200, indistinguable d'un compte légitimement vide. Seul le 403 — une décision
d'autorisation — reste silencieux.

## P2 — C6 sur les deux canaux

`PgCandidateStore` câble le fragment de métadonnée et le conjoint de placement
dans deux SQL distincts. Le banc n'exerçait que le lexical : une régression
confinée au chemin dense n'aurait laissé aucune trace. Les quatre sabotages sont
rejoués sur `store.dense(...)`.

Mutation prouvée sur PostgreSQL réel : `AND {fragment}` → `AND (TRUE OR
{fragment})` **dans le seul SQL dense** →
`test_placement_autorise_et_notion_ne_correspond_pas_ne_sert_rien` rougit ;
restauré → 5 passed.

```
PLACEMENT_DENY + notion_match  → 0   (lexical ET dense)
PLACEMENT_ALLOW + notion_mismatch → 0 (lexical ET dense)
PLACEMENT_ALLOW + notion_match → 1   (lexical ET dense)
```

## P2 — observabilité : les échecs, et l'étape fautive

**Toute** requête produit désormais un enregistrement. La route journalise ses
propres issues (200, 403, 422, 503, 500) et pose une marque ; le middleware
journalise ce qui n'a jamais atteint la route — refus d'authentification, corps
rejeté par la validation du framework. Exactement un enregistrement par requête,
jamais deux.

`stage` ne se réutilise plus après coup : `fusion_status` et `selection_status`
existent. Un échec de RRF ou de MMR ne peut plus marquer `lexical` en échec
alors que le canal lexical a rendu ses candidats.

## P2 — confidentialité du journal

- **empreinte de requête** : `HMAC-SHA256(secret, requête normalisée)` sous
  `RAG_ACCESS_LOG_HMAC_SECRET`. Un SHA-256 nu se retourne par dictionnaire :
  « corréler » devenait « retrouver ». **Aucun repli** : sans secret, pas
  d'empreinte du tout.
- **`notions`** : texte libre d'appelant, aucune taxonomie fermée ne le borne.
  Compté et empreint sous la même clé, jamais recopié. Les dimensions de
  catalogue fermées (`collection`, empreinte de scope, identifiants de corpus)
  restent lisibles — sans elles, un « 0 résultat » ne se diagnostique pas.
- **immuabilité** : `frozen=True` gèle les attributs, pas les dictionnaires
  qu'ils désignent. `filters` et `channels` sont figés à la construction.
- **portées** : un appelant non résolu n'est plus crédité de `rag:search`.

## P3

- comparaison et écriture du schéma OpenAPI **en octets** : un fichier publié en
  CRLF passait pour identique, et `OPENAPI_SCHEMA_DRIFT=0` ne prouvait plus
  l'artefact octet-identique promis ;
- la surface comparée ne retient que les routes que FastAPI documente
  réellement, au lieu d'une liste d'exclusions qui oubliait
  `/docs/oauth2-redirect` ;
- registre de clients lu **une seule fois** par requête : celle qui décide est
  celle qui attribue ;
- un registre monté en octets non-UTF-8 (rotation de secret) est une
  configuration refusée — 503 —, plus une panne serveur 500.

## Trois échecs d'intégration que la CI a fait remonter

| Banc | Cause | Correctif |
|---|---|---|
| `test_real_gin_and_hnsw_plans_filters_top_50_and_local_scope` | « 42 marqueurs pour 40 paramètres » : le fragment de métadonnée ajoute deux places au SQL, les helpers du banc ne les passaient pas | les paramètres sont lus de `chunk_metadata_filter_params`, jamais recopiés |
| `test_signed_identity_to_http_scope_and_real_database_is_end_to_end` | le double de comptage recopiait une signature devenue fausse | `**options` suit la signature réelle : le double compte, il ne décide pas de la forme |
| `test_runtime_blocks_review_update_while_trigger_drift_is_detected` | la porte de portée refusait en 503 avant d'atteindre la dérive de trigger mesurée | le banc provisionne un registre et envoie les **deux** credentials |

## Un montage de plus, et un banc qui ne le savait pas

Le montage du registre de clients a fait rougir
`test_lot44f_ingestion_up_failure.py` en CI — trois tests, sur une erreur sans
rapport avec ce qu'ils mesurent :

```
service "ingestor" refers to undefined volume 4DzlF7KBD7MejMuteknu33V5FWZC7kIt:
invalid compose project
```

Le banc synthétise une valeur factice pour chaque variable `${VAR:?…}` des deux
Compose, en donnant un **chemin** à ce qui finit par `_HOST_DIR`/`_CACHE_DIR` et
un jeton aléatoire à tout le reste. `RAG_API_CLIENTS_HOST_FILE` recevait donc un
jeton ; Compose lit toute source de montage qui n'est pas un chemin comme un
volume **nommé**, et rejette le projet entier.

Une source de montage doit avoir la **forme** d'un chemin — c'est exactement la
règle que le commentaire du banc énonce déjà pour les empreintes. Un fichier
hôte reçoit désormais un fichier réellement créé. Vert localement sur un vrai
démon Docker (`3 passed`).

`infra/.env.example` déclare les deux variables qu'un opérateur ne peut pas
deviner — `RAG_API_CLIENTS_HOST_FILE` et `RAG_ACCESS_LOG_HMAC_SECRET` — et dit
pourquoi `RAG_API_CLIENTS` doit rester vide : le Compose canonique fixe déjà
`RAG_API_CLIENTS_FILE`, et une seconde source ferait échouer le démarrage.
`test_v2_runtime_surface.py` exige leur présence.

## Un point mesuré, non corrigé ici

Le schéma OpenAPI est rendu par Pydantic, et deux versions rendent le même
modèle avec des différences de forme : 2.13 écrit `additionalProperties: true`
là où 2.9 l'omet. Le service épingle **2.9.2** dans `requirements.lock` ;
l'image v2 épingle **2.13.4** (`requirements.runtime-v2.txt`, aligné sur
`packages/contracts`). L'artefact publié est celui du lock de service — le même
que la CI compare.

La divergence est **de rendu, pas de contrat** : en JSON Schema,
`additionalProperties` vaut `true` par défaut, donc les deux documents
décrivent le même objet. `test_v2_pydantic_pin_aligned_with_contracts` ne
couvre que le manifeste d'image ; le lock de service lui échappe. L'aligner
exige de régénérer ce lock (avec ses empreintes) et de reprendre tout le
service : hors périmètre de ce lot, signalé plutôt qu'entrepris.

## Qualité

| Cible | Résultat |
|---|---|
| `services/rag-engine` — pytest (`-m "not integration"`) | vert, exit 0 |
| `services/rag-engine` — `ruff check src tests scripts` | All checks passed |
| `services/rag-engine` — `mypy src` | Success: no issues found in 135 source files |
| `packages/contracts` — pytest | 568 passed |
| `services/cockpit` — vitest | 180 passed (21 fichiers) |
| C6 sur pgvector réel (lexical + dense) | 5 passed |
| démarrage de l'image v2 réelle | 5 passed |
