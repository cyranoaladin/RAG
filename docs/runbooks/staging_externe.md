# Runbook — Staging externe de l'API de retrieval

Ce staging existe pour une seule question : **un agent extérieur, hors du
réseau et hors du conteneur, peut-il appeler l'API et recevoir des résultats
cités ?** Tout ce qui ne sert pas à répondre à cette question n'y a pas sa
place.

## Barrière d'entrée

Ne rien déployer tant que les trois conditions ne sont pas réunies :

1. la PR #148 est fusionnée — avant elle, l'image ne porte pas ses modules et
   le registre de clients n'est injecté par aucun Compose ; le démarrage
   échouerait, et on apprendrait au mauvais moment ce qu'on sait déjà ;
2. une **image par digest** existe (`sha256:…`), jamais un tag mobile ;
3. la release servie et son registre sont figés, avec leurs empreintes.

La préparation ci-dessous, elle, ne dépend d'aucune de ces conditions : elle
fabrique du matériel de secret et n'ouvre aucun port.

## 1. Ce que seul l'opérateur peut fournir

| Élément | Décision |
|---|---|
| Nom DNS | `rag-staging.<domaine>` — enregistrement A/AAAA vers l'hôte |
| TLS | certificat pour ce nom (ACME ou interne). L'API n'est jamais exposée en clair |
| Hôte | Ubuntu 22.04/24.04, Docker, `infra/scripts/provision-prod.sh` pour la base |
| Terminaison | reverse proxy devant `127.0.0.1:${INGESTOR_PORT}` — le conteneur n'écoute que sur la loopback |

Le moteur ne termine pas TLS lui-même : le Compose publie sur
`127.0.0.1:8001`. Exposer ce port directement contredirait cette borne.

## 2. PostgreSQL + pgvector du staging

Base **distincte** de la production, sur son propre volume. Les rôles et leurs
mots de passe sont produits à l'étape 3 ; les migrations sont celles du dépôt :

```bash
cd services/rag-engine
bash infra/scripts/apply_pgvector_migrations.sh
```

## 3. Matériel de secret

Un seul producteur, hors du dépôt, qui refuse d'écrire sous l'arbre de travail :

```bash
cd services/rag-engine
PYTHONPATH=src python scripts/prepare_staging_environment.py \
  --destination ~/nexus-staging-secrets \
  --embedding-artifact-dir /srv/nexus/models/e5-large \
  --embedding-inventory-sha256 <64 hex> \
  --reranker-artifact-dir /srv/nexus/models/reranker \
  --reranker-inventory-sha256 <64 hex> \
  --release-registry-sha256 <64 hex> \
  --servable-corpus-dir /srv/nexus/servable-corpus \
  --servable-corpus-index-sha256 <64 hex> \
  --sso-issuer https://sso.staging.<domaine>/ \
  --sso-audience nexus-cockpit-staging
```

Il rend trois fichiers en `0600` :

```
api-clients.json    registre du moteur — empreintes SHA-256 seules
staging.env         --env-file du Compose
credentials.env     jetons EN CLAIR, à distribuer hors bande
```

Les empreintes d'inventaire, celle du registre de releases et celle de l'index
de corpus ne sont **pas** générées : ce sont des faits du déploiement, et en
fabriquer une plausible reviendrait à fabriquer la preuve que le runtime
vérifiera. Le producteur échoue si elles manquent ou n'ont pas la forme.

Trois clients, portée minimale :

| `client_id` | Portée | Pour |
|---|---|---|
| `cockpit-staging` | `rag:search` | le BFF du Cockpit |
| `agent-externe-staging` | `rag:search` | le test E2E hors réseau |
| `ops-staging` | `rag:admin` | la revue et l'exploitation |

## 4. Ce que reçoit chaque appelant

**Cockpit staging** — deux valeurs, jamais confondues :

```
RAG_ENGINE_INTERNAL_TOKEN = RAG_BFF_SERVICE_TOKEN        (credential machine)
RAG_ENGINE_API_KEY        = COCKPIT_STAGING_API_KEY      (clé de client)
```

**Agent externe** — trois valeurs, trois questions distinctes :

```
RAG_BFF_SERVICE_TOKEN → Authorization      d'où vient l'appel ?
RAG_API_KEY           → X-RAG-API-Key      que peut CE client ?
RAG_IDENTITY_TOKEN    → X-Nexus-Identity   au nom de qui ?
```

Le moteur exige les trois sur les routes de retrieval, sans aucun repli de
l'un sur l'autre : n'en fournir que deux rend 401.

## 5. Démarrage, une fois la barrière levée

```bash
cd services/rag-engine/infra
docker compose -f docker-compose.v2.yml \
  --env-file ~/nexus-staging-secrets/staging.env up -d
```

`RAG_API_CLIENTS` reste vide dans `staging.env` : le Compose fixe lui-même
`RAG_API_CLIENTS_FILE`. Deux sources feraient échouer le démarrage — c'est le
comportement voulu du runtime, et le producteur ne l'y met pas.

## 6. Recette de l'agent extérieur

Il n'y a **pas** de route `/ready`, et il n'en faut pas : `/health` est la sonde
de disponibilité — elle valide les autorités de runtime, les artefacts de
modèle, la réconciliation de base et la dimension d'embedding, et rend 503
sinon. C'est elle que le healthcheck du Compose interroge.

La recette se lance depuis un client **hors du réseau et hors du conteneur** :

```bash
RAG_API_URL=https://rag-staging.<domaine> RAG_BFF_SERVICE_TOKEN=… RAG_API_KEY=… RAG_IDENTITY_TOKEN=… python scripts/staging_external_acceptance.py   --scope prod_nsi_terminale_specialite_v1
```

Elle enchaîne `/health`, `/taxonomy/v2` — qui doit annoncer la collection visée
— puis `/search/v2` avec une vraie question, et exige que **chaque** résultat
porte une citation avec sa source et sa page. Elle rend :

```
EXTERNAL_AGENT_E2E=PASS
SCOPE=…  COLLECTION=…  SERVABLE_COLLECTIONS=…  RESULTS=…  CITATIONS=…
```

**Une portée par exécution.** Le jeton d'identité est émis pour UNE portée :
prétendre en couvrir trois d'un seul appel serait une fiction. La recette
complète se fait donc en autant d'exécutions que de portées, chacune avec son
identité — exactement ce qu'un agent extérieur vit. Trois exemples, trois
niveaux, trois matières :

```bash
--scope prod_nsi_terminale_specialite_v1        # Terminale · NSI · SQL
--scope prod_maths_premiere_gen_specialite_v1   # Première · Maths · probabilités
--scope prod_francais_seconde_tc_v1             # Seconde · Français · programme
```

Puis le Cockpit staging sur le **même** endpoint, sans contournement d'auth.

## 7. Rotation et révocation

Une clé se révoque en retirant son entrée du registre : le lecteur relit le
fichier à chaque appel, sans cache — une clé retirée cesse d'ouvrir dès que la
configuration change, sans redémarrage. Le secret d'empreinte du journal
(`RAG_ACCESS_LOG_HMAC_SECRET`) se tourne indépendamment ; la corrélation
historique est alors rompue, ce qui est le prix voulu d'une rotation.
