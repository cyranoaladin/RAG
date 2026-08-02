# LOT41U — Fermeture de l'ingestion non gouvernée et runtime v2 minimal

Date : 2026-08-02

## Contexte et objectif

L'audit indépendant de `main@ea18ba52da5778f628c4943705dd81dfa43fbc15`
confirme quatre défauts bloquants dans le runtime `rag-engine` v2 : les écritures
d'ingestion ne portent pas le scope complet requis par la review et le
retrieval, une base Compose neuve reste au schéma 002, les routes ChromaDB
historiques sont chargées par le même processus que les routes v2, et le fetch
URL suit des redirections non revalidées.

La relecture du dépôt ajoute un constat plus fondamental : les routes et le
worker v2 écrivent directement dans PostgreSQL/pgvector après parsing et
embedding, sans preuve autoritaire de la chaîne `quality → gate → review`.
Compléter simplement cinq colonnes client ne corrigerait donc pas la frontière
de confiance ; cela rendrait seulement le contournement plus fonctionnel.

LOT41U ferme ces chemins fail-closed, rend le bootstrap PostgreSQL conforme au
head 003 et sépare physiquement le runtime v2 du monolithe legacy. Il n'active
aucune ingestion, ne publie aucun corpus, ne lève aucun verrou de gouvernance et
ne modifie pas le contrat partagé.

## Décision

### Runtime v2 lecture/revue uniquement

Une application FastAPI dédiée `api_v2.py` devient l'unique entrypoint de
l'image et du Compose v2. Elle monte uniquement les routeurs de retrieval et de
review, plus les sondes de santé et de métriques nécessaires à l'exploitation.
Elle ne monte ni `api.py`, ni `admin_api.py`, ni `ingest_v2_endpoint.py`, ni les
tâches Celery.

Le Dockerfile v2 copie une allowlist explicite de modules et installe une liste
de dépendances runtime minimale. Le monolithe ChromaDB, les parseurs de
documents, les clients URL, Celery, Redis et Ollama ne sont pas présents dans
l'image v2. Les stacks legacy conservent leur propre entrypoint historique ;
elles ne sont pas présentées comme le runtime Nexus v2.

Le service `worker` est retiré du Compose v2. Aucun processus de ce stack ne
possède donc un chemin d'écriture de contenu dans pgvector. La future
réintroduction d'une publication devra consommer une remise signée et
autoritaire du plan de contrôle, liée au digest du contenu, au tenant, à la
collection, aux dimensions de profil et aux attestations indépendantes
`quality`, `gate` et `review`. Cette capacité appartient aux jalons LOT41A et
LOT42 et reste hors du présent lot.

### Fermeture HTTP explicite

Les deux configurations Nginx v2 passent d'un proxy par défaut à une allowlist
des seules routes publiques attendues : santé, métriques, catalogue,
readiness, retrieval, chat verrouillé et review BFF. Tous les chemins
`/ingest` et `/ingest/*` retournent `410`; les autres chemins inconnus ne sont
pas transmis au moteur.

Cette suppression de surface corrige à la racine les défauts d'upload non borné
et de SSRF par URL : aucun octet ni aucune URL non fiable n'atteint un parseur ou
un client HTTP dans le runtime v2. Le code d'ingestion v2 direct devient une
dette inactive et n'est ni copié ni démarré. Il ne pourra pas être réactivé par
une simple variable d'environnement.

### Bootstrap et readiness PostgreSQL

`init.sql` reste le bootstrap canonique correspondant aux migrations 001 et
002. Le Compose v2 monte ensuite le fichier versionné
`003_profile_filtering.sql` dans `docker-entrypoint-initdb.d`, sans dupliquer
son contenu. Une base neuve applique donc 003 avant d'accepter le trafic.

Pour un volume existant, les scripts d'init PostgreSQL ne sont volontairement
pas rejoués : l'opérateur doit utiliser le runner transactionnel et sauvegardé
déjà versionné. Le healthcheck PostgreSQL vérifie la présence exacte des cinq
colonnes de profil, les SHA-256 canoniques du registre ainsi que les définitions
des contraintes et de l'index du head 003. Toute dérive homonyme maintient
PostgreSQL `unhealthy` et l'application v2 ne démarre pas.

La sonde `/health` de `api_v2.py` vérifie en lecture seule le contrat de schéma
003, la dimension pgvector et les deux DSN runtime. Le rôle `PG_RAG_DSN` doit
posséder exactement `USAGE` sur `public` et le type `vector`, ainsi que `SELECT`
sur `rag_chunks` et `rag_schema_migrations`, sans aucun privilège mutatif,
d'administration, de création ou d'appartenance aux propriétaires. Son pool
force en plus les transactions read-only. Le rôle `PG_REVIEW_DSN`
doit posséder exactement `USAGE` sur le schéma `public`, `SELECT` sur
`rag_chunks` et `UPDATE(review_status)`. Tout autre privilège d'écriture sur la
table ou ses colonnes, de création sur le schéma ou la base, d'administration
ou d'appartenance au propriétaire est interdit.
Une configuration, un schéma ou un rôle incomplet ou sur-privilégié retourne un
`503` générique ; aucune reprise sur le DSN propriétaire `DATABASE_URL_SYNC`
n'est admise. Le Compose exige explicitement `PG_RAG_DSN` et `PG_REVIEW_DSN`.
Les connexions de santé ont un délai de connexion et un `statement_timeout`
bornés. Avant de rendre le service prêt, la sonde vérifie pour les deux modèles
le manifeste canonique, la présence de la configuration et des poids, l'absence
de symlink ou de fichier non inventorié et tous les SHA-256. Cette preuve est
recalculée à chaque sonde et avant chaque chargement initial afin qu'un
remplacement du montage après une sonde réussie soit détecté.
Les modèles sont chargés avec `local_files_only`, sans téléchargement au
démarrage ni sur une requête.

## Surface autorisée

Le reverse proxy v2 transmet exclusivement :

- `GET /health` ;
- `GET /metrics` ;
- `POST /search/v2` ;
- `POST /chat` ;
- `GET /collections/v2` ;
- `GET /catalogue/v2` ;
- `GET /collections/readiness` ;
- `GET /review/v2/queue` ;
- `POST /review/v2/decide`.

Les routes métier conservent leurs contrôles BFF et d'identité signée. La santé
et les métriques ne révèlent ni DSN, ni secret, ni contenu. Un middleware
observe codes HTTP et latences sur une liste de chemins bornée ; toute URL non
montée utilise le seul label `unmatched`. Les routes cache,
admin, stats et toutes les routes legacy restent inaccessibles depuis la
frontière Nginx v2.

## Gestion des erreurs

- Schéma PostgreSQL inférieur à 003 : conteneur PostgreSQL `unhealthy`, puis
  aucun démarrage du moteur.
- DSN runtime absent : rendu Compose refusé avant démarrage.
- Schéma, dimension, artefact modèle ou rôle review non vérifiable par
  `/health` : `503` avec détail générique.
- Chemin `/ingest` ou descendant : `410`, sans proxy ni lecture de corps.
- Route non allowlistée : `404`, sans proxy.
- Identité BFF absente ou invalide : comportement fail-closed existant
  `401|403|503` avant lecture métier ou accès aux données.

## Tests et preuves

Le développement suit des cycles TDD séparés :

1. tests rouges prouvant que l'image et le Compose v2 démarrent `api_v2:app`,
   n'embarquent aucun module d'ingestion et ne démarrent aucun worker ;
2. tests rouges de surface FastAPI et Nginx prouvant l'absence de toutes les
   routes legacy et d'ingestion, puis application minimale et allowlist ;
3. tests rouges du bootstrap frais et du healthcheck de schéma 003, puis montage
   de la migration canonique et blocage de readiness ;
4. tests rouges de `/health` sur schéma valide, head absent et erreur SQL, puis
   sonde read-only fail-closed ;
5. régression des suites retrieval, review, identité, migrations et intégration
   PostgreSQL réelle, suivie de la CI locale racine.

Un test de construction inspecte l'image v2 pour garantir que `api.py`,
`ingest_v2.py`, `ingest_v2_endpoint.py`, `tasks.py`, `database.py` et
`admin_api.py` ne sont pas copiés. Un test de runtime aplati importe
`api_v2:app` depuis la même topologie que l'image.

## Alternatives écartées

Ajouter `tenant`, `candidat`, `visibility`, `school_year` et
`programme_version` au payload d'ingestion est écarté : ces valeurs seraient
toujours contrôlées par l'appelant et aucune preuve `quality → gate → review`
ne serait établie.

Dériver ces champs d'un token de rôle global est écarté : ce token ne porte ni
tenant, ni collection, ni profil signé. Réutiliser l'enveloppe BFF humaine est
également écarté : une identité de session n'est pas une attestation de
publication.

Durcir uniquement le client URL est insuffisant : même sans SSRF, la route
écrirait encore hors de la chaîne de gouvernance. Une implémentation complète de
résolution DNS épinglée, redirects contrôlés, streaming borné et quotas sera
spécifiée avec le futur worker gouverné, pas conservée comme capacité dormante
activable accidentellement.

## Retour arrière

Le rollback remettrait l'entrypoint v2 sur `api:app`, réintroduirait le worker
et le proxy d'ingestion ; il rouvrirait donc les cinq défauts de confiance et
n'est pas un rollback sûr en production. En cas de problème sur le runtime
minimal, le service doit rester arrêté ou revenir au SHA antérieur uniquement
dans un environnement legacy isolé et non exposé comme Nexus v2.

Les données PostgreSQL ne sont ni transformées ni supprimées par ce lot. La
migration 003 possède déjà son runner, son contrôle de registre, sa sauvegarde
et son rollback gardé pour les volumes existants.
