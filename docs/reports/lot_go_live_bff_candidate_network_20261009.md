# Lot — interface réseau interne du BFF pour le candidat blue-green

Base initiale relue le 9 octobre 2026 :
`main=14cb787310d1ffda1e8c6f215cfb1435e80573fb`. Après fusion de #305,
base intégrée : `main=73916df3196b046e94c3b4126c140500a59c742a`.
Le candidat public de PR #302/#303 expose l'API sur un port **loopback** de
l'hôte et place initialement API, DB et Prometheus sur `rag_net`. Le vhost
public livré par PR #305 ne transmet que `POST /search/v2` ; le BFF a aussi
besoin de `/health`, `/collections/readiness` et `/collections/v2`. Il ne peut
donc pas utiliser ce vhost comme amont interne.

Le Compose candidat déclare maintenant deux ponts Docker **propres à sa
couleur** : `nexus-rag-{blue|green}_rag_net` pour l'API, la DB et Prometheus,
et `nexus-rag-{blue|green}_bff_net` pour l'API seule. Le préflight de PR #303
accepte exactement ces deux noms, exactement ces attachements et toujours
exactement trois services. Il refuse un réseau externe, la DB ou Prometheus
sur `bff_net`, l'API absente de l'un des deux réseaux, un service ajouté, un
port DB publié, un bind supplémentaire ou inscriptible et une image API sans
provenance. Le digest du Compose résolu, signé par la readiness V2 de PR #304,
inclut cette nouvelle topologie. `mutation_allowed=false` demeure.

Le futur Cockpit **par digest**, dans son propre projet de la même couleur,
devra rejoindre uniquement `nexus-rag-{color}_bff_net`, jamais `rag_net`, et
fixer côté serveur `RAG_ENGINE_INTERNAL_URL=http://ingestor:8001`. Le port
Cockpit destiné au reverse proxy restera lié au loopback de l'hôte. Ce projet
ne doit exposer aucune DB ni aucun writer, monter aucun checkout et charger
ses secrets depuis un magasin hors checkout en lecture seule. Son image et
son digest devront provenir du workflow canonique du SHA final et être liés
à la readiness signée avant tout déploiement. Ce lot ne crée ni image Cockpit,
ni service Cockpit, ni digest fictif : ce travail est porté séparément.

Le protocole BFF utilisera une session signée **mono-matière** sélectionnant
exclusivement le scope V2 de la collection dans sa release publique successeur
propriétaire, parmi les deux releases non-HGGSP et HGGSP nommées par le
registre mixte final. Chaque scope sera lié au digest du subject de sa release,
après validation des droits et de la visibilité, revue humaine et scellement.
Les scopes V4/V5 du rehearsal restent hors du chemin public.
Il transmet les trois
credentials distincts prévus par le contrat (`Authorization` service,
`X-RAG-API-Key` client et `X-Nexus-Identity` utilisateur) directement à l'API
sur `bff_net`. L'empreinte du client Cockpit dans `api-clients.json` doit
porter uniquement `rag:search`, sans `rag:ingest` ni `rag:admin` ; cette
contrainte et les refus des routes de revue/écriture devront être vérifiés sur
la cible finale avant publication. La visibilité `student → internal` reste
refusée ; aucun filtre
de retrieval, droit, placement ou chunk n'est modifié ici.

Validation locale sans staging ni production au commit
`508e65775907e6ab98090a842d9e337a2a6ab005` (tree
`a9a6e0f3f711beb1f58c3bbfa669ccd07ba37623`) : le Compose résolu des deux
couleurs conserve trois références d'images par digest synthétique, aucun port
DB et les seuls ports API/Prometheus sur loopback. Depuis la racine du dépôt,
avec le venv isolé activé, la commande complète donne **45 succès** :

```bash
NEXUS_REQUIRE_DOCKER=1 python -m pytest -q \
  services/rag-engine/tests/test_public_blue_green_compose.py \
  services/rag-engine/tests/test_public_blue_green_preflight.py \
  services/rag-engine/tests/test_signed_public_candidate_plan.py \
  services/rag-engine/tests/test_public_bff_network_witness.py \
  services/rag-engine/tests/test_public_search_edge.py
```

Le témoin crée deux ponts temporaires et trois conteneurs Node éphémères, sans
port publié ni bind. Après une attente bornée, le client sur `bff_net` atteint
un **serveur Node témoin** qui répond 200 sur les quatre chemins ci-dessus ;
cette sonde ne lance pas l'image API candidate et ne prouve pas ses handlers.
La DB témoin est d'abord
prouvée joignable sur `rag_net` après attente bornée, puis inaccessible depuis
`bff_net` par DNS et par IP privée. Une seconde sonde positive sur `rag_net`
confirme qu'elle écoute encore après ces refus. Le nettoyage laisse zéro
conteneur et zéro réseau `nexus-bff-witness-*`. Cette preuve est une
**segmentation réseau locale** :
elle n'est pas un E2E du vrai Cockpit et ne valide aucun élève public.

`STUDENT_E2E_PASS=false` et `GO_LIVE_READY=false` pour ce lot. L'E2E réel
attendra l'image Cockpit de provenance canonique, un déploiement staging
final à la même couleur et au SHA final, les scopes/placements publics revus
et scellés, puis les réponses 401/403, enseignant/élève, hors scope et
citations sur le chemin Cockpit → BFF → API v2 → pgvector.
