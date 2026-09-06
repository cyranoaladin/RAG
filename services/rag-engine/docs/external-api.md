# API externe du rag-engine

Surface publique du plan de données. Elle expose le retrieval gouverné et sa
taxonomie ; elle n'expose ni pgvector, ni les documents bruts, ni la chaîne
d'ingestion.

Le contrat d'échange est `packages/contracts` (`nexus-contracts`) :
`RetrievalRequest → RetrievalResponse`. Aucun service ne le redéfinit
localement.

## Le spine de retrieval

`POST /search/v2` est **le** point d'entrée de retrieval. Il n'existe pas de
route parallèle : toute évolution de la recherche se fait sur celle-ci.

Le schéma OpenAPI publié est
[`openapi/rag-engine-external-api.json`](../openapi/rag-engine-external-api.json).
Il est **dérivé** de l'application FastAPI et de ses modèles Pydantic, jamais
rédigé à la main :

```bash
PYTHONPATH=src python scripts/generate_openapi.py           # régénérer
PYTHONPATH=src python scripts/generate_openapi.py --check   # OPENAPI_SCHEMA_DRIFT=0
```

`tests/test_openapi_schema_drift.py` échoue si le fichier publié diverge du
runtime.

## Authentification : deux portes cumulatives

| Porte | En-tête | Ce qu'elle établit |
|---|---|---|
| Credential machine BFF | `Authorization: Bearer …` | l'appel vient de la façade autorisée |
| Clé porteuse d'API | `X-RAG-API-Key: …` | ce que **cette clé** a le droit de faire |

Les deux en-têtes sont distincts parce que deux secrets différents ne peuvent
pas partager un en-tête sans que l'un masque l'autre. Là où aucun credential
de service n'occupe `Authorization` (chaîne d'ingestion), la clé porteuse est
lue depuis `Authorization` en repli.

### Portées

Quatre portées **disjointes** — aucune n'en implique une autre :

| Portée | Routes |
|---|---|
| `rag:search` | `/search/v2`, `/taxonomy/v2`, `/collections/v2`, `/catalogue/v2`, `/collections/readiness`, `/chat` |
| `rag:read-source` | `/corpora/servable/v1`, `/corpora/servable/v1/{manifest_sha256}` |
| `rag:ingest` | `/ingest/v2/*` |
| `rag:admin` | `/review/v2/queue`, `/review/v2/decide` |

Que `rag:search` n'implique pas `rag:read-source` est délibéré : rendre un
extrait cité n'est pas rendre le document source. Une clé `rag:search` ne peut
pas ingérer — c'est vérifié par `tests/test_api_scopes.py` sur la porte
d'ingestion réellement livrée.

### Registre de clés — aucun secret dans le dépôt

Le registre vient de l'environnement (`RAG_API_CLIENTS`) **ou** d'un magasin
monté (`RAG_API_CLIENTS_FILE`), jamais des deux. Il ne transporte que
l'empreinte SHA-256 du jeton :

```json
[
  {"client_id": "cockpit-prod", "token_sha256": "<64 hex>", "scopes": ["rag:search"]}
]
```

Une entrée portant un jeton en clair est **refusée**. Le runtime se ferme au
démarrage si le registre est absent ou irrecevable.

## Filtres : placement ET métadonnées, jamais OU

Deux familles de dimensions coexistent et ne se confondent pas.

* Les **dix dimensions de placement** — `audience`, `candidat`, `collection`,
  `matiere`, `niveau`, `programme_version`, `school_year`, `tenant`,
  `visibility`, `voie` (`nexus_contracts.ingestion.ResourceScope`) — font
  autorité sur l'**accès**. Elles vivent dans `rag_artifact_placements`.
* Les dimensions **pédagogiques** — `notion`, `chapitre`, `type_document` —
  vivent sur les métadonnées de chunk. Elles décrivent le contenu ; elles ne
  décident de rien.

La sélection servie est donc

```
AUTORISÉ_PAR_PLACEMENT  ET  CORRESPOND_AUX_MÉTADONNÉES
```

et jamais un OU. `need.notions` est poussé jusqu'au SQL, conjoint au prédicat
de placement (`ingestor.retrieval_metadata_v2`). Un filtre de notion ne peut
donc que **retirer** des résultats ; il ne peut jamais en rendre visible un
que son placement interdit.

`need.desired_doc_types` et `need.difficulty_max` restent refusés (`422`) :
aucune colonne ne permet de les appliquer réellement, et annoncer une
restriction inopérante serait mentir sur ce qui est servi.

## Taxonomie

`GET /taxonomy/v2` rend les dimensions **réellement servables et autorisées
pour l'appelant** : intersection des collections signées de son enveloppe et
des collections retrievable du catalogue, chacune projetée par
`build_server_retrieval_scope`.

### Où vit `specialite`

`specialite` est une valeur de `StatutEnseignement`
(`nexus_contracts.document`). Sa représentation canonique est le champ
`statut` de la collection dans `configs/rag_collections.yml` — d'où provient
aussi le nom de collection (`rag_nexus_{matiere}_{niveau}_{statut}`,
ADR-0013). Elle est reprise telle quelle par
`ServerRetrievalScope.statut_enseignement`.

`statut_enseignement` **n'est pas** l'une des dix dimensions de placement :
il n'apparaît pas dans `ResourceScope`. L'endpoint l'expose donc comme une
**vue**, relue à la fois du catalogue et du scope serveur dérivé ; une
divergence entre les deux ferme la vue (`403`) plutôt que d'en élire une.
Aucune seconde vérité n'est écrite en base.

## Observabilité

Chaque requête servie émet une ligne JSON sur le logger
`nexus.retrieval.access` :

`request_id`, `client_id`, `granted_scopes`, `endpoint`, `status_code`,
`latency_ms`, `filters` (collection, empreinte de scope, notions),
`candidate_count`, `returned_count`, et l'état de chaque canal
(`embedding_status`, `dense_status`, `lexical_status`, `reranker_status`,
`dense_count`, `lexical_count`).

**La requête brute n'est jamais journalisée.** Elle peut nommer une personne
ou une difficulté scolaire ; seules son empreinte SHA-256 (`query_sha256`) et
sa longueur (`query_length`) sortent du processus. Le jeton porteur non plus
n'est jamais journalisé — seul le `client_id` déclaré.

`X-Request-ID` est repris s'il est sain (≤ 128 caractères,
`[A-Za-z0-9._:-]`), sinon un identifiant est généré : perdre la corrélation
vaut mieux que perdre la requête.
