# LOT41U — Durcissement fail-closed du runtime v2

## Verdict

**LOT41U_SCOPE_SCHEMA_ATTESTATION_GREEN_AWAITING_EXACT_HEAD_CI**

LOT41U ferme les quatre constats P1 du runtime relevés par l'audit indépendant
de `main@ea18ba52da5778f628c4943705dd81dfa43fbc15`. Le stack v2 n'embarque
plus de writer ni d'API legacy, une base PostgreSQL neuve atteint directement
le head `003_profile_filtering`, et le reverse proxy fonctionne par allowlist.
La surface d'ingestion URL ou fichier non autoritaire est supprimée plutôt que
rendue artificiellement conforme.

**GO_LIVE: NO_GO**

Ce lot sécurise un runtime de lecture et de revue ; il n'autorise pas
l'ingestion. LOT41A doit encore fournir une autorité humaine GitHub vérifiable,
LOT42 une remise signée `quality → gate → review`, puis la revue golden et les
preuves opérationnelles externes doivent être obtenues. Aucun verrou
`*_allowed` n'a été activé.

## Périmètre

| Élément | Valeur |
| --- | --- |
| Date | 2026-08-02 |
| Baseline `main` | `ea18ba52da5778f628c4943705dd81dfa43fbc15` |
| Branche | `lot-41u-ingestion-runtime-hardening` |
| Head applicatif audité avant ce commit documentaire | `9ac295d62d8f7d5a71563c48442b1fbaec3c9d6b` |
| Plan de données | runtime FastAPI v2, PostgreSQL/pgvector, Compose, Nginx |
| Contrats partagés | aucune évolution |
| Verrous de gouvernance | aucun changement, 18/18 conformes |
| Décision d'architecture | ADR-0024, runtime v2 limité à lecture et revue |

## Traitement des constats indépendants

| Constat | Décision et correction | État |
| --- | --- | --- |
| `RAG-INGEST-001` — écritures sans scope complet | Le writer v2 non autoritaire est retiré de l'application, de l'image, de Compose et du proxy. Aucune donnée client libre n'est promue en scope signé. Un nouveau writer ne pourra revenir qu'avec LOT41A/LOT42. | fermé par suppression de la surface |
| `RAG-MIGRATION-001` — base Compose neuve sans `003` | PostgreSQL monte `init.sql` puis `003_profile_filtering.sql`; son healthcheck et `/health` vérifient les SHA du registre, les 31 colonnes, les dix index, l'expression `text_tsv` et les cinq contraintes validées des migrations 001–003. `v2-up` attend la santé. | corrigé |
| `RAG-LEGACY-001` — routes Chroma/legacy exposées | `api_v2.py` est l'unique application. L'image copie une liste explicite de modules, Compose n'exécute plus `api:app`, et Nginx refuse les routes legacy en `410` avant tout proxy. | corrigé |
| `RAG-SSRF-001` — redirections URL non revalidées | Le runtime v2 n'embarque ni endpoint URL, ni client HTTP, ni module d'ingestion réseau. Il n'existe donc plus de redirection à suivre dans le service exposé. | fermé par suppression de la surface |
| `RAG-UPLOAD-001` — upload lu sans borne | Aucun endpoint d'upload, parseur ou montage de dépôt n'est présent dans le runtime v2. | fermé par suppression de la surface |
| `RAG-DOC-001` — documentation contradictoire | README, AGENTS du moteur, runbook et exemple d'environnement décrivent désormais PostgreSQL/pgvector, le BFF et l'absence de writer. | corrigé |

Le choix de suppression est intentionnel. Ajouter simplement `tenant`,
`candidat`, `visibility`, `school_year` et `programme_version` au payload
n'aurait pas authentifié ces valeurs et aurait conservé l'écriture directe
interdite dans pgvector. La remise future devra dériver son scope d'une preuve
autoritaire et lier le contenu aux attestations indépendantes.

## Architecture livrée

Le runtime v2 expose exactement :

- `/health` et `/metrics` ;
- `/search/v2`, `/chat`, `/collections/v2`, `/catalogue/v2` et
  `/collections/readiness` ;
- `/review/v2/queue` et `/review/v2/decide`.

Les sept routes métier conservent les contrôles BFF et l'enveloppe d'identité
signée existants. `/metrics` est limité au loopback dans Nginx. Les chemins
`/ingest*`, `/search`, `/collections`, `/rag/query`, `/admin*`, `/stats*`,
`/eval*` et `/kb*` ne sont jamais transmis au moteur. Tout autre chemin reçoit
`404`.

Le Compose v2 contient seulement PostgreSQL/pgvector, l'API lecture/revue et
Prometheus. Il ne contient plus ChromaDB, Redis, Ollama, worker, UI, répertoire
d'upload, token d'ingestion ou DSN propriétaire. L'image de production utilise
un verrou runtime séparé, CPU-only, et ne copie ni `api.py`, ni
`ingest_v2.py`, ni `ingest_v2_endpoint.py`, ni `tasks.py`, ni `database.py`.
Les artefacts embedding et reranker sont montés en lecture seule ; le reranker
canonique est chargé avec `local_files_only` et les modes Hugging Face hors
ligne. Leur inventaire `SHA256SUMS` est lié à une empreinte attendue fournie par
la configuration de déploiement hors du montage ; remplacer ensemble les
poids, le manifeste et les checksums ne suffit donc plus à passer la readiness.
Les anciennes variables sans effet `RERANKER_MODEL` et
`RERANKER_TOP_N` ont été retirées du Compose et de son exemple d'environnement.

## Migrations et santé

Une base neuve est initialisée dans cet ordre :

1. `init.sql` crée le schéma v2 initial ;
2. `003_profile_filtering.sql` ajoute le profil signé, les contraintes LOT41 et
   l'index de lecture ;
3. un script d'initialisation calcule les SHA-256 des migrations canoniques et
   enregistre atomiquement `001`, `002` et `003` dans le registre ;
4. `03_provision_runtime_roles.sh` crée deux identités distinctes : retrieval
   avec `SELECT` sur les chunks et le registre, et review avec `SELECT` sur les
   seuls chunks plus `UPDATE(review_status)` ; les mots de passe ne sont jamais
   passés sur la ligne de commande `psql` ;
5. le healthcheck PostgreSQL recalcule les trois SHA, exige les 31 colonnes
   uniques,
   les dix définitions d'index, l'expression générée `text_tsv`, cinq
   définitions de contraintes validées, le prédicat exact de l'index de profil,
   l'absence de RLS, de policy et de trigger applicatif, puis les trois entrées
   exactes du registre ;
6. l'API relit les mêmes preuves via un rôle `SELECT`, avec `connect_timeout`,
   `statement_timeout` et transaction read-only, vérifie les privilèges
   effectifs des rôles retrieval et review, refuse toute cible de `SET ROLE`,
   puis le modèle canonique et la dimension pgvector `1024` avant de rendre
   `healthy`.

La procédure des volumes existants reste distincte : sauvegarde, scripts de
migration versionnés, vérification du head puis rollback testé. Aucun DSN owner
n'est injecté dans le runtime applicatif.

## Cycles TDD et preuves ciblées

Les contrôles ont été écrits ou durcis avant chaque implémentation : décision
ADR, état du schéma, surface FastAPI, contenu d'image, topologie Compose,
allowlist Nginx et documentation. Les états RED ont confirmé que la baseline
exposait le monolithe legacy, omettait `003` au bootstrap et transmettait
`/ingest`.

Les preuves GREEN fraîches comprennent :

- `schema_head_003_ready` : colonnes, index, contraintes, erreurs psycopg et
  absence de SQL mutatif testés ;
- surface FastAPI : neuf chemins exacts, santé fail-closed, métriques et import
  aplati testés ;
- image `nexus-rag-engine-v2:lot41u` construite, avec `api_v2.py` présent et les
  modules writer/legacy absents du conteneur ;
- Compose PostgreSQL sur volume temporaire neuf : santé complète positive,
  refus après suppression de l'index lexical, puis récupération positive après
  restauration ;
- registre frais : trois entrées dont les SHA correspondent octet pour octet à
  `001_rag_chunks_v2_schema.sql`, `002_hybrid_retrieval.sql` et
  `003_profile_filtering.sql` ;
- compatibilité du runner sur ce volume : `MIGRATIONS_APPLIED=0`,
  `MIGRATIONS_ADOPTED=0`, `SCHEMA_VERIFICATION=OK` et `UPGRADE_COMPLETE` ;
- deux configurations Nginx rendues et validées par `nginx -t` ;
- tests négatifs `404`/`410` pour les routes non autorisées ;
- Ruff vert, `mypy` vert sur 47 fichiers du moteur et suites runtime ciblées
  vertes ;
- intégration PostgreSQL réelle verte, dont migrations, adoption, rollback,
  atomicité, moindre privilège, HNSW, GIN, identité signée, scope, review et
  endpoints HTTP : `LOT40_HYBRID_INTEGRATION=PASS`.

La cible `make test-integration` a aussi été corrigée pour définir
`PYTHONPATH=src`. Sans cela, son exécution canonique échouait à la collecte avec
`ModuleNotFoundError: ingestor`, alors que le script hybride appelé ensuite
pouvait être lancé séparément.

## CI locale source

La CI racine exhaustive a été exécutée sur le head source exact
`c8364acef01bcc81c33755571a284016038a3531`, avec Python 3.12.3 et Node
22.23.1. Une première exécution a identifié l'accès non affiné à `BaseRoute.path`
dans `api_v2.py` ; la correction utilise un accès défensif, puis Ruff, `mypy`
et 14 tests ciblés sont redevenus verts.

La relance complète a produit **13 réussites, 0 échec** :

- `packages/contracts` : import réussi ;
- `services/rag-pedago` : Ruff, `mypy` sur 76 fichiers et 1 757 tests réussis ;
- `services/rag-engine` : Ruff, `mypy` sur 47 fichiers, suite non-intégration
  complète et smoke PostgreSQL réel réussis ;
- `services/cockpit` : 20 fichiers de tests, 172 tests, deux builds Next.js,
  contrôles de contrats et deux audits npm sans vulnérabilité ;
- hygiène, topologie CI, protection versionnée de `main`, taxonomie, preuves
  source, verrous de gouvernance et tests fail-safe : tous réussis ;
- tests fail-safe : 50 réussites, 0 échec ;
- verrous : baseline 18, configuration 18, conformité totale.

Le rapport crée nécessairement un nouveau head. Une seconde CI exhaustive sera
donc exécutée après son commit, sans modification ultérieure ; son résultat et
les checks GitHub seront des preuves du head final, pas du parent nommé ici.

La revue prépublication a ajouté un dernier cycle rouge/vert : la sonde API ne
filtrait pas encore `pg_constraint.convalidated` et le bootstrap frais ne
créait pas le registre reconnu par le runner. Le test de validation a d'abord
échoué, puis 58 tests schema/Compose/runtime, Ruff et `mypy` sur 47 fichiers ont
réussi après correction. Deux volumes PostgreSQL éphémères distincts ont prouvé
l'enregistrement exact du head et sa compatibilité immédiate avec le runner.

La première revue Codex de la PR #88 sur `fe92cc5` a ensuite relevé que
`/catalogue/v2` conservait l'ancien contrôle par tokens humains alors que le
Compose fermé ne les fournit plus. Le constat P1 a été reproduit : un ancien
token admin recevait `200` tandis que le BFF recevait `503`. La route exige
désormais d'abord le credential BFF, puis l'identité signée et un rôle
`admin`, `reviewer`, `teacher` ou `ingest_agent`; `student` reçoit `403`. Les
78 tests ciblés catalogue/retrieval/runtime, Ruff et `mypy` sont verts après ce
cycle.

La revue Cubic suivante a produit dix remarques sur le head précédent, puis une
onzième sur les tests catalogue. Leur qualification indépendante donne :

- **valides et corrigées** : registre de migrations sans contrôle des SHA,
  objets PostgreSQL homonymes acceptés, upstream `ingestor` inaccessible depuis
  Nginx hôte, absence de timeout des sondes psycopg, configuration reranker
  morte et téléchargement possible, chemins absolus du plan, test de routes
  dépendant de `RAG_ENV`, test Nginx aveugle aux blocs non exacts et assertions
  de rôles catalogue tautologiques ;
- **doublon corrigé** : indisponibilité de `/catalogue/v2`, déjà fermée par le
  cycle Codex `BFF → identité signée → rôle` et désormais prouvée par un test
  HTTP paramétré plutôt que par introspection d'une constante privée ;
- **durcissement supplémentaire découvert pendant la vérification** : les
  commandes documentées `envsubst` sans allowlist auraient supprimé
  `$binary_remote_addr` et `$request_uri`. Le runbook et les README passent une
  liste explicite de variables de template.

Les cycles rouges ont reproduit les absences d'attributs de readiness, le
vhost Docker injoignable, le chemin local non portable, l'absence du contrat
reranker et du healthcheck exact. Après correction, 197 tests ciblés ont réussi,
Ruff est vert et `mypy` valide 48 fichiers. Sur PostgreSQL 16 éphémère, le
healthcheck canonique réussit puis refuse la même base après remplacement de la
contrainte tenant par `CHECK (true)` ; la sonde applicative via un rôle
`SELECT` retourne `SCHEMA_HEAD_003_READY=True` et `PGVECTOR_DIMENSION=1024`.
Les deux vhosts rendus avec une allowlist `envsubst` passent `nginx -t`.

La revue Cubic du head `5d8b8f3` a enfin relevé six écarts supplémentaires,
tous reproduits avant correction : contrôle incomplet de l'artefact reranker,
commande de rendu TLS absente du README Nginx, empreintes de schéma dupliquées,
lien relatif cassé dans le plan de migration et doubles sources pour les
timeouts PostgreSQL et l'identifiant du reranker. Le runtime exige désormais
un répertoire explicite avec `manifest.json`, un inventaire exhaustif
`SHA256SUMS`, l'identifiant canonique et chaque octet conforme avant d'importer
`CrossEncoder`; les fichiers non listés, symlinks, chemins non sûrs et
substitutions sont refusés. Le script E2E appelle exactement ce même vérificateur.

Les empreintes `pg_get_constraintdef`/`pg_get_indexdef` ont une source unique,
`schema_head_003_fingerprints.env`, montée dans PostgreSQL et copiée dans
l'image applicative. Le test d'intégration calcule toujours les objets depuis
la migration réelle sur PostgreSQL 16 et appelle maintenant la sonde
applicative sur ce même schéma. Les paramètres de connexion read-only sont
centralisés dans `readiness_db.py`, et `retrieval_hybrid_v2.RERANK_MODEL`
dérive de l'identifiant canonique sans le redéfinir.

La revue Codex du head `81825b0` a ensuite identifié trois écarts valides. Le
contexte Docker deny-by-default n'autorisait pas explicitement quatre sources
copiées ; `/health` pouvait accepter les montages modèles de repli vides ; et
le DSN de revue n'était pas ouvert avant de déclarer le service prêt. Les trois
défauts ont été reproduits par tests avant correction.

Le commit `ec8f743` rend l'allowlist Docker exhaustive et introduit un
vérificateur commun d'artefact : manifeste canonique, configuration, poids,
inventaire exact incluant le manifeste, SHA-256 de chaque fichier, refus des
symlinks, substitutions, chemins non sûrs et fichiers non listés. Le
healthcheck vérifie les deux montages avant `200`. L'artefact
embedding préparé par le dépôt inclut désormais son manifeste dans
`SHA256SUMS`.

Une seconde sonde PostgreSQL ouvre `PG_REVIEW_DSN` avec les mêmes timeouts
read-only et exige exactement : rôle non administratif, aucune appartenance au
propriétaire, `USAGE` sans `CREATE`, aucune création de base ou table
temporaire, `SELECT` sur `rag_chunks`, aucun privilège mutatif de table et seul
`UPDATE(review_status)`. Les 17 dérives unitaires sont refusées. Le runner
PostgreSQL réel prouve ce contrat avec le rôle éphémère `lot41_review` et
conclut de nouveau `LOT40_HYBRID_INTEGRATION=PASS`.

La validation consolidée du cycle antérieur `5d8b8f3`, avant les trois
corrections Codex du head `81825b0`, établissait :

- 216 tests ciblés schema/reranker/runtime/retrieval réussissent ;
- Ruff est vert et `mypy` valide 49 fichiers du moteur ;
- la suite non-intégration complète est verte ;
- le cycle PostgreSQL réel migration/adoption/rollback/scope/review/retrieval
  conclut `LOT40_HYBRID_INTEGRATION=PASS` et exécute la sonde head 003 ;
- un Compose PostgreSQL sur volume neuf devient `healthy`, puis son healthcheck
  explicite réussit avec le manifeste partagé ;
- `docker compose config` est valide, l'image
  `nexus-rag-engine-v2:lot41u-final` se construit et expose exactement les neuf
  routes attendues sans module writer/legacy.

Après le correctif `ec8f743`, 128 tests ciblés modèles/readiness/runtime
réussissent, Ruff et `mypy` sont verts, la suite non-intégration complète du
moteur est verte, `docker compose config --quiet` réussit et une construction
Docker `--no-cache` depuis le contexte deny-by-default copie toutes les sources
puis expose exactement les neuf routes sans writer ni legacy.

La relecture de tous les fils encore ouverts a enfin requalifié un ancien P1
Cubic comme toujours valide malgré son ancre devenue obsolète : un attaquant
capable de remplacer le montage modèle pouvait aussi régénérer le manifeste et
`SHA256SUMS`, puis présenter un paquet entièrement cohérent mais non approuvé.
Le commit `245e5f6` exige désormais, pour chaque modèle, l'empreinte SHA-256 de
`SHA256SUMS` fournie séparément par la configuration de déploiement. La sonde
refuse une empreinte absente, mal formée ou différente avant d'accepter le
manifeste et les poids. Les scripts de construction affichent cette ancre pour
sa conservation hors artefact ; les scripts de vérification et Compose la
rendent obligatoire. Deux tests remplacent poids, manifeste et inventaire de
façon cohérente tout en conservant l'ancre approuvée initiale et prouvent le
refus. Les 69 tests ciblés artefacts/runtime sont verts, comme Ruff, `mypy` et
la suite non-intégration complète du moteur.

Le commit `15c17b4` issu de la qualification pré-fusion a d'abord supprimé la
mémorisation de la preuve par chemin afin qu'un remplacement postérieur à une
première sonde verte soit refusé. La sonde PostgreSQL vérifie désormais dynamiquement
toutes les colonnes de `rag_chunks` et n'accepte `UPDATE` que sur
`review_status`, y compris si le schéma gagne une colonne ultérieure. Le test
de contexte Docker dérive enfin ses attentes de chaque instruction `COPY`, au
lieu d'une liste partielle maintenue à la main.

Le commit `1842e4d` ferme deux derniers fils pré-fusion. `/health` refuse
désormais un `PG_RAG_DSN` propriétaire, administratif, créateur ou détenteur
d'un quelconque privilège mutatif ; le pool ajoute une transaction read-only
indépendante des grants. Un test PostgreSQL réel accorde temporairement
`UPDATE(source_label)` au rôle retrieval et prouve son rejet avant révocation.
Le runtime v2 instrumente aussi chaque requête par code et latence, avec une
allowlist de labels et la valeur unique `unmatched` pour tout chemin inconnu.

La première exécution PostgreSQL sur ce commit a utilement échoué :
`has_table_privilege(..., 'UPDATE')` ne détecte pas un grant limité à une
colonne. Le commit `585f519` remplace donc les contrôles `INSERT`, `UPDATE` et
`REFERENCES` concernés par une inspection dynamique de toutes les colonnes de
`rag_chunks` et `rag_schema_migrations`. Le même test réel est ensuite passé et
prouve que `UPDATE(source_label)` rend la readiness retrieval négative.

La revue du head `1013d63` a relevé trois écarts valides supplémentaires. Les
sondes PostgreSQL utilisaient `pg_has_role(..., 'USAGE')`, qui ignore une
appartenance `NOINHERIT` néanmoins exploitable par `SET ROLE`. Elles utilisent
maintenant `MEMBER` et refusent toute appartenance directe ou indirecte à un
autre rôle. Le runner PostgreSQL réel crée un rôle writer intermédiaire,
l'accorde temporairement aux deux rôles runtime et prouve leur readiness
négative avant révocation : `RUNTIME_SET_ROLE_MEMBERSHIP_REJECTED=PASS`.

Le rehachage intégral des modèles à chaque appel public de `/health` aurait pu
amplifier des probes parallèles en lecture de plusieurs gigaoctets. Chaque
worker effectue désormais la preuve cryptographique exhaustive pendant son
démarrage, avant d'accepter le trafic, puis conserve une attestation des
métadonnées. `/health` compare l'ancre externe en mémoire et au plus 10 000
entrées attestées sans lire aucun contenu modèle. L'inventaire lu au démarrage
est borné à 16 Mio. Les remplacements, ajouts, suppressions et changements
d'ancre usuels sont refusés. Enfin, le test de contexte Docker traite
explicitement les options `COPY` et ignore les sources d'un stage
`COPY --from`, évitant de confondre un nom de propriétaire, un mode ou une
sortie de build avec une source du contexte.
Les 119 tests ciblés de readiness, runtime et modèles sont verts ; Ruff et
`mypy` sont verts sur les modules modifiés, et l'intégration PostgreSQL réelle
conclut de nouveau `LOT40_HYBRID_INTEGRATION=PASS`.

La première CI exhaustive du head documentaire a ensuite détecté une fixture
historique légitimement devenue incomplète : le test du cycle de vie du pool
entrait dans le lifespan FastAPI sans provisionner les attestations modèles.
Le démarrage échouait donc, conformément au nouveau contrat fail-closed, avant
de pouvoir tester le pool. La fixture simule désormais explicitement les deux
attestations et laisse la vérification réelle aux tests runtime dédiés.

La lecture GraphQL exhaustive des fils a ensuite révélé quatre remarques plus
récentes non reprises dans le courriel initial. Le commit `5f9af0b` ferme les
quatre écarts : la méthode HTTP est ramenée à `other` hors allowlist ; la sonde
review refuse désormais tout grant `INSERT` par colonne ; les tuples de tests
de privilèges sont documentés position par position ; enfin, la readiness du
schéma contrôle les 31 colonnes, les dix index et l'expression générée
`text_tsv`, avec des empreintes provenant du registre unique versionné.

Le cycle rouge a reproduit les quatre défauts. Après correction, 68 contrôles
ciblés, Ruff et `mypy` sont verts. Le runner PostgreSQL réel conclut
`REVIEW_ROLE_COLUMN_LEVEL_INSERT_REJECTED=PASS`,
`SCHEMA_BASE_INDEX_DRIFT_REJECTED=PASS` et
`LOT40_HYBRID_INTEGRATION=PASS`. Une instance PostgreSQL fraîche a également
prouvé `POSTGRES_COMPLETE_SCHEMA_HEALTH=PASS`, puis le healthcheck a refusé la
suppression de `idx_rag_chunks_text_tsv` avant de repasser vert après sa
restauration.

La revue du head `e04180a` a encore identifié deux risques opérationnels
valides. Une rafale sur `/health` pouvait lancer quatre connexions PostgreSQL
par requête, et quatre workers Uvicorn exposaient quatre registres Prometheus
indépendants derrière un seul endpoint. Le commit `4795dfc` coalesce désormais
les sondes profondes sous verrou, conserve les résultats positifs comme
négatifs pendant cinq secondes, limite `/health` au loopback dans les deux
vhosts et fixe le runtime canonique à un worker. Les compteurs sont ainsi
complets pour le processus servi ; toute montée en charge horizontale devra
ajouter une agrégation Prometheus qualifiée. Le cycle TDD a d'abord produit
quatre échecs, puis les 42 tests runtime/proxy ciblés, Ruff et `mypy` sont verts.

La fermeture de toute route `/admin/*` rendait par ailleurs obsolète la sonde
historique du Cockpit, qui appelait encore `/admin/health`. Le commit `9ebbf02`
fait désormais appeler `/health` par le BFF, conserve un payload public réduit à
`ok` ou `unavailable` et ajoute deux tests de route. Le cycle rouge a observé
l'appel legacy exact avant correction ; les huit tests ciblés du client moteur
et de la route santé ainsi qu'ESLint sont ensuite passés.

La revue Cubic du même head a demandé de compléter l'attestation structurelle.
Le commit `7bcf57f` ajoute les valeurs par défaut, `format_type` et `atttypmod`
aux 31 définitions de colonnes, impose donc explicitement `vector(1024)`, et
compare tous les index prêts/valides au lieu de filtrer seulement les dix noms
attendus. Les contraintes `CHECK` sont elles aussi comparées comme un ensemble
exact avec leur état de validation. Le healthcheck PostgreSQL applique le même
contrat et refuse dimension, default ou index supplémentaire divergents.

La remarque selon laquelle les empreintes n'étaient jamais recalculées en CI
était inexacte mais révélait un manque de lisibilité : l'intégration PostgreSQL
réelle appelle déjà `schema_head_003_ready()` sur une base fraîche. Le test et
son marqueur ont été renommés pour produire explicitement
`SCHEMA_FINGERPRINTS_REAL_DB=PASS`. Le cycle complet conclut aussi
`SCHEMA_DEFAULT_AND_EXTRA_INDEX_DRIFT_REJECTED=PASS` et
`LOT40_HYBRID_INTEGRATION=PASS`. Une sonde PostgreSQL fraîche séparée a refusé
`vector(768)`, un default modifié et un onzième index, puis a repassé verte après
restauration.

La revue du head `08bb1e4` a enfin relevé cinq écarts supplémentaires, tous
traités par le commit `f95e987`. Le rôle PostgreSQL de revue refuse maintenant
le privilège effectif `TRIGGER`, avec une mutation réelle `GRANT`/`REVOKE`
prouvée par `REVIEW_ROLE_TRIGGER_PRIVILEGE_REJECTED=PASS`. Lorsque les artefacts
de taxonomie ne sont pas présents dans l'image v2, le catalogue retourne
désormais `taxonomy_exists=false` et une incohérence explicite au lieu d'un vert
non démontré. Le TTL de la sonde PostgreSQL démarre après la fin de la sonde,
donc même une sonde plus lente que cinq secondes reste coalescée.

Le garde de lecture seule des tests SQL utilise des frontières de mots et
détecte donc aussi un mot-clé mutatif suivi d'une tabulation ou d'un saut de
ligne sans confondre `attisdropped` avec `DROP`. Enfin, les 31 colonnes et leurs
types, defaults et typmods ne sont plus maintenus deux fois :
`schema_head_003_columns.tsv` constitue le contrat versionné unique, chargé
strictement par la sonde Python et importé dans une table temporaire par le
healthcheck PostgreSQL. Le fichier est explicitement monté dans PostgreSQL et
copié dans l'image applicative par l'allowlist Docker.

Le cycle TDD a d'abord produit six échecs ciblés. Après correction, 75 tests
ciblés, la suite non-intégration complète, Ruff et `mypy` sont verts. Le runner
PostgreSQL réel conclut de nouveau `LOT40_HYBRID_INTEGRATION=PASS`, incluant le
test `TRIGGER`. Une instance pgvector 16 neuve utilisant le contrat partagé a
atteint `POSTGRES_SHARED_COLUMN_CONTRACT_HEALTH=PASS`, puis son conteneur
éphémère a été supprimé.

La première CI locale exhaustive suivant ce cycle a détecté une course réelle
dans la sonde bornée des modèles : sur le système de fichiers du runner, un
fichier ajouté pouvait partager le timestamp observable du répertoire et ne
pas être vu par la seule comparaison des entrées déjà attestées. Le commit
`45c00e9` énumère désormais à chaque sonde au plus 10 000 chemins, compare
l'ensemble exact aux chemins attestés et conserve aussi `st_ctime_ns` pour
détecter une modification de même taille dont le `mtime` a été restauré. La
sonde continue de ne lire aucun contenu de poids.

Deux régressions déterministes couvrent le cas d'un répertoire dont les
métadonnées semblent stables et la réécriture de même taille avec `mtime`
restauré. Les sept tests d'attestation, Ruff et `mypy` sont verts ; la suite
non-intégration complète du moteur repasse également verte.

La revue suivante a identifié trois frontières encore incomplètes. Un volume
Compose neuf ne créait pas les rôles restreints exigés par la readiness ;
l'attestation du schéma ne couvrait pas `relrowsecurity`,
`relforcerowsecurity` et `pg_policy` ; enfin, le healthcheck devait refuser un
nom de colonne dupliqué dans le contrat TSV. Le commit `d25d5a8` provisionne les
deux rôles avec quoting `psql` et secrets lus depuis l'environnement, ajoute
l'état RLS à la preuve Python et shell, et rend `column_name` unique dans la
table temporaire du healthcheck.

Le cycle RED a produit 12 échecs ciblés avant implémentation. Après correction,
20 tests schema/Compose sont verts, Ruff est vert et `mypy` ne relève aucune
erreur sur 52 fichiers. Le runner PostgreSQL réel conclut
`SCHEMA_ROW_SECURITY_DRIFT_REJECTED=PASS` puis
`LOT40_HYBRID_INTEGRATION=PASS`. Un conteneur pgvector 16 vierge exécutant les
quatre scripts Docker réels a conclu `FRESH_BOOTSTRAP_RUNTIME_ROLES=PASS`,
`FRESH_BOOTSTRAP_HEALTH=PASS` et `RETRIEVAL_WRITE_DENIED=PASS`, avant d'être
supprimé.

La première CI exhaustive après ce commit a échoué honnêtement sur deux tests
du moteur. Le premier cherchait encore les `GRANT` dans le runner alors que leur
source canonique est désormais `provision_runtime_roles.sh`; il inspecte à
présent ce fichier et vérifie aussi que seuls `SELECT` et
`UPDATE(review_status)` sont accordés. Le second test legacy d'un téléchargement
simulé appelait encore le DNS réel avant son mock HTTP et a rencontré une panne
de résolution ; la validation d'URL est maintenant neutralisée explicitement
dans cette fixture. Les deux régressions ciblées et Ruff sont verts avant la
relance exhaustive.

Cette relance a ensuite révélé une course plus profonde dans le smoke Docker :
`pg_isready` sans hôte interrogeait le socket Unix du serveur PostgreSQL
temporaire utilisé par l'entrypoint pendant l'initialisation, puis le premier
`psql` pouvait rencontrer son arrêt avant le lancement du serveur final. Le
runner attend désormais `127.0.0.1:5432` dans le conteneur ; le serveur
temporaire n'écoute volontairement pas TCP, donc seul le processus final peut
satisfaire ce garde-fou.

Les commits `ddf8d06` et `826812e` consignent respectivement l'isolation de la
fixture DNS et l'attente du serveur PostgreSQL final. Le rapport ne les attribue
donc plus au parent `d25d5a8`. Sur `826812e`, la CI locale racine exhaustive a
produit **13 réussites et 0 échec** : 1 757 tests `rag-pedago`, toute la suite
`rag-engine` avec PostgreSQL réel, 174 tests Cockpit, deux builds propres et
aucune vulnérabilité npm. Le run GitHub `pull_request` exact
[`30777200044`](https://github.com/cyranoaladin/RAG/actions/runs/30777200044)
a également réussi ses six jobs.

La revue de ce head a encore détecté une double dépense au premier retrieval :
les loaders rehachaient les poids déjà vérifiés au démarrage et leurs caches
n'étaient pas synchronisés. Le commit `a6cc47a` transmet maintenant aux loaders
les chemins issus des attestations de lifespan et sérialise les deux
constructions froides ; un appel autonome hors lifespan conserve la
vérification exhaustive. Le même commit retire au rôle review tout accès à
`rag_schema_migrations`. La sonde refuse aussi `SELECT`, `INSERT`, `UPDATE`,
`REFERENCES`, `DELETE`, `TRUNCATE`, `TRIGGER` et toute appartenance au
propriétaire sur ce registre, afin de fermer les volumes existants autant que
le bootstrap frais.

Le cycle TDD a d'abord échoué sur cinq régressions ciblées. Après correction,
223 tests modèles/runtime/readiness/runner sont verts, Ruff et `mypy` sont
verts, et l'intégration PostgreSQL réelle conclut
`REVIEW_ROLE_MIGRATION_REGISTRY_INSERT_REJECTED=PASS` puis
`LOT40_HYBRID_INTEGRATION=PASS`.

La revue Cubic du head `4046f83` a correctement signalé que la sérialisation
seule laissait encore une fenêtre entre l'attestation de démarrage et le premier
retrieval. Le commit `294ba28` construit donc embedding et reranker dans le
lifespan, avant le `yield` FastAPI, puis revalide l'ensemble borné des chemins,
inodes, tailles, `mtime` et `ctime` attestés. Un changement pendant le
chargement fait échouer le démarrage ; aucun trafic ne précède la construction
des modèles. Le second constat ne portait pas sur le garde lui-même, couvert
position par position en unité, mais sur une preuve d'intégration surqualifiée :
le test et son marqueur nomment désormais exactement la mutation `INSERT`
qu'ils exécutent.

Les 33 tests ciblés du lifespan, des loaders et de la concurrence sont verts,
comme Ruff et `mypy`. La suite non-intégration complète du moteur et le cycle
PostgreSQL réel repassent verts ; ce dernier conclut
`REVIEW_ROLE_MIGRATION_REGISTRY_INSERT_REJECTED=PASS` puis
`LOT40_HYBRID_INTEGRATION=PASS`.

La revue Codex du head `d3d9f36` a ensuite produit cinq fils. Le constat selon
lequel les modèles restaient lazy était déjà corrigé par `294ba28` : le
lifespan appelle bien `preload_runtime_models()` avant son `yield`. Les quatre
autres scénarios étaient recevables. Le commit `9084000` :

- compare désormais la dimension native du modèle d'embedding préchargé à la
  dimension canonique avant de construire le reranker et avant tout trafic ;
- refuse tout grant `REFERENCES`, y compris limité à une colonne de
  `rag_chunks`, sur le rôle review ;
- réinclut explicitement l'artefact de scope signé du paquet
  `nexus-contracts` après le hard-deny générique des répertoires `artifacts`
  dans `.dockerignore` ;
- valide les bornes et les types `PG_POOL_MIN_SIZE`, `PG_POOL_MAX_SIZE` et
  `PG_POOL_TIMEOUT_S` dans la readiness publique, ainsi que la concordance du
  DSN validé.

Le cycle TDD a d'abord produit six échecs ciblés, puis **36 réussites** après
correction. Ruff, `mypy`, `git diff --check` et toute la suite non-intégration
du moteur sont verts. Le premier smoke PostgreSQL post-correctif a validé le
nouveau marqueur `REVIEW_ROLE_COLUMN_LEVEL_REFERENCES_REJECTED=PASS`, puis a
rencontré une variance HNSW approximative sur un voisin de rang 50 déjà verte
dans les exécutions précédentes et sans code retrieval modifié par ce patch.
La relance complète sur une base neuve est verte et conclut le nouveau marqueur
ainsi que `LOT40_HYBRID_INTEGRATION=PASS`. L'oracle ANN n'a pas été affaibli.

Le run GitHub exact du head documentaire `3c32b0b`,
[`30780741000`](https://github.com/cyranoaladin/RAG/actions/runs/30780741000),
a reproduit cette variance HNSW : les cinq autres jobs sont verts et le job
`rag-engine` ne tombe que sur l'égalité entre le préfixe ANN et l'oracle
séquentiel, avec `target-000` omis au rang 50. Le commit `6e93b38` ne modifie
pas le runtime, ses bornes de 200+1 candidats ni les réglages de plan testés.
Il porte uniquement la connexion de **preuve empirique exacte** à
`hnsw.ef_search = 1000`, valeur maximale, afin que la comparaison contre
l'oracle séquentiel ne dépende plus de la construction aléatoire du graphe.
Les contrôles séparés conservent `ef_search = 40` pour le plan runtime et
`ef_search = 1` pour l'underfill borné. Deux smokes complets consécutifs sur
deux bases neuves concluent `HNSW_DISTINCT_FIXTURE_EMPIRICAL_ORACLE_PREFIX=PASS`
et `LOT40_HYBRID_INTEGRATION=PASS` après ce correctif de preuve.

La revue du head `1099a41` a correctement relevé que ce réglage maximal ne
transformait pas HNSW en index exact, ainsi que quatre lacunes de readiness. Le
commit applicatif `8b56c6e2bb848386caee556538b2dcc7d2885f82` remplace donc cette
surqualification et ferme les cinq fils :

- l'égalité au préfixe est désormais prouvée par un store séquentiel exact,
  avec `enable_indexscan = off` et `enable_bitmapscan = off`; HNSW reste testé
  séparément pour son plan, son filtrage strict, son ordre, ses bornes et son
  scénario d'underfill ;
- `/health` valide réellement la configuration du credential BFF, l'enveloppe
  d'identité signée et son artefact de scope ;
- `/health` charge et valide la version, le backend, les domaines et chaque
  entrée du catalogue v2 monté ;
- les DSN retrieval et review doivent produire le même couple autoritatif
  `system_identifier` PostgreSQL et `current_database()` ; une copie distincte
  rend donc la readiness indisponible ;
- le contrôle tautologique qui recomparait `PG_RAG_DSN` à lui-même après
  normalisation a été supprimé, tandis que `PoolSettings.from_env()` continue
  de valider le DSN, les types et les bornes du pool.

Le cycle test-first a d'abord échoué à la collecte en l'absence du validateur
de catalogue, puis **76 tests ciblés** sont passés. Ruff et `mypy` sont verts.
Deux exécutions PostgreSQL réelles sur des bases neuves — le smoke ciblé puis
la CI racine — concluent `DENSE_EXACT_ORACLE_PREFIX=PASS` et
`LOT40_HYBRID_INTEGRATION=PASS`. La CI locale complète du head applicatif est
verte : 13 cibles sur 13, 1 757 tests `rag-pedago`, toute la suite
non-intégration `rag-engine`, 174 tests Cockpit, deux builds Next.js et zéro
vulnérabilité npm. Cette preuve locale porte sur le commit applicatif cité ; le
commit documentaire suivant doit encore recevoir ses propres checks GitHub.

La revue Cubic du head documentaire `2aaf43a` a ensuite relevé deux écarts
valides dans le validateur de catalogue. Le commit applicatif `3793f3f` :

- impose structurellement `domains.quarantine.retrievable: false`, de sorte
  qu'un catalogue monté ne puisse jamais promouvoir la quarantaine en surface
  de retrieval ;
- reconstruit chaque test négatif à partir du catalogue canonique complet et
  vérifie le message de la règle ciblée : version, catalogue vide, voie inconnue
  et quarantaine ; aucun test ne peut plus réussir prématurément sur l'absence
  du premier champ obligatoire.

Le test de quarantaine a d'abord échoué car la configuration interdite était
acceptée, puis les quatre cas isolés sont passés après correction. La première
relance exhaustive a gardé 12 cibles racine vertes mais rencontré une course
préexistante de granularité `ctime` dans un test d'attestation de modèle. Cinq
relances isolées ont confirmé le caractère intermittent. La préparation de ce
test attend désormais, pendant au plus deux secondes, une mutation de
métadonnées effectivement observable. Cinq nouvelles relances, toute la suite
non-intégration du moteur et le smoke PostgreSQL réel sont verts, avec
`DENSE_EXACT_ORACLE_PREFIX=PASS` et `LOT40_HYBRID_INTEGRATION=PASS`. Le head
documentaire final reste soumis à la CI GitHub exacte.

La revue Codex du même head a enfin identifié une incompatibilité entre la
nouvelle sonde `pg_control_system()` et les rôles minimaux créés sur une base
PostgreSQL 16 neuve. Le test statique a d'abord échoué faute de grant. Le
commit `2c4322a` accorde ensuite directement `EXECUTE` sur cette seule fonction
aux rôles retrieval et review ; il n'accorde ni `pg_monitor`, ni héritage, ni
écriture. Le smoke sur PostgreSQL réel confirme
`RUNTIME_ROLE_SHARED_DATABASE_IDENTITY=PASS`, puis tous les contrôles de
moindre privilège et `LOT40_HYBRID_INTEGRATION=PASS`.

La revue Codex du head documentaire `9d186ae` a enfin identifié que
`/search/v2` exposait encore les modèles locaux `SearchV2Request` et
`SearchV2Response`, tandis que le Cockpit traduisait manuellement
`q/collection/hits`. Le test de frontière a d'abord échoué en observant
`SearchV2Request` dans la route FastAPI. Le commit applicatif `83aa736` :

- monte directement `RetrievalRequest → RetrievalResponse` depuis
  `nexus-contracts` sur `/search/v2` et supprime les DTO publics locaux ;
- fait construire la requête contractuelle par le BFF depuis l'identité signée
  et l'artefact de scope, jamais depuis un profil fourni par le navigateur ;
- résout la collection côté moteur à partir de l'unique matière contractuelle,
  exige sa présence dans l'artefact signé, puis compare toutes les dimensions
  d'autorité au scope serveur avant le retrieval ;
- valide la requête et la réponse avec les schémas générés, propage directement
  les résultats et avertissements contractuels, et retire la traduction manuelle
  des hits dans le Cockpit ;
- refuse l'ancien payload local en `422`, les divergences de profil en `403` et
  les options de pipeline non supportées sans élargir le scope ;
- ajoute l'adaptateur contractuel à l'allowlist du contexte Docker et à l'image
  aplatie, afin que le runtime `api_v2:app` conserve le même chemin d'import que
  les tests et le code source.

Les tests rouge/vert de la route et du BFF, les 174 tests Cockpit, le lint, le
typecheck, le build Next.js, la suite non-intégration complète du moteur et le
smoke PostgreSQL réel sont verts. Ce dernier conclut notamment
`HTTP_SEARCH_V2=PASS`, `MONO_SUBJECT_HTTP_SCOPE=PASS`,
`SIGNED_IDENTITY_HTTP_REAL_DB=PASS` et `LOT40_HYBRID_INTEGRATION=PASS`.

La CI GitHub `pull_request` du head documentaire `3232a88` a ensuite réussi
ses six jobs obligatoires, ainsi que GitGuardian et Cubic. Les revues
exact-head Cubic et Codex ont toutefois détecté que les filtres optionnels
`need.notions`, `need.desired_doc_types` et `need.difficulty_max` étaient
adaptés puis ignorés par le pipeline PostgreSQL. Le test rouge a confirmé que
les trois variantes retournaient `200` et lançaient le retrieval.

Le commit `b6a628d` ferme cette ambiguïté sans inventer une sémantique SQL non
prouvée : tant que ces filtres ne sont pas implémentés de bout en bout, la
route les refuse explicitement en `422 Unsupported retrieval filters` avant
tout appel au pipeline. Le test de visibilité fixe aussi explicitement
`status_detail=candidat_libre`, source contractuelle de l'audience `libre`, au
lieu de dépendre implicitement du comportement par défaut. Les trois tests
rouge/vert, les cinq rôles de visibilité, Ruff, `mypy` sur 52 fichiers et la
suite non-intégration complète du moteur sont verts. Ce nouveau head remplace
la preuve `3232a88` et doit donc obtenir sa propre CI GitHub exacte.

La CI GitHub `pull_request` du head documentaire `d4df590`,
[`30787366866`](https://github.com/cyranoaladin/RAG/actions/runs/30787366866),
a ensuite réussi ses six jobs obligatoires, ainsi que GitGuardian et Cubic. La
revue Codex exacte a toutefois ouvert deux nouveaux P1 avant toute fusion :
`/health` validait séparément le scope pilote signé et le catalogue monté, et
l'empreinte du schéma ignorait les triggers non internes de `rag_chunks`.

Le commit applicatif `9ac295d62d8f7d5a71563c48442b1fbaec3c9d6b`
ferme les deux écarts :

- la readiness croise chaque sujet de l'artefact signé avec sa collection
  déclarée, son domaine strictement retrievable et les dimensions matière,
  niveau, voie et statut. Une collection peut rester déclarée mais dormante
  sans être artificiellement activée ; une collection absente, un domaine
  fermé ou une dimension divergente rendent la santé indisponible ;
- la sonde du head 003 inclut désormais l'ensemble exact des triggers non
  internes. Le contrat courant en exige zéro, quelle que soit leur activation,
  et ne peut donc plus déclarer sain un volume portant un trigger stale capable
  d'altérer ou de bloquer les décisions de review.

Les tests ont d'abord échoué avec une readiness qui ne consultait jamais
l'alignement scope/catalogue et une ligne de schéma à huit composantes refusée
par la sonde à sept composantes. Après correction, les suites unitaires ciblées,
Ruff et `mypy` sur 52 fichiers sont verts, ainsi que toute la suite
non-intégration du moteur. Le smoke PostgreSQL 16 ajoute un vrai trigger
`BEFORE UPDATE`, observe la readiness négative, le supprime, puis retrouve le
head sain avec `SCHEMA_TRIGGER_DRIFT_REJECTED=PASS`; le run se termine par
`LOT40_HYBRID_INTEGRATION=PASS`.

## Éléments restant hors de ce lot

Ces points ne sont pas masqués par les corrections runtime :

- LOT41A : review GitHub formelle, reviewer habilité distinct, dépôt/PR/base/head
  exacts, challenge canonique et révocation ;
- LOT42 : attestations indépendantes `quality`, `gate` et `review`, liées au
  contenu, au scope et aux items réellement remis ;
- revue humaine exhaustive de la golden suite, actuellement
  `HUMAN_REVIEW_PENDING` ;
- corpus réel, droits et couverture pédagogique substantielle ;
- protection live de `main`, secrets de production, TLS, rate limiting,
  sauvegarde/restauration et rollback effectivement exercés dans
  l'infrastructure cible ;
- durcissements P2 de supply chain et des workflows secondaires, à traiter
  dans un lot dédié sans mélanger leur autorité avec ce correctif runtime.

## Commits du lot avant preuve finale

| SHA | Objet |
| --- | --- |
| `9663140` | spécification du runtime v2 fail-closed |
| `c1dc619` | plan d'implémentation |
| `95e1a4d` | ADR-0024 et test de décision |
| `2fee69b` | vérification read-only du head PostgreSQL 003 |
| `df4b53f` | application FastAPI v2 lecture/revue |
| `e2c1273` | image minimale sans writer |
| `c971e82` | bootstrap Compose au head 003 |
| `7c1ee15` | allowlist Nginx |
| `998e220` | documentation opérationnelle alignée |
| `c5d0ce9` | exécution fiable des tests d'intégration |
| `c8364ac` | correction de typage révélée par la CI exhaustive |
| `dcd69b7` | rapport de lot initial |
| `66f5018` | validation des contraintes et registre frais canonique |
| `fe92cc5` | preuves complémentaires du bootstrap |
| `944bf81` | authentification BFF et identité signée du catalogue v2 |
| `56fbdba` | rapport de revue du catalogue v2 |
| `5d8b8f3` | intégrité du head 003, proxy loopback, timeouts, reranker hors-ligne et tests hermétiques |
| `81825b0` | intégrité vérifiée des artefacts, sources canoniques et documentation finale |
| `ec8f743` | readiness stricte des artefacts et du rôle PostgreSQL de revue |
| `50789c0` | documentation et preuve du cycle readiness |
| `245e5f6` | ancre externe des inventaires de modèles |
| `15c17b4` | revalidation continue des artefacts et moindre privilège review |
| `6c86032` | documentation du dernier cycle de revue |
| `1842e4d` | moindre privilège retrieval et instrumentation HTTP v2 |
| `585f519` | détection des grants retrieval limités à une colonne |
| `1013d63` | documentation et preuve du test PostgreSQL fail-closed |
| `8ebdc48` | fermeture de `SET ROLE`, santé modèle bornée et parseur Docker |
| `54aa9b2` | documentation du cycle final de revue |
| `058a810` | isolation de la fixture du cycle de vie FastAPI |
| `5f9af0b` | schéma retrieval complet, grants `INSERT` et métriques bornées |
| `4795dfc` | santé PostgreSQL coalescée et métriques mono-processus |
| `9ebbf02` | sonde Cockpit alignée sur `/health` v2 |
| `7bcf57f` | types, defaults, contraintes et index PostgreSQL exacts |
| `f95e987` | privilège `TRIGGER`, taxonomies fail-closed, TTL et contrat de colonnes partagé |
| `45c00e9` | inventaire borné exact et `ctime` des modèles attestés |
| `d25d5a8` | rôles runtime frais, état RLS et unicité du contrat de colonnes |
| `ed4d479` | preuve documentaire du bootstrap runtime PostgreSQL |
| `ddf8d06` | fixtures runtime hermétiques sans résolution DNS réelle |
| `826812e` | attente du serveur PostgreSQL final dans le smoke Docker |
| `a6cc47a` | attestations modèles réutilisées et registre interdit au rôle review |
| `294ba28` | préchargement des modèles avant trafic et preuve `INSERT` précise |
| `9084000` | dimension runtime, pool, scope packagé et `REFERENCES` review fail-closed |
| `6e93b38` | exploration maximale réservée à l'oracle HNSW empirique |
| `8b56c6e` | autorités, catalogue et identité PostgreSQL attestés ; oracle dense exact |
| `3793f3f` | quarantaine fail-closed, tests catalogue isolés et preuve `ctime` stable |
| `2c4322a` | exécution minimale de la sonde d'identité par les deux rôles runtime |
| `83aa736` | frontière `/search/v2` alignée sur `RetrievalRequest → RetrievalResponse` |
| `b6a628d` | refus fail-closed des filtres retrieval non implémentés |
| `9ac295d` | alignement scope/catalogue et attestation exacte des triggers PostgreSQL |

## Décision de livraison

LOT41U peut passer à la vérification du head final de la PR #88. La fusion
reste conditionnée aux checks `pull_request` du head exact, à l'absence
de fil non résolu et à la protection de `main`. Le commit de fusion ou de
squash devra ensuite obtenir son propre run `push` vert sur `main`.

Cette fusion rendra `main` source de vérité pour les correctifs runtime audités,
mais ne changera pas le verdict global : **GO_LIVE: NO_GO** jusqu'aux autorités,
revues et preuves de production listées ci-dessus.
