# LOT41U — Durcissement fail-closed du runtime v2

## Verdict

**LOT41U_REVIEW_FIXES_GREEN_AWAITING_FINAL_HEAD_CI**

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
| Head source avant le dernier cycle de revue | `5d8b8f3fc430e2b9d47b55f6a937c832bb78bd7b` |
| Plan de données | runtime FastAPI v2, PostgreSQL/pgvector, Compose, Nginx |
| Contrats partagés | aucune évolution |
| Verrous de gouvernance | aucun changement, 18/18 conformes |
| Décision d'architecture | ADR-0024, runtime v2 limité à lecture et revue |

## Traitement des constats indépendants

| Constat | Décision et correction | État |
| --- | --- | --- |
| `RAG-INGEST-001` — écritures sans scope complet | Le writer v2 non autoritaire est retiré de l'application, de l'image, de Compose et du proxy. Aucune donnée client libre n'est promue en scope signé. Un nouveau writer ne pourra revenir qu'avec LOT41A/LOT42. | fermé par suppression de la surface |
| `RAG-MIGRATION-001` — base Compose neuve sans `003` | PostgreSQL monte `init.sql` puis `003_profile_filtering.sql`; son healthcheck et `/health` vérifient les SHA du registre et les définitions exactes des cinq colonnes, de l'index et des cinq contraintes validées. `v2-up` attend la santé. | corrigé |
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
4. le healthcheck PostgreSQL recalcule les trois SHA, exige cinq colonnes de
   profil, cinq définitions de contraintes validées, la définition et le
   prédicat exacts de `idx_rag_chunks_profile_reviewed`, puis les trois entrées
   exactes du registre ;
5. l'API relit les mêmes preuves via un rôle `SELECT`, avec `connect_timeout`,
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
- Compose PostgreSQL sur volume temporaire neuf : résultat réel `5|t|5` pour
  colonnes, index et contraintes ;
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
est borné à 16 Mio. Les remplacements, ajouts,
suppressions et changements d'ancre usuels sont refusés ; le chargement initial
du modèle refait la preuve complète. Enfin, le test de contexte Docker traite
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
| commit courant | isolation de la fixture du cycle de vie FastAPI |

## Décision de livraison

LOT41U peut passer à la vérification du head final puis à une PR dédiée. La
fusion reste conditionnée aux checks `pull_request` du head exact, à l'absence
de fil non résolu et à la protection de `main`. Le commit de fusion ou de
squash devra ensuite obtenir son propre run `push` vert sur `main`.

Cette fusion rendra `main` source de vérité pour les correctifs runtime audités,
mais ne changera pas le verdict global : **GO_LIVE: NO_GO** jusqu'aux autorités,
revues et preuves de production listées ci-dessus.
