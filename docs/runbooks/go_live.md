# Runbook de qualification avant go-live — Nexus RAG

## Verdict courant

**GO_LIVE: NO_GO**

Ce runbook qualifie le runtime v2 ; il n'autorise pas son ouverture publique.
Le moteur déployable est strictement un runtime **lecture/revue** lancé par
`api_v2:app`. Il ne contient aucun writer, worker, parseur de document ou client
de source distante. Toute publication demeure interdite tant qu'une remise
autoritaire n'a pas prouvé la chaîne `quality → gate → review`.

Les bloqueurs externes au runtime restent :

- LOT41A : autorité humaine GitHub formelle, vérifiable et révocable ;
- LOT42 : attestations autoritaires liées au contenu et au scope publié ;
- revue humaine exhaustive de la suite golden ;
- preuves de production pour TLS, secrets, sauvegarde/restauration et rollback ;
- corpus réel, droits et licences vérifiés par une personne habilitée.

## 1. Périmètre canonique

Le stack versionné dans `services/rag-engine/infra/docker-compose.v2.yml`
comprend uniquement PostgreSQL/pgvector, l'API v2 et Prometheus. Il expose les
capacités suivantes : santé, métriques locales, retrieval, chat verrouillé,
catalogue, readiness et revue. Toute route d'ingestion ou route legacy est
fermée par l'image et par l'allowlist Nginx.

Les requêtes métier passent exclusivement par le **Cockpit BFF** : session
Auth.js, scope serveur, credential machine dédié et enveloppe d'identité signée.
Un jeton humain présenté directement au moteur n'est jamais une autorité.

## 2. Prérequis obligatoires

- Docker Engine et plugin Compose supportant `up --wait` ;
- DNS et TLS canoniques pour le Cockpit et l'API ;
- gestionnaire de secrets externe au dépôt ;
- artefact local `intfloat/multilingual-e5-large` vérifié en 1024 dimensions ;
- artefact local `cross-encoder/ms-marco-MiniLM-L-6-v2` vérifié hors-ligne ;
- deux rôles PostgreSQL distincts déjà provisionnés et audités ;
- Cockpit HTTPS et BFF déployés avec la même configuration d'identité interne ;
- sauvegarde persistante avant toute migration d'un volume existant.

Les DSN runtime sont :

- `PG_RAG_DSN` : rôle limité à `SELECT` sur `rag_chunks` et
  `rag_schema_migrations` ;
- `PG_REVIEW_DSN` : rôle limité à `SELECT` sur ces deux tables et à la mise à
  jour du seul statut de revue dans `rag_chunks`.

Le propriétaire PostgreSQL et les credentials de migration ne doivent jamais
être fournis au conteneur API.

## 3. Préparer la configuration sans exposer les secrets

Depuis `services/rag-engine/infra` :

```bash
cp .env.example .env
chmod 600 .env
```

Remplir `.env` depuis le gestionnaire de secrets. Les autorités indispensables
sont `RAG_BFF_SERVICE_TOKEN`, `NEXUS_INTERNAL_TOKEN_SECRET`,
`NEXUS_INTERNAL_TOKEN_ISSUER`, `NEXUS_INTERNAL_TOKEN_AUDIENCE`,
`NEXUS_SSO_ISSUER` et `NEXUS_SSO_AUDIENCE`. Ne pas activer `xtrace` et ne jamais
imprimer les valeurs.

Valider ensuite le rendu sans afficher la configuration :

```bash
docker compose -f docker-compose.v2.yml --env-file .env config --quiet
```

Vérifier les deux artefacts avant démarrage :

```bash
RAG_ENV=preproduction \
MODEL_ARTIFACT_DIR="$RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR" \
MODEL_ARTIFACT_INVENTORY_SHA256="$RAG_EMBEDDING_MODEL_INVENTORY_SHA256" \
../../../scripts/e2e/verify-embedding-model-artifact.sh

RAG_ENV=preproduction \
MODEL_ARTIFACT_DIR="$RAG_RERANKER_MODEL_ARTIFACT_HOST_DIR" \
MODEL_ARTIFACT_INVENTORY_SHA256="$RAG_RERANKER_MODEL_INVENTORY_SHA256" \
../../../scripts/e2e/verify-reranker-model-artifact.sh
```

Chaque répertoire doit contenir `manifest.json`, `config.json`, au moins un
poids `*.safetensors` ou `pytorch_model.bin`, et un `SHA256SUMS` exhaustif qui
inclut le manifeste. Les scripts chargent aussi les modèles hors-ligne par
défaut ; ne pas utiliser `SKIP_LOAD_TEST=1` pour une qualification de
production. L'empreinte SHA-256 de `SHA256SUMS` doit être approuvée à la
construction, conservée dans la configuration de déploiement protégée et
distincte du montage modèle. Ne jamais la recalculer depuis le montage au
moment de la promotion : elle constitue l'ancre externe qui empêche le
remplacement simultané des poids, du manifeste et de leur inventaire. Un ancien
artefact embedding dont le manifeste n'était pas inclus
dans `SHA256SUMS` doit être régénéré avec
`prepare-embedding-model-artifact.sh`, pas modifié dans le montage actif.

## 4. Préparer PostgreSQL

### Volume neuf

Au premier démarrage uniquement, PostgreSQL applique dans l'ordre
`00_init.sql`, puis `01_003_profile_filtering.sql`. Son healthcheck échoue tant
que le head `003_profile_filtering`, les SHA-256 canoniques, les définitions
exactes de l'index et des cinq contraintes validées ne sont pas présents. Le script
`02_register_bootstrap_migrations.sh` calcule les SHA-256 des trois migrations
canoniques et enregistre atomiquement `001`, `002` et `003` dans
`rag_schema_migrations`. Le runner transactionnel doit ensuite reconnaître ce
volume avec `MIGRATIONS_APPLIED=0` et `MIGRATIONS_ADOPTED=0`.

### Volume existant

Ne pas compter sur les scripts d'initialisation Docker, qui ne sont rejoués que
sur un volume vide. Sauvegarder, puis appliquer le runner transactionnel :

```bash
cd services/rag-engine/infra
BACKUP_ROOT=/backup/rag ./scripts/apply_pgvector_migrations.sh
```

Le runner doit terminer au head 003. En cas d'échec ou de données incompatibles,
arrêter la procédure et restaurer selon le runbook de rollback ; ne jamais
forcer le démarrage de l'API.

Avant promotion, relire les `GRANT` effectifs et prouver que les deux DSN
runtime n'ont ni création, ni suppression, ni modification de contenu ou de
schéma.

Le rôle `PG_RAG_DSN` doit pouvoir lire `rag_schema_migrations`, sinon `/health`
échoue volontairement en `503` : ne pas lui substituer le rôle owner. La sonde
refuse également tout privilège d'écriture, de création, d'administration ou
d'appartenance au propriétaire ; le pool force les transactions read-only.
`/health` ouvre également `PG_REVIEW_DSN` et vérifie le rôle effectif : attributs
non administratifs, `USAGE` sans `CREATE`, aucune table temporaire, lecture de
`rag_chunks` et seul `UPDATE(review_status)`. Un rôle absent, sous-privilégié ou
sur-privilégié maintient volontairement l'API en `503`.

## 5. Démarrer le runtime fermé

Depuis `services/rag-engine` :

```bash
make v2-up
```

Cette cible utilise `docker compose up -d --build --wait`. Un service unhealthy
fait échouer la commande ; aucun délai arbitraire ni succès de substitution
n'est accepté.

La première sonde de chaque worker recalcule les inventaires des deux modèles,
puis recalcule cette preuve à chaque sonde et avant chaque chargement initial.
Une modification d'artefact exige un nouveau déploiement ; ne jamais remplacer
les poids sous un conteneur en cours d'exécution.

Contrôles locaux :

```bash
curl -fsS http://127.0.0.1:8001/health | jq -e \
  '.status == "healthy" and .schema_head == "003_profile_filtering" and .pgvector_dim == 1024'

test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/ingest)" = 404
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1/admin)" = 404
```

Après au moins une requête métier de smoke, vérifier que `/metrics` contient
`ingestor_requests_total` et `ingestor_request_latency_seconds`. Les chemins
inconnus doivent être agrégés sous `path="unmatched"` afin de conserver une
cardinalité bornée.

## 6. Installer le proxy par allowlist

Rendre `infra/nginx/rag-api.conf.template` avec le domaine API canonique et le
port local, puis valider avant rechargement :

```bash
envsubst '${RAG_API_EXTERNAL_DOMAIN} ${NGINX_API_PORT}' \
  < infra/nginx/rag-api.conf.template \
  | sudo tee /etc/nginx/sites-available/rag-api.conf >/dev/null
sudo nginx -t
sudo systemctl reload nginx
```

La liste passée à `envsubst` est obligatoire : un appel sans liste effacerait
les variables natives Nginx telles que `$binary_remote_addr` et `$request_uri`.

Le proxy public doit :

- transmettre seulement les neuf routes exactes du runtime ;
- limiter `/metrics` aux adresses loopback ;
- rendre `410` sur les chemins legacy explicitement révoqués ;
- rendre `404` pour tout autre chemin ;
- rediriger HTTP vers le domaine canonique configuré, sans faire confiance à
  `Host` ni aux headers `X-Forwarded-*` comme autorité.

Le vhost alternatif `infra/nginx/rag-v2.conf`, s'il est utilisé, doit lui aussi
être rendu avec `NGINX_API_PORT` et vise exclusivement le port loopback publié
par Compose. Aucun Nginx hôte ne doit résoudre le nom Docker `ingestor`.

## 7. Vérifier le Cockpit BFF

Les tests fonctionnels authentifiés sont exécutés depuis le Cockpit, jamais par
appel direct avec un rôle humain :

1. une session `reviewer` autorisée lit la queue de son seul scope ;
2. cette session peut prendre une décision `reviewed` ou `quarantined` ;
3. une session `student` ou `teacher` reçoit `403` avant tout appel moteur de
   décision ;
4. une origine différente de `NEXUS_COCKPIT_PUBLIC_ORIGIN` est refusée avant la
   lecture du corps ;
5. une collection hors scope est refusée ;
6. une recherche ne retourne que des chunks `reviewed` et produit des citations
   conformes au contrat partagé ;
7. le chat reste `answer_generation_locked`.

## 8. Preuves opérationnelles encore requises

Avant de changer le verdict, archiver pour le SHA candidat exact :

- les checks `pull_request`, puis le run `push` du SHA fusionné sur `main` ;
- le readback de protection de branche et une approbation formelle ;
- le rendu Compose et l'identité des images épinglées ;
- un démarrage sur volume vierge et un upgrade de volume restauré ;
- un exercice backup → restore → rollback ;
- les résultats TLS, rate limiting, logs sans secrets et alerting ;
- l'attestation humaine golden et les attestations LOT41A/LOT42 ;
- les preuves de droits et de couverture substantielle du corpus réel.

Tant qu'un de ces éléments ou un bloqueur initial manque, conserver
**GO_LIVE: NO_GO** et ne pas ouvrir de capacité d'ingestion ou de génération.
