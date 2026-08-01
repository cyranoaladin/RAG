# Design LOT40 — retrieval hybride et migrations

## Statut

**APPROUVÉ POUR PLANIFICATION**

Ce design détaille le contrat LOT40 du document canonique
`2026-07-31-pilot-go-live-finalization-design.md`. Le mandat de conduite du
projet et les validations successives autorisent le choix technique ci-dessous.
LOT40 reste un lot isolé : une branche, une PR et le rapport
`docs/reports/lot_40_hybrid_retrieval.md`.

## Objectif

Livrer dans `rag-engine` le chemin nominal PostgreSQL/pgvector du pilote :
retrieval dense et lexical, fusion RRF, rerank, diversification MMR, ordre total
stable et citations conformes au contrat. La migration est additive,
transactionnelle et réversible. Les tests couvrent les fonctions pures, les
requêtes SQL, une vraie base pgvector éphémère et le smoke HTTP.

LOT40 ne lit ni ne publie le corpus réel. Il ne lève aucun verrou de
gouvernance et ne met pas en œuvre les filtres d'identité exhaustifs de LOT41.

## Options examinées

### Étendre `retrieval_v2_endpoint.py`

Cette option minimise le nombre de fichiers, mais ajouterait le SQL lexical, la
fusion, le pool et MMR à un endpoint de plus de mille lignes qui duplique déjà
le pipeline. Les chemins `/search/v2`, `/chat` et warmup resteraient difficiles
à prouver identiques. Option rejetée.

### Réutiliser `database.py` et `hybrid_search.py`

Ces modules ciblent le schéma historique `rag_documents`/`tenant` et un champ
`embedding`, alors que le chemin v2 certifié utilise `rag_chunks`, `collection`,
`review_status` et `vector(1024)`. Leur rerank possède aussi un fallback RRF
fail-open. Une adaptation introduirait une seconde source de vérité. Option
rejetée ; les usages historiques ne sont pas supprimés dans ce lot.

### Extraire un noyau hybride v2

Option retenue. Un module v2 focalisé porte les candidats, les deux requêtes,
RRF, rerank, MMR et le mapping de résultat. Un module séparé porte le cycle de
vie du pool. L'endpoint conserve le gate `retrievable`, l'authentification et
les DTO, puis délègue tous ses chemins au même pipeline. Il ne prétend pas
charger un verrou de gouvernance appartenant à un autre service.

## Architecture

### Migration, registre et head

Le runner possède un registre unique `rag_schema_migrations` :

| Colonne | Contrat |
|---|---|
| `version` | entier positif, clé primaire |
| `file_name` | nom de fichier unique et non vide |
| `sha256` | exactement 64 hexadécimaux minuscules |
| `applied_at` | `timestamptz NOT NULL DEFAULT now()` |

Le manifeste versionné est la suite contiguë des fichiers `NNN_*.sql`, triée
par numéro, et `infra/postgres/migrations/HEAD` contient exactement
`002_hybrid_retrieval`. Le SHA-256 est calculé sur les octets du fichier. Une
migration est appliquée et sa ligne de registre insérée par la même session
`psql --single-transaction`, sous verrou consultatif PostgreSQL. Il n'existe
donc aucun état où le DDL est validé sans son enregistrement, ou l'inverse.

Pour une base neuve, le runner crée le registre, applique `001`, l'enregistre,
puis applique `002`. Pour une base v2 antérieure au registre, il accepte une
reconnaissance contrôlée de **l'un des deux états exacts** `001` ou `002` :
registre absent et validateurs exhaustifs verts (extension, table, colonnes,
contraintes, index, `vector(1024)`, puis absence exacte ou définition exacte
des objets hybrides). Tout schéma partiel, supplémentaire ou divergent est
refusé avant backup et avant mutation ; `001` n'est jamais marqué sur la seule
présence de `chunk_id`.

L'adoption d'un schéma exact `001` crée le registre et insère la ligne `001`
dans une transaction sous verrou, puis applique normalement `002` dans une
seconde transition. L'adoption d'un bootstrap `init.sql` déjà exact `002` crée
le registre et insère les lignes `001` et `002`, avec leurs noms et SHA issus
du snapshot immuable, dans **une seule transaction** sous verrou consultatif ;
aucun DDL de migration n'est rejoué. Les validateurs `001`, `002` et registre
sont répétés avant commit. Un échec après les insertions laisse le registre
entièrement absent. Les marqueurs distinguent migrations réellement appliquées
et versions seulement adoptées (`MIGRATIONS_APPLIED` / `MIGRATIONS_ADOPTED`).

La migration `002_hybrid_retrieval.sql` ajoute à `rag_chunks` une colonne
`text_tsv` générée depuis `coalesce(text, '')` avec la configuration française
et l'index GIN `idx_rag_chunks_text_tsv`. Le rollback versionné vit dans
`infra/postgres/rollbacks/002_hybrid_retrieval.down.sql`, hors du répertoire
parcouru par le runner. Dans une transaction unique, il supprime cet index et
cette colonne, puis la ligne `002`; le head effectif redevient `001`. Un nouvel
up rétablit `002`. Aucune donnée source n'est supprimée.

Avant toute mutation, le runner refuse : version enregistrée inconnue du
manifeste, checksum différent, trou ou doublon de versions, ordre invalide,
head déclaré différent du dernier fichier, ou invariant de schéma divergent du
head enregistré. Après chaque transition il revalide le schéma. Le backup
obligatoire existant est conservé. Aucun DSN ni chemin absolu de machine n'est
versionné.

### Pool PostgreSQL

`pg_pool.py` encapsule `psycopg_pool.ConnectionPool`. Le pool est paresseux,
partagé par processus, borné et fermable explicitement. Une taille invalide,
un DSN absent, un timeout ou une connexion indisponible produit une erreur
contrôlée ; aucun appel direct à `psycopg.connect` ne subsiste dans le chemin
retrieval nominal.

Les paramètres de pool sont bornés et lus au démarrage du composant. Les tests
injectent une fabrique de connexion, sans toucher à un store externe. Le lock
canonique utilisé par `make install` aligne `psycopg`, `psycopg-binary` et
`psycopg-pool` sur une seule version compatible ; un test repart d'une
installation propre et importe effectivement `psycopg_pool`.

### Pipeline hybride v2

Le flux nominal est unique :

```text
requête brute
  → format `query:` pour le seul embedding dense
  → pool dense ANN borné 200+1 puis au plus 50 + lexical français top-50,
    tous deux reviewed-only
  → RRF alpha=0.7, k=60
  → rerank MiniLM-L-6-v2
  → seuil 1.90
  → MMR déterministe sur les vecteurs stockés des passages
  → déduplication documentaire et top-k
  → DTO et citations
```

La recherche lexicale reçoit la requête brute, jamais le préfixe E5. Dense et
lexical appliquent `collection = %s` et `review_status = 'reviewed'` avant tout
classement. Les valeurs sont paramétrées ; aucune colonne ou clause arbitraire
ne provient du client.

Les deux classements SQL normatifs sont :

```sql
-- dense, query_vector paramétré et dimensionné à 1024
WITH hnsw_candidates AS MATERIALIZED (
  SELECT toutes_les_colonnes_necessaires,
         vector <=> query_vector AS distance
  FROM rag_chunks
  WHERE univers_admissible
  ORDER BY distance ASC
  LIMIT 201
), ranked_pool AS MATERIALIZED (
  SELECT *, row_number() OVER (ORDER BY distance ASC, chunk_id ASC) AS pool_rank
  FROM hnsw_candidates
)
SELECT ..., 1 - distance AS dense_score, diagnostic_frontiere_200_201
FROM ranked_pool
WHERE pool_rank <= requested_limit -- requested_limit <= 50
ORDER BY distance ASC, chunk_id ASC

-- lexical, tsquery calculée une seule fois dans un CTE
plainto_tsquery('french', raw_query) AS lexical_query
ts_rank_cd(text_tsv, lexical_query, 32) AS lexical_score
WHERE text_tsv @@ lexical_query
ORDER BY lexical_score DESC, chunk_id ASC
LIMIT 50
```

Le bit de normalisation `32` rend le rang lexical `rank/(rank+1)`. Avant ces
classements, les deux canaux utilisent le même univers admissible : collection
demandée, `review_status='reviewed'`, texte non blanc, vecteur non nul et trois
champs de provenance non blancs. Une requête transformée en `tsquery` vide est
un canal lexical vide valide.

Le canal dense est un parcours ANN réellement borné : la seule lecture de
`rag_chunks` matérialise au plus 201 lignes, soit un pool de 200 plus une
sentinelle. Le SELECT extérieur ne relit jamais la table et ne classe que ce
pool. `chunk_id ASC` donne l'ordre total exact **à l'intérieur du pool ANN** et
`dense_score` vaut exactement `1 - cosine_distance`, fini, sans
renormalisation cachée. LOT40 ne garantit donc pas le top-50 exact global de la
collection. Un underfill HNSW est un résultat dense valide, sans second scan ni
fallback exact.

Si les distances aux rangs 200 et 201 sont égales, le canal échoue de façon
générique : l'appartenance déterministe à la frontière du pool n'est pas
démontrable. Une fixture de 52 égalités, entièrement contenue dans le pool,
retourne bien `000..049`; une fixture de plus de 201 égalités prouve le refus
fail-closed. Le classement lexical, lui, conserve son top-50 SQL déterministe
global sur son univers filtré.

Chaque canal retourne au plus 50 candidats et le pool fusionné contient donc
au plus 100 `chunk_id`. Les rangs commencent à 1. Pour un candidat `c`, la
formule exacte est :

```text
rrf(c) = 0.7 / (60 + rang_dense(c)) + 0.3 / (60 + rang_lexical(c))
```

Le terme d'un canal absent vaut zéro. Un canal exécuté correctement mais vide
est un résultat valide et les candidats de l'autre canal suivent néanmoins le
rerank ; une erreur d'exécution d'un canal ferme toute la requête en 503. La
fusion déduplique par `chunk_id` et ordonne par `(rrf DESC, chunk_id ASC)`.
Avec dense `[A, B, C]` et lexical `[B, D, A]`, la référence attendue est
`[A, B, C, D]` et les tests comparent les fractions exactes.

Le reranker reçoit la requête brute et le texte de chaque candidat. Il doit
retourner exactement un logit fini par candidat. Après le seuil inclusif
`logit >= 1.90`, l'ordre intermédiaire est
`(logit DESC, rrf DESC, chunk_id ASC)`.

MMR utilise `lambda=0.7`, sans ré-embedding : les vecteurs `rag_chunks.vector`
ont déjà été produits avec le préfixe canonique `passage:`. La pertinence est
`sigmoid(logit)`. À chaque itération :

```text
mmr_raw(c) = 0.7 * sigmoid(logit(c))
             - 0.3 * max(cosine(c, élément_déjà_sélectionné))
score_final(c) = (mmr_raw(c) + 0.3) / 1.3
```

Le maximum de similarité vaut zéro pour le premier élément. Les cosinus et le
score final doivent être finis ; le score public est borné à `[0, 1]` pour le
contrat. À égalité MMR, l'ordre total est
`(mmr_raw DESC, logit DESC, rrf DESC, chunk_id ASC)`. La réponse suit l'ordre
de sélection MMR. Dès qu'un candidat est sélectionné, tous ses frères de même
`doc_id` sont retirés du pool **avant** l'itération suivante : ils ne peuvent
donc ni être servis, ni influencer la pénalité de similarité. MMR continue
jusqu'à `top_k` ou épuisement des `doc_id` uniques, ce qui évite un résultat
sous-rempli tant qu'un document admissible reste disponible. Les candidats
non reviewed, sans texte, vecteur ou provenance complète ont déjà été retirés
avant les rangs SQL et n'entrent jamais dans RRF, rerank ou MMR.

La fixture de référence `A(logit=2,[1,0])`, `B(logit=2,[1,0])`,
`C(logit=1.9,[0,1])`, portés par trois `doc_id` distincts, avec les mêmes
scores RRF et `chunk_id A < B < C`, donne l'ordre `[A, C, B]`. Une seconde
fixture contient `A1` et `A2` pour `doc-X`,
plus `B` pour `doc-Y` et `C` pour `doc-Z` : après la sélection de `A1`, `A2`
est retiré avant le calcul suivant et un `top_k=3` retourne trois documents.

Le modèle d'embedding reste `intfloat/multilingual-e5-large`, dimension 1024.
Le reranker reste `cross-encoder/ms-marco-MiniLM-L-6-v2`. Le seuil reste 1.90.
Ces valeurs ne sont ni recalibrées ni remplacées par le prototype historique.

### Endpoint et citations

`retrieval_v2_endpoint.py` conserve :

- le gate de collection `retrievable` ;
- les rôles et le refus reviewed-only ;
- les modèles de requête/réponse ;
- les endpoints de catalogue, cache et chat.

`/search/v2`, `/chat` et le warmup appellent le même pipeline injecté. Le cache
ne redevient pas une source de réponse publique : les statuts courants sont
toujours relus en base. Les hits exposent les scores dense, lexical, RRF et
rerank ainsi que le score final pour la preuve, sans modifier
`packages/contracts`.

Le mapping est explicite pour les trois consommateurs :

- `/search/v2` conserve son DTO local `SearchV2Hit`, lui ajoute `page` et les
  quatre scores d'étape plus `score_final`, et expose toujours les quatre
  champs de provenance `source_label`, `source_uri`, `rights`, `page` ;
- `/chat` transforme le hit interne en `RetrievalResult` contractuel :
  `score=score_final`, extrait non vide et `Citation.page=page_start` seulement
  si la page est positive ; les scores d'étape restent dans `metadata` ;
- le warmup met en cache la sérialisation du même `SearchV2Hit`, mais cette
  cache n'est jamais servie publiquement sans revalidation courante en base.

Une citation n'est construite que si `source_label`, `source_uri` et `rights`
sont non vides. Un candidat incomplet, sans texte ou sans vecteur est exclu
avant la réponse plutôt que servi sans provenance.

### Génération conversationnelle fermée

Le code actuel de `/chat` appelle OpenRouter lorsqu'une clé est présente, sans
charger le verrou canonique de gouvernance. LOT40 supprime cette capacité du
chemin actif : après retrieval, `/chat` retourne la réponse de refus
`answer_generation_locked` avec les `retrieval_hits` autorisés, et
`_openrouter_answer` n'est jamais appelé, même si `OPENROUTER_API_KEY` est
défini. Ce refus dur reste en place jusqu'à un lot explicitement autorisé par
ADR et par le contrat/API de gouvernance ; `rag-engine` ne lit pas directement
les fichiers internes de `rag-pedago`. Les fichiers et valeurs de verrous
restent bit à bit inchangés dans LOT40.

## Gestion des erreurs

Le mode nominal est fail-closed :

- erreur dense ou lexicale : HTTP 503 ;
- pool/DSN indisponible : HTTP 503 sans exposition du DSN ;
- modèle, dimension, reranker ou MMR indisponible : HTTP 503 ;
- nombre de scores différent du nombre de candidats : HTTP 503 ;
- candidat non reviewed ou provenance incomplète : candidat exclu ;
- génération `/chat` : refus déterministe `answer_generation_locked`, sans
  appel réseau ;
- aucune correspondance au-dessus du seuil : réponse vide valide.

Il n'existe aucun fallback dense seul, lexical seul, RRF sans rerank, MMR sans
embeddings, modèle alternatif ou seuil abaissé. Le prototype LOT41 contenu dans
les stashes n'est pas repris.

## Tests et preuves

Les tests unitaires prouvent notamment :

- RRF exact avec `alpha=0.7`, `k=60`, déduplication et égalités stables ;
- préfixes `query:`/`passage:` au bon endroit ;
- formule MMR, fixture `[A, C, B]`, score borné et déduplication par document ;
- erreurs fail-closed de chaque étage ;
- requêtes paramétrées et filtres reviewed-only des deux canaux ;
- mapping de citation des trois consommateurs et page conforme au contrat ;
- clé OpenRouter présente mais aucun appel réseau lorsque la génération est
  verrouillée ;
- pool paresseux, borné, réutilisé puis fermé.

Une base éphémère et nommée utilise la référence immuable
`pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`.
Le rapport consigne ce digest OCI. Elle valide la migration, le down, le nouvel
up et une recherche HTTP avec modèles déterministes injectés. Après `ANALYZE`,
la preuve du GIN ouvre une transaction, exécute
`SET LOCAL enable_seqscan = off`, puis `EXPLAIN` sur la requête lexicale et
exige `idx_rag_chunks_text_tsv`; elle ne dépend donc pas de la préférence du
planner sur une petite fixture.

Pour le dense, une fixture synthétique de 45 000 lignes cibles, complétée par
des lignes hors collection et non reviewed, rend le choix HNSW naturel. Un
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` sur le SQL de production exige une
unique lecture de `rag_chunks`, un `Index Scan` nommé exactement
`idx_rag_chunks_vector`, au plus 201 lignes matérialisées dans
`hnsw_candidates` et aucun tri portant sur plus de 201 lignes. Une preuve
structurelle séparée désactive les scans concurrents; elle ne se substitue pas
au plan naturel. L'underfill forcé par `ef_search=1/max_scan_tuples=1` reste
borné et n'est jamais comparé à un top global. Sur la fixture aux distances
distinctes, une comparaison au préfixe d'un oracle exact désactivant l'index
est seulement une observation empirique de fixture, pas une garantie du canal
ANN. Le temps du plan est consigné à titre informatif, sans seuil normatif.

Un `PgCandidateStore` réel et `/search/v2` utilisent aussi une connexion du
rôle applicatif sans pré-régler `ef_search` ni `max_scan_tuples`; le store ne
fait que l'activation pgvector et `strict_order`. Ils prouvent un résultat
dense non vide, cohérent et borné à 50, sans exiger qu'il soit rempli.

Le test ne monte aucun corpus réel. Il démarre d'abord le bootstrap réel de
`docker-compose.v2.yml` en montant le même `init.sql` dans l'image épinglée,
prouve l'adoption atomique de son head `002` sans registre, puis conserve le
cycle depuis une base entièrement fraîche dans une seconde base isolée du même
conteneur.

Le runner détruit son conteneur et son volume temporaires avec un `trap`, y
compris en erreur. Avant toute création, il prouve l'absence des deux noms. Les
deux ressources portent le label propriétaire unique
`com.nexus.lot40.owner=<token>` où le token cryptographiquement aléatoire est
indépendant des noms. Après création, le runner capture l'ID Docker immuable du
conteneur et le couple label/`CreatedAt` du volume. Le cleanup revalide
immédiatement ces identités, supprime le conteneur par ID et refuse toute
substitution de nom, de label ou d'empreinte. Une collision, une course de
création, un label absent/divergent ou une erreur d'inspection ferme le runner
sans supprimer la ressource concernée. Il ne réutilise jamais `rag_pgvector` ni
un volume existant. Pour le volume, l'API Docker ne fournit pas de suppression
conditionnelle atomique : un administrateur du daemon peut encore remplacer la
ressource entre la dernière inspection et `volume rm`; cette limite TOCTOU est
inhérente à l'autorité administrateur du daemon, et non contournable par le
runner.

Une cible Make dédiée `test-integration-hybrid` orchestre le conteneur nommé,
l'adoption `002`, `002 → 001 → 002`, puis `001 → 002 → 001 → 002` sur la base
fraîche, le retrieval réel et le smoke HTTP. Elle est appelée
explicitement par le job GitHub `rag-engine` **et** par `scripts/ci-local.sh`,
en plus de `make test`. Les tests de topologie/fail-safe échouent si l'un des
deux raccordements ou le nettoyage disparaît. LOT40 ne peut donc être vert dans
aucune des deux CI en éludant l'intégration pgvector.

Le rapport du lot consigne les commandes, le SHA candidat, le head de migration
et les résultats unitaires, DB, smoke, lint, types, CI locale et GitHub.

## Hors périmètre

- aucune évolution de `nexus-contracts` ;
- aucun filtre serveur d'identité, tenant, candidat ou année de LOT41 ;
- aucun accès à un corpus réel ni publication pgvector ;
- aucune activation des verrous de validation ou publics ;
- aucune génération OpenRouter ;
- aucune suppression des chemins historiques encore utilisés.

## Critères d'acceptation

LOT40 est livrable seulement si les migrations `up → down → up`, le retrieval
hybride réel sur DB éphémère, le smoke HTTP, les tests unitaires, Ruff, mypy,
les verrous de gouvernance, la CI locale et les checks GitHub sont tous verts
sur la tête candidate. Le verdict global reste `GO_LIVE: NO_GO` et LOT41 ne
commence qu'après la fusion de LOT40 dans `main`.
