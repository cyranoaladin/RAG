# Bascule de production — plan et ce qui casse

*28 août 2026. La mise en service n'est pas un premier déploiement : c'est une
migration, avec un existant en ligne.*

## L'écart, établi par mesure

`rag-api.nexusreussite.academy` répond, sert, et **parle un contrat antérieur**.

| | Production | Dépôt / local |
|---|---|---|
| `/health` | `{"status":"healthy"}` | `{status, schema_head, embedding_model, embedding_dim_declared, pgvector_dim}` |
| Corps de `/search/v2` | `{q, collection, k}` | `RetrievalRequest` (`nexus-contracts`) |
| Réponse | `{hits, seuil, returned}` | `RetrievalResponse` (`results`, citations) |
| Authentification | `Authorization: Bearer` | `x-api-token` **et** `x-nexus-identity` signée |

Vérification directe, corps vide :

```
prod  → {"detail":[{"loc":["body","q"],"msg":"Field required"}, …]}
local → {"detail":"Unauthorized"}
```

La production attend `q` et `collection`. Le contrat courant n'a ni l'un ni
l'autre : il porte `student_profile`, `curriculum_scope`, `need`, `retrieval`.

## Ce qui casse, et ce qui ne casse pas

### Ne casse pas : le cockpit

`services/cockpit/src/app/api/search/route.ts` envoie déjà un `RetrievalRequest`
avec `identityToken`, validé par `validateRetrievalResponse`. **Le cockpit est
écrit contre le contrat courant.**

Il ne peut donc *pas* fonctionner contre la production actuelle. La bascule ne le
casse pas : elle est ce qui le rend opérant. C'est le fait le plus important du
plan, et il inverse l'intuition — migrer est moins risqué que ne pas migrer.

### Casse : l'interface Streamlit

`services/rag-engine/src/ui/app_v2.py` — servie par
`rag-ui.nexusreussite.academy` — envoie l'ancien DTO :

```python
api_post("/search/v2", {"q": query, "collection": col_name, "k": k})
```

et s'authentifie par `Authorization: Bearer $API_TOKEN` seul. Après bascule elle
recevra :

- **422** sur le corps (`q` et `collection` refusés, quatre champs manquants) ;
- **401** faute d'enveloppe `x-nexus-identity` signée.

Elle lit aussi `result["hits"]`, quand la réponse portera `results`.

**Trois ruptures, pas une.** L'UI doit être migrée ou retirée du service **dans
la même fenêtre** que le moteur.

### Casse : tout appelant tiers non recensé

Aucun inventaire des appelants de `rag-api.nexusreussite.academy` n'existe. Les
métriques exposées publiquement (`ingestor_requests_total` par route) le
donneraient — c'est un usage légitime de la mesure avant de la fermer.

## Ce qui ne peut pas être établi depuis ce poste

L'accès SSH au serveur n'a pas été utilisé. Restent inconnus :

1. **Quelle image** la production exécute, et depuis quand.
2. **Quelle base** elle sert — les 26 documents, une autre, ou aucune.
3. **Si un `docker compose` y est en place**, ou un déploiement manuel.
4. **Où sont ses secrets**, et s'ils diffèrent de ceux du local
   (`NEXUS_INTERNAL_TOKEN_SECRET` et `RAG_BFF_SERVICE_TOKEN` doivent concorder
   entre cockpit et moteur, sinon toute requête échoue en 401).
5. **S'il existe des sauvegardes** de sa base.
6. **Si le renouvellement TLS est automatisé** — le certificat expire le
   **27 septembre 2026**.

**Le point 4 est bloquant** : sans secrets concordants, la bascule produit un
service qui refuse tout, et le symptôme (401 partout) ne désigne pas sa cause.

## Ordre des opérations

Aucune étape n'est exécutable depuis ce poste ; l'ordre, lui, est contraint.

**Avant la fenêtre**

1. Inventorier le serveur : les six points ci-dessus. Sans cela, on ne migre pas,
   on espère.
2. `pg_dump` de la base de production, restauré ailleurs et **vérifié** — pas
   seulement produit.
3. Concorder les secrets entre cockpit et moteur, et le vérifier par une requête
   signée réelle avant la bascule.
4. Décider du sort de l'UI Streamlit : migrer, ou retirer de `rag-ui`.

**Pendant la fenêtre**

5. Déployer l'image `nexusrag-ingestor:cu130` — **5,51 Go**, à transférer avant
   la fenêtre, pas pendant.
6. Vérifier `/health` : `schema_head = 004_artifact_placements` et
   `embedding_model` présents. C'est le témoin le plus court que le nouveau code
   sert.
7. **Rejouer la preuve cosinus sur le serveur**, contre ses propres vecteurs.
   Les 3,05·10⁻¹² mesurés ici valent pour ce matériel ; le serveur peut n'avoir
   pas de GPU, et un encodage CPU n'est pas garanti bit-à-bit identique.
8. Un tir de charge court sous rôle `student`, sur les collections servies.
9. Re-rendre la configuration nginx depuis `rag-api.conf.template` — voir
   ci-dessous.

**Après**

10. Ne retirer le rollback qu'après une journée de service réel.

## Rollback

L'image précédente reste disponible localement sous `nexusrag-ingestor:latest`
avant re-tag — **à étiqueter explicitement avant la bascule**, sans quoi le
rollback n'a pas de cible. La base n'est pas migrée par cette bascule : le
schéma reste `004_artifact_placements`. Le retour arrière est donc un simple
changement d'image, à condition que l'étiquette existe.

## `/metrics` — ce qu'il faut re-rendre sur le serveur

**Le dépôt est correct** : `infra/nginx/rag-api.conf.template` restreint déjà
l'endpoint à localhost.

```nginx
location = /metrics {
  allow 127.0.0.1;
  allow ::1;
  deny all;
  proxy_pass http://127.0.0.1:${NGINX_API_PORT}/metrics;
  proxy_http_version 1.1;
}
```

`infra/nginx/rendered/` est **ignoré par git** — un artefact local. La
configuration servie a été rendue avant l'ajout de cette restriction, ou
éditée à la main.

Ce n'est donc pas une correction de code : **c'est un re-rendu et un rechargement
sur le serveur.**

```bash
# sur le serveur, depuis le dépôt
NGINX_API_PORT=8001 envsubst '${NGINX_API_PORT}' \
  < infra/nginx/rag-api.conf.template \
  > /etc/nginx/conf.d/rag-api.conf
nginx -t && systemctl reload nginx

# vérification — doit répondre 403, non 200
curl -s -o /dev/null -w '%{http_code}\n' https://rag-api.nexusreussite.academy/metrics
```

Prometheus continue de scraper par le réseau interne : la restriction ne porte
que sur l'entrée publique.

**Tant que ce re-rendu n'est pas fait, l'endpoint reste ouvert** — 29 236 lignes
de volumétrie, latences par route et surface de routes, lisibles par quiconque.
