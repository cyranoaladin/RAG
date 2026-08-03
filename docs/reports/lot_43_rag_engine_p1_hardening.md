# LOT43 — Correctifs P1 rag-engine (routes legacy, SSRF, migrations automatiques)

## Verdict

**Sous-lot `rag-engine` P1 hardening : TERMINÉ et validé localement
(voir §43.1–43.7).**
**Verdict global de clôture : `NOT_READY_FOR_PRODUCTION`** — voir la
section « Rapport de clôture du lot » en fin de document pour le détail
complet (périmètre couvert, tests, risques résiduels, LOT44+ restant).

*Mise à jour : ce rapport a été révisé après une seconde passe de
vérification (relecture indépendante de l'état réel du dépôt, exécution
effective des tests annoncés, audit ciblé de signaux de sécurité résiduels,
puis validation Compose fraîche isolée avec parcours complet ingestion →
review → retrieval). La rédaction initiale de ce rapport sous-déclarait le
travail réellement livré, et deux vrais gaps ont été trouvés et corrigés
depuis : timeouts de readiness (§43.6), et un bug de packaging Docker
bloquant (§43.7) qui aurait rendu `/review/v2/*` et `/search/v2`
inutilisables (500) dans **toute** image construite depuis ce dépôt. Le
contenu ci-dessous reflète l'état réel du dépôt à la date de révision, pas
seulement l'intention initiale du lot.*

Les trois bloqueurs P1 identifiés dans le cadrage de l'usine d'ingestion
agentique (fermeture des routes legacy, SSRF, migrations automatiques) sont
corrigés et testés — **y compris `/collections` et `/stats/{name}` (ChromaDB
direct), initialement signalées comme hors périmètre puis effectivement
fermées avant la fin de ce lot (§43.1)**. Trois durcissements complémentaires,
non anticipés dans le cadrage initial mais découverts nécessaires en cours de
lot, ont également été livrés : scope serveur obligatoire à l'ingestion
(§43.4), quotas et limites applicatives (§43.5), et bornage des connexions
Postgres directes du health-check/readiness (§43.6). Ce lot ne construit
**pas** l'orchestrateur agentique lui-même (contrats, MCP, agents
spécialisés, scheduler) : il s'agit délibérément d'un premier lot de
stabilisation, condition préalable convenue avec l'utilisateur avant
d'attaquer les phases suivantes (LOT44+).

Aucun verrou de gouvernance (`services/rag-pedago/configs/pedago_interface_contract.yml`)
n'a été touché. Aucune capacité de publication automatique n'a été ajoutée.

## Périmètre

| Élément | Valeur |
| --- | --- |
| Date | 2026-08-03 |
| Baseline `main` | `ea18ba52da5778f628c4943705dd81dfa43fbc15` |
| Branche | `lot-43-rag-engine-p1-hardening` |
| Service modifié | `services/rag-engine` uniquement |
| Contrats (`packages/contracts`) | aucun changement |
| Gouvernance (`services/rag-pedago`) | aucun changement |
| Cockpit | aucun changement |

## Contexte : pourquoi ce lot avant l'usine d'ingestion agentique

Un audit initial (4 inventaires parallèles sur rag-engine, rag-pedago,
contracts/cockpit, docs/CI) a montré que l'essentiel de l'architecture
agentique demandée existe déjà à des degrés divers (orchestrateur
Level/Subject, `EduscolAgent`, `SourceValidator` avec RightsAgent fail-closed,
gouvernance `quality → gate → review` par verrous). En revanche, trois bugs de
sécurité/fiabilité réels et actuels ont été détectés côté `rag-engine`,
indépendants de la fonctionnalité à construire. Il a été décidé avec
l'utilisateur de les traiter en premier (LOT43), avant les lots suivants
(contrats canoniques, MCP, orchestrateur, agents spécialisés — LOT44+).

## Constats corrigés

### 43.1 — Routes d'ingestion legacy exposées publiquement

**Avant** : `infra/nginx/rag-v2.conf` et `infra/nginx/rag-api.conf.template`
routaient `/ingest` en préfixe générique vers l'upstream applicatif, qui
héberge à la fois le routeur v2 (`/ingest/v2/*`) et les handlers historiques
`api.py` (`/ingest`, `/ingest/urls`, `/ingest/upload-files`, `/ingest/drive`,
`/ingest/check-duplicates`) interrogeant ChromaDB. Le commentaire en tête de
`ingest_v2_endpoint.py` affirmait à tort que ces routes legacy étaient déjà
isolées.

**Après** : allowlist explicite au niveau Nginx — seul `/ingest/v2/*` est
proxié ; tout le reste sous `/ingest*` renvoie `410` par défaut, dans les deux
fichiers de configuration (parité avec le traitement déjà appliqué à
`/search`, `/kb`, `/rag` en LOT41). Le commentaire trompeur a été corrigé.

**Traité dans ce même lot (revu depuis la version initiale de ce rapport)** :
`/collections` et `/stats/{collection_name}` dans `api.py` interrogent aussi
directement ChromaDB et ne sont plus utilisées par l'UI v2 (confirmé par
`test_ui_app_v2_admin.py`, qui vérifie leur absence au profit de
`/collections/v2`). Une première version de ce lot les avait laissées
ouvertes par prudence de périmètre ; elles ont finalement été fermées (410)
au même niveau Nginx que les autres routes legacy, sans élargir le
périmètre applicatif (aucun changement dans `api.py` — uniquement les
allowlists Nginx) :
- `location = /collections { return 410; }` (match exact, ne masque pas
  `/collections/v2`) ;
- `location ^~ /stats { return 410; }` (préfixe, aucune route `/stats/v2`
  homonyme à préserver).

Tests : `tests/test_lot43_ingest_legacy_closure.py` (fermeture de
`/ingest*` legacy), parsing statique des deux fichiers Nginx, sans
dépendance à un nginx réel — même technique que
`tests/test_lot41_legacy_route_closure.py`, qui reste vert ;
`tests/test_lot43_chromadb_legacy_closure.py` (nouveau, fermeture de
`/collections`/`/stats`), même technique, vérifie explicitement que la
fermeture est un match exact (`=`) pour `/collections` — pas un préfixe
(`^~`) qui masquerait `/collections/v2`.

### 43.2 — Protection SSRF incomplète et incohérente

**Avant** : `ingest_v2_endpoint._validate_url` bloquait une liste statique de
hosts et les IP littérales privées/loopback/link-local, mais ne résolvait
jamais le DNS pour un nom de domaine (un domaine pointant vers une IP privée
passait), et l'appel `httpx.get(url, follow_redirects=True)` ne revalidait pas
la destination après redirection. Un second point d'entrée, `tasks.py`
(`_load_source_text`, tâche Celery `ingest_document_task`), faisait un
`requests.get` totalement non validé — sans appelant actuel dans le code,
mais réellement enregistré et exécutable par le worker Celery.

**Après** : nouveau module `src/ingestor/ssrf_guard.py`, point d'entrée unique
pour tout fetch d'URL externe :
- résolution DNS complète (tous les A/AAAA) et validation de chaque IP
  (loopback, RFC1918, link-local, multicast, unspecified, reserved) ;
- schémas `http`/`https` uniquement, rejet des credentials embarqués dans
  l'URL, rejet des ports hors 80/443 ;
- redirections suivies manuellement avec revalidation à **chaque** saut, via
  un transport `httpx` dédié (`_RevalidatingTransport`) qui réexécute la
  résolution/validation juste avant chaque dispatch réseau — réduit
  fortement la fenêtre de TOCTOU exploitable par du DNS rebinding, sans
  toutefois offrir un épinglage IP au niveau TCP/TLS (limite connue,
  documentée dans le code : un épinglage complet casserait la vérification
  SNI/certificat pour HTTPS sans complexification significative hors
  périmètre de ce lot) ;
- limite de redirections, timeouts connect/read/write/pool, streaming avec
  coupure dès dépassement de `max_bytes`.

Branché dans `ingest_v2_endpoint.ingest_urls_v2` (remplace `_validate_url` +
`httpx.get` brut) et dans `tasks._load_source_text` (remplace le
`requests.get` non validé).

Tests : `tests/test_ssrf_guard.py` (16 cas), entièrement déterministes —
résolution DNS monkeypatchée, réponses HTTP simulées via
`httpx.MockTransport`, aucun accès réseau réel. Couvre : loopback, RFC1918,
IPv6 link-local (`fe80::/10` et ULA `fd00::/8`), endpoint metadata cloud
(`169.254.169.254`), domaine avec IP mixte publique/privée, schéma interdit,
credentials en URL, redirection vers destination privée, DNS rebinding entre
validation et dispatch, redirections excessives, réponse trop volumineuse,
timeout.

### 43.3 — Migrations PostgreSQL non appliquées automatiquement

**Avant** : `infra/postgres/init.sql` (monté en
`docker-entrypoint-initdb.d`) ne crée qu'un schéma partiel — confirmé par un
test d'intégration réel : sur un volume vierge, `rag_chunks` est créée sans
les colonnes de scope LOT41 (`tenant`, `candidat`, `visibility`,
`school_year`, `programme_version`), et sans la table de registre
`rag_schema_migrations`. Le seul outil capable d'amener le schéma à son head
déclaré (`infra/scripts/apply_pgvector_migrations.sh`) exige `docker exec`
sur un conteneur déjà nommé, `BACKUP_ROOT`, et une sauvegarde `pg_dump`/
`docker cp` — conçu pour une upgrade opérateur de production avec données
réelles, pas pour un bootstrap automatique de `docker compose up`. Un volume
vierge démarrait donc aujourd'hui avec un schéma v2 incomplet, non
compatible avec le code applicatif déjà fusionné (LOT41) qui suppose ces
colonnes présentes.

**Après** : nouveau script `infra/scripts/bootstrap_pgvector_schema.sh`, qui
réutilise intégralement (aucune duplication de logique SQL) la bibliothèque
partagée `infra/scripts/lib/pgvector_migration_state.sh` déjà utilisée par
l'outil opérateur (découverte de manifeste, validation par somme de contrôle,
détection de trous/désordre dans le registre, verrou `pg_advisory_xact_lock`,
détection d'un schéma non enregistré). Différences volontaires par rapport à
l'outil opérateur :
- connexion directe via `psql`/variables libpq standard (`PGHOST`, `PGPORT`,
  `PGUSER`, `PGPASSWORD`, `PGDATABASE`) au lieu de `docker exec` — utilisable
  comme conteneur d'init dans le réseau compose, sans socket Docker monté ;
- pas de sauvegarde `pg_dump`/`docker cp` — les migrations sont additives et
  non destructrices par construction (mêmes fichiers SQL, mêmes garde-fous
  `NOT VALID`/`VALIDATE CONSTRAINT`, refus explicite de 001 face à des
  données legacy non vides) ; un volume vierge n'a de toute façon rien à
  sauvegarder. **Pour une upgrade de production avec données réelles et
  garantie de rollback, l'outil opérateur `apply_pgvector_migrations.sh`
  reste l'outil de référence, pas ce script.**
- revalidation complète de l'état après application (jamais de confiance
  aveugle dans sa propre comptabilité) : échec explicite si le head effectif
  ne correspond pas au head déclaré.

Nouveau service `migrator` dans `infra/docker-compose.v2.yml` (image
`pgvector/pgvector:pg16`, déjà dotée de `psql` — pas de client Postgres ajouté
à l'image applicative), déclenché après `pgvector: service_healthy` ;
`ingestor` et `worker` déclarent désormais `migrator: condition:
service_completed_successfully` en dépendance, donc ne démarrent plus avant
que le schéma soit confirmé à jour.

Tests : `tests/integration/test_migrations_autorun.py` (marqué
`integration`, ignoré si Docker indisponible) — **test réel**, pas de
commande-double : démarre un vrai conteneur `pgvector/pgvector:pg16` sur un
volume neuf, applique `init.sql` (ce que fait
`docker-entrypoint-initdb.d` en production), exécute le script de bootstrap,
et vérifie en base : le registre contient bien les versions 1/2/3, les
colonnes de scope LOT41 sont présentes, une seconde exécution est idempotente
(`MIGRATIONS_APPLIED=0`), et une falsification de checksum en base est
détectée et bloque explicitement (`MIGRATION_CHECKSUM_MISMATCH`). Confirme
que le bug était réel (échec de la première assertion avant le correctif) et
que le correctif le résout.

La configuration Compose modifiée a été validée avec `docker compose config`
(Docker Compose v5.3.1, résolution complète du service `migrator` et de la
condition `service_completed_successfully`). Le test de bout en bout complet
(`docker compose down -v && docker compose up` sur l'ensemble de la stack
v2) n'a **pas** été exécuté dans cet environnement : un conteneur
`rag_pgvector` déjà actif et apparemment important (probablement un
déploiement réel ou une session antérieure) occupe le même nom/sous-réseau,
et il a été jugé plus sûr de ne pas y toucher. Recommandation : exécuter ce
test complet sur un hôte/CI dédié avant mise en production.

### 43.4 — Scope complet absent des chunks ingérés en v2

**Avant** : `ingest_document` (`ingest_v2.py`) écrivait chaque chunk sans
jamais renseigner `tenant`, `candidat`, `visibility`, `school_year` et
`programme_version` — colonnes de scope gouvernées introduites en LOT41
(migration `003_profile_filtering.sql`). Ces colonnes restaient `NULL`. Or le
retrieval v2 (`retrieval_pg_v2.py`) filtre avec des égalités strictes du
type `WHERE tenant = $2` : une colonne `NULL` ne satisfait jamais une égalité
en SQL. Conséquence réelle : **aucun chunk ingéré via `/ingest/v2` ne
pouvait jamais être retourné par une recherche scopée**, y compris après
review humaine (`reviewed`) — le pipeline d'ingestion produisait des
ressources orphelines, invisibles du retrieval par construction.

**Après** : un scope serveur par défaut, unique pour tout le déploiement,
est lu et validé depuis l'environnement (`NEXUS_DEFAULT_TENANT`,
`NEXUS_DEFAULT_CANDIDAT`, `NEXUS_DEFAULT_VISIBILITY`,
`NEXUS_DEFAULT_SCHOOL_YEAR`, `NEXUS_DEFAULT_PROGRAMME_VERSION`) et injecté
dans chaque ligne insérée. Fail-closed strict, conforme à `AGENTS.md`
(« toute ambiguïté doit produire une quarantaine, jamais une affectation
arbitraire ») : une variable absente, ou une valeur hors de l'énumération
autorisée (`candidat`, `visibility`) ou de la forme attendue (`school_year`
au format `AAAA-AAAA` consécutif), fait échouer `ingest_document` **avant**
tout chunking/embedding — jamais de colonne `NULL` écrite silencieusement.
Ajouté aussi au service `ingestor`/`worker` de `docker-compose.v2.yml`
(`NEXUS_DEFAULT_*: ${...:?... requis}` — échec explicite au démarrage si
absent).

**Limite assumée et documentée dans le code** (`ingest_v2.py`, commentaire
au-dessus de `_get_default_scope`) : c'est un correctif minimal, pas une
modélisation complète du multi-tenant. Une seule valeur par dimension pour
tout le déploiement — en particulier `candidat` varie réellement par
collection selon la convention `{population}_{niveau}` documentée dans
`AGENTS.md` (`libre_terminale`, `aefe_seconde`, etc.). Modéliser cela
proprement exige d'étendre le catalogue de collections
(`configs/rag_collections.yml`, 59 entrées) avec un scope gouverné par
collection et un ADR dédié — non fait ici, tracé comme limitation connue.

Tests : `TestDefaultScope` et `TestCollectionQuota` dans
`tests/test_ingest_v2.py` — configuration valide, chaque variable manquante
individuellement, valeurs hors énumération, formats d'année invalides, et un
test de bout en bout applicatif vérifiant que `ingest_document` échoue avant
d'atteindre l'embedding si le scope n'est pas configuré.

### 43.5 — Quota par collection et limites applicatives d'ingestion

**Avant** : aucune limite indépendante du reverse proxy sur la taille des
fichiers uploadés (lecture non bornée `upload_file.file.read()`), le nombre
de fichiers par requête, le nombre d'URLs par requête ou par domaine, le
nombre de pages PDF, la taille du texte extrait, ou le volume ingéré par
collection dans le temps.

**Après**, dans `ingest_v2_endpoint.py` (toutes configurables par variable
d'environnement, valeurs par défaut raisonnables) :
- lecture bornée des fichiers uploadés (`_read_upload_bounded`, jamais de
  `read()` illimité — abandon dès dépassement de `MAX_UPLOAD_FILE_BYTES`) ;
- `MAX_FILES_PER_UPLOAD`, `MAX_URLS_PER_REQUEST`,
  `MAX_URLS_PER_DOMAIN_PER_REQUEST` (anti-abus par domaine dans un même
  batch), `MAX_PDF_PAGES`, `MAX_EXTRACTED_TEXT_CHARS`.

Et dans `ingest_v2.py` : `MAX_CHUNKS_PER_COLLECTION_PER_DAY`, un quota
glissant sur 24h par collection, vérifié en base **avant** chunking/
embedding (`_check_collection_quota`), pour empêcher qu'une seule collection
n'épuise la capacité d'ingestion du déploiement.

Tests : `tests/test_lot43_ingest_limits.py` (6 tests — fichiers en excès,
fichier trop volumineux sans lecture illimitée, texte extrait trop long,
URLs en excès, pages PDF en excès, cap par domaine) et
`TestCollectionQuota` dans `test_ingest_v2.py` (quota atteint bloque avant
l'embedding, quota non atteint laisse le traitement continuer).

### 43.6 — Connexions Postgres non bornées sur `/health` et `/collections/readiness`

**Avant** : le chemin principal de retrieval (`PgCandidateStore` via le pool
partagé, `pg_pool.py`) est borné par `PG_POOL_TIMEOUT_S` (5s par défaut).
Mais deux connexions Postgres directes, hors pool, utilisées uniquement par
les vérifications de santé/readiness, ouvraient la connexion avec
`psycopg.connect(pg_dsn)` sans aucun `connect_timeout` :
`embedding_contract.pgvector_dimension` (utilisé par `/health`) et
`retrieval_v2_endpoint._get_reviewed_chunk_counts` (utilisé par
`/collections/readiness`). Si Postgres est injoignable ou trop lent à
répondre (au niveau TCP ou pendant la poignée de main du protocole), ces
deux appels pouvaient bloquer indéfiniment — un health-check qui ne répond
jamais est pire qu'un health-check qui répond `503` rapidement : il masque
la panne au lieu de la signaler.

**Après** : un `connect_timeout` borné (`PG_HEALTHCHECK_CONNECT_TIMEOUT_S`,
5s par défaut, même variable d'environnement dans les deux modules) est
passé explicitement à `psycopg.connect(...)` aux deux points d'appel. Les
deux fonctions restent fail-closed (exception → `503`), mais échouent
maintenant vite au lieu de ne jamais répondre.

Tests (TDD — rouge confirmé avant l'implémentation, puis vert) :
- `TestPgvectorDimensionConnectTimeout` (`tests/test_embedding_contract.py`) ;
- `TestReadinessConnectTimeout` (`tests/test_retrieval_v2_endpoint.py`).

Chaque classe couvre deux cas : (1) le paramètre `connect_timeout` est bien
transmis à `psycopg.connect` (assertion sur l'appel, sans réseau) ; (2) un
cas **réel et déterministe d'abandon** — un socket TCP local qui accepte la
poignée de main (`listen()` sans jamais appeler `accept()`) mais ne répond
jamais au protocole Postgres, simulant une base injoignable/bloquée ; le
test mesure le temps écoulé et vérifie qu'il reste borné (`< 5s` pour un
`connect_timeout` réduit à 1s dans le test), au lieu de dépendre d'un délai
TCP par défaut du système qui peut atteindre plusieurs dizaines de secondes.

### 43.7 — Validation Compose fraîche isolée + parcours complet ingestion → review → retrieval

Exécutée dans un projet Docker Compose strictement isolé (`docker compose -p
lot43fresh`), sans toucher la stack `infra` déjà active (`rag_pgvector`,
`rag_worker`, `rag_ui`, `rag_redis`) : conteneurs renommés, réseau dédié sur
un sous-réseau libre (`172.16.99.0/24`, vérifié non chevauchant contre les
17 réseaux Docker déjà présents sur l'hôte), volumes nommés et préfixés par
le projet (`lot43fresh_rag_pgvector_data`, etc.), ports publiés en mode
éphémère (`PGVECTOR_PORT=0`, etc. → Docker choisit un port libre). Config
validée avec `docker compose config` avant tout `up`, conformément à
`AGENTS.md`.

**Migrations sur volume réellement vierge, via Compose (pas un conteneur ad
hoc)** : `pgvector` démarré seul, healthy, puis `migrator` exécuté par
l'orchestration Compose réelle (`depends_on: service_healthy`) —
`MIGRATIONS_APPLIED=1`, `MIGRATIONS_ADOPTED=2`, `SCHEMA_VERIFICATION=OK`,
`SCHEMA_HEAD=3`, exit code 0. Schéma vérifié directement en base : colonnes
de scope LOT41 présentes, contraintes `_lot41_check` actives, index
`idx_rag_chunks_vector` (HNSW) et `idx_rag_chunks_profile_reviewed` créés,
registre `rag_schema_migrations` à jour (versions 1/2/3).

**Bug réel trouvé et corrigé : `.dockerignore` cassait toute identité signée
en conteneur.** En construisant `ingestor`/`worker` (images `lot43fresh-*`,
build complet y compris `sentence-transformers`/`torch`/`libreoffice` —
réseau sortant disponible pour pip malgré un test ICMP initial négatif ;
aucune image ni modèle n'a eu besoin d'être téléchargé pour Postgres/Redis/
Ollama, déjà en cache local), le premier appel à une route exigeant une
identité interne signée (`/review/v2/queue`) a **crashé en 500** :

```
FileNotFoundError: [Errno 2] No such file or directory:
'/usr/local/lib/python3.11/site-packages/nexus_contracts/artifacts/pilot-retrieval-scope-v1.json'
```

Cause : `.dockerignore` (racine du repo, `git blame` → commit `186b1750`,
2026-07-13, **antérieur à LOT43, sans rapport avec ce lot**) contient une
dénégation générique `**/artifacts` / `**/artifacts/**` destinée à exclure
les répertoires de build/CI — mais ce motif masque aussi
`packages/contracts/src/nexus_contracts/artifacts/`, qui contient la
ressource *requise au runtime* par
`identity_v2.load_identity_verifier_config()` (l'artefact pilote signé,
LOT38). Reproduit et confirmé avec un `docker build` réel minimal (pas une
réimplémentation des règles `.dockerignore`) : le fichier est absent du
contexte de build. Le bug est invisible dans la suite de tests existante
car le `.venv` hôte utilise `nexus-contracts` en **install éditable**
(`pip install -e`), qui lit directement l'arbre source et ne passe jamais
par le filtrage `.dockerignore` — seul un vrai build d'image Docker
l'exposait. **Impact réel non testé jusqu'ici : `/review/v2/queue`,
`/review/v2/decide`, `/search/v2`, `/collections/v2` et
`/collections/readiness` auraient échoué en 500 dans toute image
construite depuis ce dépôt**, y compris potentiellement la stack `infra`
déjà déployée selon la date de son dernier build.

Correctif : exception ciblée ajoutée après la dénégation générique dans
`.dockerignore` (`!packages/contracts/src/nexus_contracts/artifacts` +
`/**`), qui gagne comme dernière règle correspondante (sémantique Docker :
la dernière règle qui matche l'emporte). Aucune autre exclusion générique
n'est affaiblie.

Test (TDD — rouge confirmé avec Docker réel avant le correctif, puis vert) :
`tests/integration/test_docker_build_context_includes_pilot_artifact.py` —
construit une image jetable minimale (`FROM busybox`, pas de `pip install`,
donc rapide) qui copie `packages/contracts` et vérifie la présence du
fichier ; utilise le moteur Docker réel pour évaluer les motifs
`.dockerignore`, pas une réimplémentation qui pourrait diverger du
comportement réel.

**Parcours complet vérifié après correctif, avec un modèle d'embedding réel
(`intfloat/multilingual-e5-large`, cache pré-provisionné localement, monté
en lecture seule) et une identité interne réellement signée HS256 (secret,
émetteur, audience configurés pour ce test, alignés sur l'artefact pilote
canonique `packages/contracts/.../pilot-retrieval-scope-v1.json` — scope
`libre_terminale_maths_nsi_real_v1`) :**

1. `POST /ingest/v2/upload-files` (jeton de rôle `ingest_agent`) → chunk
   écrit, scope complet en base (`tenant=libre_terminale`, `candidat=libre`,
   `niveau=terminale`, `voie=generale`, `matiere=nsi`,
   `statut_enseignement=specialite`, `school_year=2026-2027`,
   `programme_version=BOEN_special_8_2019-07-25`),
   `review_status=needs_review`.
2. `GET /review/v2/queue` (jeton BFF + identité signée rôle `reviewer`) →
   le document apparaît (`total_pending_docs: 1`).
3. `POST /review/v2/decide` (`decision: reviewed`) → `chunks_affected: 1` ;
   vérifié en base : `review_status` passe à `reviewed`.
4. Vérifié en SQL direct que la ligne satisfait exactement le prédicat de
   scope utilisé par le retrieval (`_SCOPE_PREDICATE_SQL`, identique entre
   `review_v2_endpoint.py` et `retrieval_pg_v2.py`) avec
   `review_status = 'reviewed'` — la ligne est bien éligible côté
   autorisation SQL.
5. `POST /search/v2` (jeton BFF + identité signée rôle `student`) → `200
   OK`, pipeline hybride exécuté sans erreur, **0 résultat retourné** : le
   seuil de reranking `+1.90` (`retrieval_hybrid_v2.RERANK_THRESHOLD`,
   constante volontairement stricte, déjà couverte par les tests LOT40) n'a
   pas été atteint par une phrase de test générique isolée face à un
   cross-encoder — comportement de précision attendu, pas un échec
   d'autorisation ou de scope (confirmé par le point 4).

Cette validation ne couvre pas un « vrai » scoring de pertinence réussi
bout en bout (il faudrait un corpus et une requête soigneusement choisis
pour dépasser le seuil de reranking, hors périmètre de ce lot), mais couvre
et confirme réellement : migrations fraîches, scope complet à l'ingestion,
transition d'état de review via l'API réelle, et l'autorisation SQL de
retrieval jusqu'à la porte du seuil de pertinence.

Stack de test entièrement nettoyée après vérification (`docker compose
down -v` sur le projet isolé `lot43fresh` uniquement, puis suppression des
images `lot43fresh-*`) ; confirmé qu'aucun conteneur, volume, réseau ou
image ne subsiste, et que la stack `infra` déjà active n'a pas été touchée.

## Fichiers créés

- `services/rag-engine/src/ingestor/ssrf_guard.py`
- `services/rag-engine/infra/scripts/bootstrap_pgvector_schema.sh`
- `services/rag-engine/tests/test_lot43_ingest_legacy_closure.py`
- `services/rag-engine/tests/test_lot43_chromadb_legacy_closure.py`
- `services/rag-engine/tests/test_lot43_ingest_limits.py`
- `services/rag-engine/tests/test_ssrf_guard.py`
- `services/rag-engine/tests/integration/test_migrations_autorun.py`
- `services/rag-engine/tests/integration/test_docker_build_context_includes_pilot_artifact.py`
- `docs/reports/lot_43_rag_engine_p1_hardening.md` (ce rapport)

## Fichiers modifiés

- `services/rag-engine/infra/nginx/rag-v2.conf` (fermeture `/ingest*` +
  `/collections` + `/stats`)
- `services/rag-engine/infra/nginx/rag-api.conf.template` (idem)
- `services/rag-engine/src/ingestor/ingest_v2_endpoint.py` (SSRF, limites
  upload/URL/PDF/texte extrait)
- `services/rag-engine/src/ingestor/ingest_v2.py` (scope serveur par défaut,
  quota par collection)
- `services/rag-engine/src/ingestor/tasks.py` (SSRF sur `_load_source_text`)
- `services/rag-engine/src/ingestor/embedding_contract.py` (connect_timeout
  sur `pgvector_dimension`)
- `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`
  (connect_timeout sur `_get_reviewed_chunk_counts`)
- `services/rag-engine/src/ingestor/retrieval_contract_adapter.py`
  (docstring : statut non câblé documenté, LOT44)
- `services/rag-engine/infra/docker-compose.v2.yml` (service `migrator`,
  variables `NEXUS_DEFAULT_*` requises)
- `.dockerignore` (racine du repo — exception pour
  `packages/contracts/src/nexus_contracts/artifacts/`, cf. §43.7 ; bug
  antérieur à LOT43, sans rapport avec ce lot, trouvé lors de la validation
  Compose fraîche)
- `services/rag-engine/tests/test_ingest_v2.py` (classes `TestDefaultScope`,
  `TestCollectionQuota`)
- `services/rag-engine/tests/test_embedding_contract.py` (classe
  `TestPgvectorDimensionConnectTimeout`)
- `services/rag-engine/tests/test_retrieval_v2_endpoint.py` (classe
  `TestReadinessConnectTimeout`)

## Tests exécutés — résultats exacts

Commandes exécutées telles quelles, dans `services/rag-engine`, avec le
`.venv` déjà provisionné via `uv` (cf. limite d'environnement ci-dessous) :

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/mypy src
Success: no issues found in 46 source files

$ PYTHONPATH=src .venv/bin/python -m pytest tests/ -m "not integration" -o addopts=""
1224 passed, 1 skipped, 19 deselected, 3 warnings in 35.37s

$ PYTHONPATH=src .venv/bin/python -m pytest tests/test_ssrf_guard.py -o addopts="" -v
16 passed in 0.59s (dans le cadre d'une exécution groupée avec d'autres
tests LOT43 ; 16/16 individuellement confirmés)

$ PYTHONPATH=src .venv/bin/python -m pytest tests/integration/ -o addopts="" -q
11 passed, 9 skipped in 14.32s
# dont : 3 (migrations autorun, conteneur jetable isolé) + 1 (contexte de
# build .dockerignore, §43.7) réellement exécutés avec Docker ; le reste
# des tests d'intégration (non liés à LOT43) est skip pour absence d'autres
# prérequis (ex. DATABASE_URL_TEST), sans rapport avec ce lot.
```

Aucune régression : la suite complète était déjà verte avant ce lot. Le
nombre de tests non-intégration est passé de 1197 (chiffre de la première
rédaction de ce rapport, avant les correctifs §43.1/43.4/43.5) à **1220**
après l'ajout de la fermeture ChromaDB, du scope serveur, des quotas et des
limites applicatives, puis à **1224** après l'ajout des tests de timeout de
readiness (§43.6) — chaque étape ajoutant strictement des tests, sans
qu'aucun test préexistant ne soit cassé ou modifié pour le faire passer. Le
nouveau test d'intégration du §43.7 porte le total de tests `integration`
liés à LOT43 réellement exécutés à 4 (3 migrations + 1 contexte de build).

## Limite d'environnement constatée (non liée à LOT43)

`bash scripts/ci-local.sh` fait `rm -rf .venv` puis `python3.11 -m venv
.venv` pour `packages/contracts`, `services/rag-pedago` et
`services/rag-engine` avant chaque run, afin de garantir une installation
reproductible. Dans ce sandbox, cette recréation échoue systématiquement à
l'étape `ensurepip` (`ModuleNotFoundError: No module named 'encodings'`) —
un défaut du bootstrap `venv` stdlib avec le build Python 3.11.14 fourni par
`uv` dans cet environnement, reproductible à l'identique sur les **trois**
services (y compris ceux non modifiés par ce lot), donc antérieur et
indépendant de LOT43. Contournement utilisé pour ce lot : recréation du venv
via `uv venv` + `uv pip install` (fonctionne correctement, produit le même
jeu de paquets), puis exécution directe de `ruff`/`mypy`/`pytest` — tous
verts (résultats ci-dessus). Le reste de `ci-local.sh` (gouvernance, garde-
fous CI, cockpit, tests de topologie) s'est exécuté normalement une fois ce
point dépassé manuellement. Recommandation : sur un runner CI dédié
(GitHub Actions), ce problème ne devrait pas se reproduire si le Python
utilisé fournit un `ensurepip` fonctionnel nativement ; sinon, remplacer
`python3.11 -m venv` par `uv venv` dans `scripts/ci-local.sh` réglerait le
problème durablement.

## Ce qui reste bloquant / hors périmètre

- **`retrieval_contract_adapter.py` — filtres `notions`/`desired_doc_types`/
  `difficulty_max` non câblés.** Un audit ciblé (post-rédaction initiale de
  ce rapport) a confirmé que `SearchV2Request` (le contrat HTTP réel de
  `POST /search/v2`, `retrieval_v2_endpoint.py`) n'expose que `q`,
  `collection`, `k` — ces trois filtres n'existent même pas côté requête.
  Un module séparé, `retrieval_contract_adapter.py`, sait traduire
  `RetrievalRequest.need.notions`/`desired_doc_types`/`difficulty_max` en un
  dict de filtres, mais **n'est appelé par aucune route de production**
  (seulement par son propre test et par un test qui vérifie juste sa
  présence sur disque) — ce dict n'a nulle part où atterrir dans
  `retrieval_pg_v2.py`. Ce n'est pas une faille de sécurité (rien n'est
  accepté silencieusement puis ignoré côté HTTP : les champs ne sont pas
  acceptés du tout), mais c'est une fonctionnalité déclarée dans le contrat
  `nexus_contracts` et jamais raccordée. **Décision volontairement non
  prise dans ce lot** : câbler cet adaptateur à `/search/v2` est un
  changement de comportement de recherche (filtrage additionnel côté
  requête), pas un correctif de sécurité/fiabilité P1 — cela relève de
  LOT44+ (contrats canoniques et retrieval enrichi). Le module n'a pas été
  supprimé : il est fonctionnellement correct, seulement non branché ; un
  commentaire dans le fichier documente désormais explicitement ce statut
  et pointe vers ce paragraphe.
- Le reste de l'usine d'ingestion agentique (contrats canoniques
  `SearchPlan`/`ResourceCandidate`/`ArtifactRecord`/`RoutingDecision`/
  `QualityReport`, MCP, orchestrateur à jobs persistants avec
  `SKIP LOCKED`/leases/dead-letter, agents spécialisés
  SourceScout/Fetcher/RightsAgent/ContentClassifier/QualityAgent/
  CoverageAgent génériques, scheduler à budgets) reste à construire — c'est
  l'objet des lots suivants (LOT44+), hors périmètre de ce lot par accord
  explicite avec l'utilisateur. Le catalogue de collections
  (`configs/rag_collections.yml`, 59 entrées, LOT28) et le mécanisme de
  review (`/review/v2/queue`, `/review/v2/decide`) existent déjà et sont
  fonctionnels, mais ne couvrent pas le modèle `CollectionProfile` complet
  attendu par LOT44 (pas de seuils qualité ni de politique de publication
  par collection).
- Incohérence de dimension d'embeddings entre le moteur v2 (pgvector,
  1024d, verrouillé fail-closed par `embedding_contract.py`) et le moteur
  ChromaDB legacy déprécié (`infra/docker-compose.yml`, défaut
  `EMBED_MODEL=nomic-embed-text`, 768d, sans validation de contrat). Sans
  effet sur le chemin v2 (fail-closed, testé) ; risque résiduel documenté
  pour le moteur legacy uniquement, dont la décommission est déjà actée
  (ADR-0013). Un script `migrate_chroma_to_pgvector.py` orphelin (non
  importé, schéma de table désynchronisé du schéma v2 réel) casserait s'il
  était exécuté tel quel — signalé, non touché (hors périmètre de ce lot).
- Aucun verrou de gouvernance n'a été modifié ; `curated_ingestion_allowed`
  et `real_documents_allowed` restent à `false`. Toute décision de les lever
  reste hors du périmètre de ce lot et nécessite un ADR dédié, conformément
  à `AGENTS.md`.
- **Mise à jour** : la validation Compose fraîche isolée a finalement été
  exécutée (§43.7), dans un projet Compose dédié (`lot43fresh`) sans toucher
  la stack `infra` déjà active — migrations réelles sur volume vierge,
  ingestion → review → retrieval vérifiés avec une identité signée réelle.
  Elle a permis de trouver et corriger un bug bloquant réel (`.dockerignore`
  masquait l'artefact d'identité pilote, §43.7). Ce qui reste non démontré :
  un scoring de pertinence réussi de bout en bout (0 résultat retourné par
  `/search/v2` dans ce test — seuil de reranking +1.90 non atteint par une
  phrase de test générique, comportement de précision attendu et non un
  échec de scope/autorisation, cf. §43.7 point 5) ; et la validation
  `down -v && up` de la stack `infra` de production **en place** (non
  souhaitable/nécessaire — le test isolé §43.7 couvre la même logique de
  bootstrap sans le risque d'interrompre un déploiement actif).

## Commandes de démarrage local

```bash
cd services/rag-engine
make install   # ou : rm -rf .venv && uv venv .venv --python 3.11 \
                #      && uv pip install -p .venv/bin/python -r requirements.lock \
                #      && uv pip install -p .venv/bin/python -e ../../packages/contracts --no-deps \
                #      && uv pip install -p .venv/bin/python -r requirements-dev.txt
make lint
make typecheck
make test
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_migrations_autorun.py  # nécessite Docker
```

## Rapport de clôture du lot LOT43

*Ce rapport clôt LOT43. Rien n'a été commité, poussé, ni ouvert en pull
request — ces actions restent soumises à autorisation explicite
ultérieure. Aucun fichier existant n'a été supprimé. Aucun verrou de
gouvernance (`services/rag-pedago/configs/pedago_interface_contract.yml`)
n'a été modifié.*

### 1. Résumé exécutif

LOT43 corrige quatre bloqueurs P1 réels et actuels du moteur RAG
(`rag-engine`), et en découvre puis corrige un cinquième pendant sa propre
phase de validation. Tous sont testés — la majorité par des tests
d'intégration réels (vrai Postgres, vrai Docker, vraie cryptographie
HS256), pas seulement par des mocks. Aucune régression sur la suite
existante. Le sous-lot de hardening est terminé et validé localement. Le
programme global (usine d'ingestion agentique — contrats canoniques, jobs
persistants, orchestrateur, agents spécialisés, MCP, Cockpit) n'est pas
entamé par ce lot et reste entièrement à construire : le verdict global de
clôture est donc **`NOT_READY_FOR_PRODUCTION`**.

### 2. Corrections livrées

| # | Correction | Détail | État |
|---|---|---|---|
| 1 | Timeouts PostgreSQL sur `/health` et `/collections/readiness` | `connect_timeout` borné (`PG_HEALTHCHECK_CONNECT_TIMEOUT_S`, 5s) sur les deux connexions directes hors pool ; sans lui, un Postgres injoignable pouvait bloquer ces routes indéfiniment | §43.6 — TDD, testé |
| 2 | Fermeture des routes ChromaDB legacy | `/collections` et `/stats/{name}` (lecture directe ChromaDB) fermées en 410 au niveau Nginx, en plus de `/ingest*` legacy déjà fermées ; aucune voie de lecture parallèle contournant le runtime v2 | §43.1 — testé |
| 3 | Limites upload, URL, PDF, quotas | `MAX_FILES_PER_UPLOAD`, `MAX_UPLOAD_FILE_BYTES` (lecture bornée, jamais de `read()` illimité), `MAX_URLS_PER_REQUEST`, `MAX_URLS_PER_DOMAIN_PER_REQUEST`, `MAX_PDF_PAGES`, `MAX_EXTRACTED_TEXT_CHARS`, `MAX_CHUNKS_PER_COLLECTION_PER_DAY` (quota glissant 24h par collection) | §43.5 — testé |
| 4 | Scope serveur obligatoire et fail-closed | `tenant`/`candidat`/`visibility`/`school_year`/`programme_version` désormais toujours renseignés à l'ingestion v2 (auparavant `NULL`, rendant tout chunk ingéré invisible du retrieval scopé même après review) ; échec explicite si la configuration serveur est absente ou invalide — jamais de valeur devinée | §43.4 — testé |
| 5 | Conservation de `retrieval_contract_adapter.py` pour LOT44 | Module non supprimé ; docstring ajoutée documentant explicitement qu'il n'est câblé à aucune route de production (`notions`/`desired_doc_types`/`difficulty_max` non exposés par `/search/v2`) ; décision de le brancher ou non renvoyée à LOT44 | Documenté, non modifié fonctionnellement |
| 6 | Bug `.dockerignore` corrigé + test Docker réel | Dénégation générique `**/artifacts` masquait `nexus_contracts/artifacts/pilot-retrieval-scope-v1.json`, requis par toute route utilisant une identité signée (`/review/v2/*`, `/search/v2`, `/collections/v2`, `/collections/readiness`) — 500 garanti dans toute image construite depuis ce dépôt. Bug antérieur à LOT43 (13/07/2026), trouvé pendant la validation Compose de ce lot | §43.7 — TDD avec Docker réel, testé |
| 7 | Validation Compose fraîche et isolée | Projet Compose dédié (`lot43fresh`), réseau/volumes/ports isolés, sans toucher la stack `infra` active ; migrations réelles sur volume vierge via l'orchestration Compose (pas un conteneur ad hoc) | §43.7 — exécuté et nettoyé |
| 8 | Parcours complet ingestion → review → retrieval | Ingestion HTTP réelle (modèle d'embedding réel) → `needs_review` en base → apparition dans `/review/v2/queue` → `POST /review/v2/decide` → `reviewed` en base → éligibilité SQL confirmée pour le retrieval (prédicat de scope identique entre review et retrieval) | §43.7 — exécuté avec identité HS256 réellement signée |

Le SSRF (résolution DNS complète, revalidation à chaque redirection,
16 tests déterministes) et les migrations automatiques (`migrator`,
3 tests d'intégration réels) — les deux bloqueurs P1 du périmètre initial —
restaient également livrés et confirmés à cette clôture (§43.2, §43.3).

### 3. Résultats exacts des commandes exécutées

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/mypy src
Success: no issues found in 46 source files

$ PYTHONPATH=src .venv/bin/python -m pytest tests/ -m "not integration" -o addopts=""
1224 passed, 1 skipped, 19 deselected, 3 warnings in 35.37s

$ PYTHONPATH=src .venv/bin/python -m pytest tests/test_ssrf_guard.py -o addopts="" -v
16 passed in 0.59s

$ PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_migrations_autorun.py tests/integration/test_docker_build_context_includes_pilot_artifact.py -o addopts="" -v
4 passed in 12.37s
```

Validation Compose fraîche (§43.7, commandes non-pytest, exécutées et
nettoyées manuellement dans cette session) :

```
$ docker compose -p lot43fresh --env-file .env -f docker-compose.v2.yml -f docker-compose.override.yml config
# résolu sans erreur : réseau lot43fresh_rag_net (172.16.99.0/24), volumes
# et conteneurs préfixés/renommés lot43fresh_*

$ docker compose -p lot43fresh ... up -d pgvector && (attente healthy) && up migrator
MIGRATIONS_APPLIED=1
MIGRATIONS_ADOPTED=2
SCHEMA_VERIFICATION=OK
BOOTSTRAP_COMPLETE
SCHEMA_HEAD=3
# exit code 0

$ docker compose -p lot43fresh ... build ingestor worker   # cache-friendly, ~1min
$ docker compose -p lot43fresh ... up -d ingestor worker    # healthy

$ curl -X POST .../ingest/v2/upload-files?collection=rag_nexus_nsi_terminale_specialite&...
{"results":[{"doc_id":"4744ea...","chunks_written":1,"review_status":"needs_review"}]}

$ curl .../review/v2/queue?collection=rag_nexus_nsi_terminale_specialite   # identité signée reviewer
{"total_pending_docs":1,"returned":1,...}

$ curl -X POST .../review/v2/decide -d '{"decision":"reviewed",...}'       # identité signée reviewer
{"decision":"reviewed","chunks_affected":1,...}

$ curl -X POST .../search/v2 -d '{"q":"...","collection":"...","k":5}'     # identité signée student
{"returned":0,"hits":[]}   # 200 OK ; 0 résultat = seuil de reranking +1.90
                            # non atteint, pas un échec d'autorisation
                            # (confirmé par requête SQL directe du prédicat
                            # de scope, cf. §43.7 point 4)

$ docker compose -p lot43fresh ... down -v && docker rmi lot43fresh-ingestor lot43fresh-worker
# containers, volumes, réseau, images : tous supprimés ; stack infra
# (rag_pgvector, rag_worker, rag_ui, rag_redis) vérifiée intacte
```

### 4. Décompte précis des tests

| Catégorie | Commande | Résultat |
|---|---|---|
| Unitaires / non-intégration (ensemble du service) | `pytest tests/ -m "not integration"` | **1224 passed**, 1 skipped, 19 deselected |
| … dont SSRF (`test_ssrf_guard.py`) | `pytest tests/test_ssrf_guard.py -v` | **16 passed** (sous-ensemble des 1224 ci-dessus, isolés ici pour preuve dédiée) |
| Intégration Compose/Docker réels liés à LOT43 | `pytest tests/integration/test_migrations_autorun.py tests/integration/test_docker_build_context_includes_pilot_artifact.py` | **4 passed** (3 migrations sur Postgres réel jetable + 1 contexte de build `.dockerignore`) |
| Intégration hors périmètre LOT43 (préexistants) | `pytest tests/integration/` (ensemble) | 11 passed, 9 skipped (skip : prérequis externes non liés à ce lot, ex. `DATABASE_URL_TEST`) |
| Validation Compose fraîche bout en bout (§43.7) | manuel, hors pytest | ingestion → review → retrieval exécutés avec succès jusqu'à la porte du seuil de reranking (non un test pytest — parcours HTTP réel documenté ci-dessus) |

Baseline avant LOT43 (rapport initial) : 1197 passed. Progression : 1197 →
1220 (fermeture ChromaDB, scope serveur, quotas/limites) → **1224**
(timeouts readiness). Aucun test préexistant cassé ni modifié pour
« repasser au vert » — uniquement des ajouts.

### 5. Fichiers modifiés

- `.dockerignore` (racine du repo — correctif §43.7)
- `services/rag-engine/infra/nginx/rag-v2.conf`
- `services/rag-engine/infra/nginx/rag-api.conf.template`
- `services/rag-engine/infra/docker-compose.v2.yml`
- `services/rag-engine/src/ingestor/ingest_v2.py`
- `services/rag-engine/src/ingestor/ingest_v2_endpoint.py`
- `services/rag-engine/src/ingestor/tasks.py`
- `services/rag-engine/src/ingestor/embedding_contract.py`
- `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`
- `services/rag-engine/src/ingestor/retrieval_contract_adapter.py` (docstring uniquement)
- `services/rag-engine/tests/test_ingest_v2.py`
- `services/rag-engine/tests/test_embedding_contract.py`
- `services/rag-engine/tests/test_retrieval_v2_endpoint.py`

### Fichiers créés

- `services/rag-engine/src/ingestor/ssrf_guard.py`
- `services/rag-engine/infra/scripts/bootstrap_pgvector_schema.sh`
- `services/rag-engine/tests/test_lot43_ingest_legacy_closure.py`
- `services/rag-engine/tests/test_lot43_chromadb_legacy_closure.py`
- `services/rag-engine/tests/test_lot43_ingest_limits.py`
- `services/rag-engine/tests/test_ssrf_guard.py`
- `services/rag-engine/tests/integration/test_migrations_autorun.py`
- `services/rag-engine/tests/integration/test_docker_build_context_includes_pilot_artifact.py`
- `docs/reports/lot_43_rag_engine_p1_hardening.md` (ce rapport)

### Fichiers explicitement non modifiés

- `services/rag-pedago/**` — aucun changement (orchestrateur Level/Subject,
  `EduscolAgent`, `SourceValidator`, `reviewers.py`, gouvernance).
- `services/rag-pedago/configs/pedago_interface_contract.yml` — verrous de
  gouvernance intacts (`curated_ingestion_allowed`, `real_documents_allowed`
  restent `false`).
- `services/cockpit/**` — aucun changement.
- `packages/contracts/src/nexus_contracts/**` (code Python) — aucun
  changement fonctionnel ; seul `.dockerignore` à la racine du repo a été
  modifié pour cesser de masquer une ressource déjà présente dans ce
  package.
- `services/rag-engine/src/ingestor/api.py` — routes legacy ChromaDB
  (`/collections`, `/stats/{name}`, `/ingest*`) laissées intactes dans le
  code applicatif ; seule leur exposition Nginx a été fermée (défense en
  profondeur : elles restent aussi protégées par authentification
  applicative existante).
- `services/rag-engine/infra/docker-compose.yml` (le compose **legacy**,
  distinct de `docker-compose.v2.yml`) — non modifié ; conserve
  `EMBED_MODEL=nomic-embed-text` (768d) par défaut, incohérent avec le
  contrat v2 (1024d). Sans effet sur le chemin v2 (fail-closed), mais
  signalé comme risque résiduel (§6).
- `scripts/migrate_chroma_to_pgvector.py` — script orphelin (non importé),
  schéma de table désynchronisé du schéma v2 réel ; non touché, signalé
  uniquement.
- `infra/scripts/apply_pgvector_migrations.sh` (l'outil opérateur de
  production) — non modifié ; reste l'outil de référence pour une upgrade
  avec données réelles et garantie de rollback, distinct du script de
  bootstrap ajouté pour les volumes vierges.

### 6. Risques résiduels et hors périmètre explicite de LOT43

- **Scoring de pertinence de bout en bout non démontré** : le parcours
  §43.7 confirme l'autorisation et le scope jusqu'à la porte du seuil de
  reranking (+1.90), mais aucune requête n'a été conçue pour dépasser ce
  seuil avec un corpus réaliste. C'est un test de qualité de recherche, pas
  un bloqueur de sécurité/fiabilité P1.
- **Incohérence de dimension d'embeddings sur le moteur ChromaDB legacy**
  (`docker-compose.yml`, 768d par défaut vs contrat v2 1024d) — sans effet
  sur le chemin v2 (fail-closed), risque cantonné au moteur déprécié
  (décommission déjà actée, ADR-0013).
- **Script `migrate_chroma_to_pgvector.py` orphelin et désynchronisé** —
  casserait s'il était exécuté tel quel ; non utilisé nulle part dans le
  code actif.
- **Modélisation du scope serveur encore minimale** (§43.4) : une seule
  valeur par dimension pour tout le déploiement, alors que `candidat` varie
  réellement par collection selon la convention `{population}_{niveau}`.
  Modéliser cela proprement nécessite d'étendre le catalogue de collections
  avec un scope gouverné par collection et un ADR dédié — non fait ici.
- **`retrieval_contract_adapter.py` non câblé** — fonctionnalité de
  filtrage (`notions`, `desired_doc_types`, `difficulty_max`) déclarée dans
  le contrat mais indisponible via `/search/v2`. Pas un risque de sécurité,
  mais un écart fonctionnel documenté pour LOT44.
- **Aucune politique de moindre privilège PostgreSQL documentée pour la
  production** : aucun `GRANT` n'existe dans les migrations versionnées
  (ni excès ni politique explicite) ; un script de test dédié
  (`test_hybrid_integration.sh`) illustre une politique restrictive mais
  elle n'est pas appliquée en production.
- **Validation Compose `down -v && up` de la stack `infra` en place** non
  effectuée (délibérément — n'aurait fait que dupliquer la logique déjà
  validée de façon isolée en §43.7, avec le risque en plus d'interrompre un
  déploiement actif).
- **L'ensemble du programme LOT44+ reste à construire** : contrats
  canoniques (`CollectionProfile`, `SearchPlan`, `ResourceCandidate`,
  `ArtifactRecord`, `RoutingDecision`, `QualityReport`, `IngestionRun`,
  `CoverageSnapshot`), file de jobs persistante (`SKIP LOCKED`, leases,
  retries, dead-letter), orchestrateur et scheduler à budgets, agents
  spécialisés génériques (SourceScout, Fetcher, RightsAgent,
  ContentClassifier, QualityAgent, CoverageAgent, Supervisor), serveurs MCP
  (Research, Collection Catalog, Artifact Store, Policy, RAG Ingest,
  Observability), et endpoints Cockpit de suivi. Rien de tout cela n'existe
  après LOT43, en dehors de ce qui préexistait déjà côté `rag-pedago`
  (orchestrateur Level/Subject, `EduscolAgent`, `SourceValidator`,
  mécanisme de review) — confirmé par inspection directe, pas supposé.

### 7. Matrice des critères d'acceptation (périmètre LOT43 uniquement)

| Critère | État | Preuve |
|---|---|---|
| Routes legacy fermées (`/ingest*`, `/collections`, `/stats`) | IMPLEMENTED / TESTED | §43.1, tests nginx statiques |
| SSRF complet (DNS, redirections, tailles, timeouts) | IMPLEMENTED / TESTED | §43.2, 16 tests déterministes |
| Migrations automatiques sur volume vierge | IMPLEMENTED / TESTED | §43.3 + §43.7, tests réels + Compose réel |
| Scope complet fail-closed à l'ingestion | IMPLEMENTED / TESTED | §43.4, tests unitaires + E2E réel (§43.7) |
| Quotas et limites applicatives | IMPLEMENTED / TESTED | §43.5, 6 tests dédiés |
| Timeouts health/readiness | IMPLEMENTED / TESTED | §43.6, TDD, tests déterministes réels |
| Bug `.dockerignore` (identité signée en conteneur) | IMPLEMENTED / TESTED | §43.7, TDD avec Docker réel |
| Parcours ingestion → review → retrieval | TESTED (jusqu'au seuil de reranking) | §43.7, HTTP réel + identité signée réelle |
| Contrats canoniques, MCP, orchestrateur, agents, Cockpit | NOT_IMPLEMENTED | Hors périmètre explicite de LOT43 (LOT44+) |
| Auto-publication de confiance | NOT_IMPLEMENTED / désactivée par défaut | Aucun changement, verrous intacts |

### 8. Verdict final

**Sous-lot `rag-engine` P1 hardening : TERMINÉ**, dans son périmètre
(fermeture des routes legacy, SSRF, migrations automatiques, scope serveur,
quotas/limites, timeouts de readiness, et un bug de packaging Docker
bloquant trouvé et corrigé pendant sa propre validation), testé sans
régression y compris par des preuves réelles (Postgres réel, Docker réel,
cryptographie HS256 réellement signée).

**Verdict global de clôture : `NOT_READY_FOR_PRODUCTION`.**

Ce verdict global ne remet pas en cause la qualité ou la complétude du
travail de hardening livré : il reflète simplement que l'ensemble du
programme demandé — l'usine d'ingestion agentique complète avec contrats
canoniques, jobs persistants, orchestrateur, agents spécialisés, serveurs
MCP et endpoints Cockpit — n'est pas construit par ce lot et reste
entièrement à réaliser dans les lots suivants (LOT44+), conformément à
l'accord de périmètre explicite avec l'utilisateur documenté depuis la
première version de ce rapport. Aucun critère de mise en production
(migrations fraîches, ingestion réelle, review, retrieval, routes legacy
fermées, SSRF, tests end-to-end, scope complet, absence de fuite
inter-tenant) ne peut à lui seul faire basculer un chantier aussi large
que `PARTIAL` ou `NOT_READY_FOR_PRODUCTION` tant que LOT44+ n'a pas
commencé.
