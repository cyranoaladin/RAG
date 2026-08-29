# État du déploiement — ce qui existe, ce qui manque

*28 août 2026. Constats vérifiés depuis ce poste, pas une estimation.*

## Le fait qui change le cadrage

**Un déploiement de production existe déjà et il est en ligne.** Le mandat parlait
de `rag-ui.nexusreussite.academy` comme d'une cible à atteindre ; c'est une cible
**déjà servie**.

| Vérification | Résultat |
|---|---|
| DNS `rag-ui.nexusreussite.academy` | résout vers un serveur unique |
| DNS `rag-api.nexusreussite.academy` | même serveur |
| `https://rag-ui…` | **HTTP 200**, TLS valide |
| `https://rag-api…/health` | **HTTP 200** |
| `http://rag-api…/health` | **301** → redirection HTTPS en place |
| Certificat | Let's Encrypt, `notAfter = 27 septembre 2026` |
| nginx | `infra/nginx/rendered/{rag-ui,rag-api,rag-n8n}.conf` versionnés |

Rien de tout cela n'est à construire. Ce qui manque n'est pas l'infrastructure.

## Ce qui manque réellement

### 1. La production sert un code antérieur — écart majeur

| | Production | Local canonique |
|---|---|---|
| `/health` | `{"status":"healthy"}` | `{status, schema_head, embedding_model, embedding_dim_declared, pgvector_dim}` |
| Corps de `/search/v2` | `{q, collection, k}` | `RetrievalRequest` du contrat |

La production **ignore le contrat `nexus-contracts`** que le cockpit est censé
être le seul à parler. Elle expose l'ancien DTO. Un cockpit écrit contre le
contrat actuel ne fonctionnerait pas contre cette production.

**Conséquence** : la mise en service n'est pas un déploiement initial, c'est une
**migration** — avec un existant en ligne, donc un plan de bascule et un
rollback, pas un `docker compose up`.

### 2. `/metrics` est exposé publiquement

`https://rag-api…/metrics` répond **200 sans authentification** : 29 236 lignes,
dont `ingestor_requests_total`, les latences par route et les volumes ingérés.

Ce n'est ni un secret ni une donnée personnelle — c'est la **troisième
catégorie** de la politique de divulgation : ni l'un ni l'autre, et pourtant une
information exploitable (volumétrie, disponibilité, surface de routes).

`docs/NGINX_METRICS_POLICY.md` existe dans le service. **Il n'est pas appliqué
sur cette production.**

### 3. Vérifications d'authentification — une alerte levée puis écartée

Un premier contrôle a montré `/search/v2` répondant **422 sans credential**, là
où le local refuse en **401**. Cela ressemblait à une absence de barrière.

**Vérification faite : c'est faux.** Avec un corps *bien formé*, la production
répond **401**. Le 422 provenait de l'ordre de validation — le corps est validé
avant l'authentification pour un corps malformé. Une divulgation de schéma, pas
un défaut d'authentification.

Consigné parce que l'alarme a été levée : un contrôle qui affirme sans vérifier
est le défaut que ce dépôt combat, et il vaut aussi pour les alertes.

`/collections` et `/collections/v2` répondent bien **401**.

### 4. Ce qui n'a pas pu être établi depuis ce poste

Honnêtement délimité — l'accès au serveur n'a pas été utilisé :

- **quelle version d'image** la production exécute, et depuis quand ;
- **quelle base** elle sert : le corpus des 26 documents, un autre, ou aucun ;
- **si un `docker compose` y est en place**, ou un déploiement manuel ;
- **où sont ses secrets** (`NEXUS_INTERNAL_TOKEN_SECRET`, `RAG_BFF_SERVICE_TOKEN`)
  et s'ils diffèrent de ceux du local ;
- **s'il existe des sauvegardes** de sa base ;
- **le renouvellement du certificat** est-il automatisé — il expire le 27/09.

Ces six points exigent un accès SSH au serveur. Ils ne sont pas devinables, et
aucune supposition n'est offerte ici à leur place.

### 5. Le service `ui` référencé par nginx n'existe pas dans les compose

`rendered/rag-ui.conf` fait `proxy_pass http://ui:8501` — un Streamlit. Aucun
service nommé `ui` n'apparaît dans les `docker-compose*.yml` du dépôt. Soit il
est défini côté serveur hors dépôt, soit la configuration rendue est un vestige.

## Liste des manques, ordonnée

| # | Manque | Nature |
|---|---|---|
| 1 | Le retrieval ne répond pas — 18/18 en `503` (dette n°26) | **bloquant, local** |
| 2 | Aucun rôle `student` ne peut interroger le corpus (dette n°28) | **bloquant, gouvernance** |
| 3 | La production sert un code antérieur au contrat | **bloquant, migration** |
| 4 | Le corpus des 2451 documents n'est pas sur cette machine | **bloquant, données** |
| 5 | Inventaire du serveur de production (les six points du §4) | prérequis |
| 6 | `/metrics` public en production | sécurité |
| 7 | Renouvellement TLS non vérifié — échéance 27/09 | échéance |
| 8 | Service `ui` référencé mais introuvable dans le dépôt | cohérence |

**Ce qui n'est PAS un manque** : DNS, TLS, nginx, redirection HTTPS, hébergement.
Tout cela existe et fonctionne.
