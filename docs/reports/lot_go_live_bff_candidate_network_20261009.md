# Lot — interface réseau interne du BFF pour le candidat blue-green

Base relue le 9 octobre 2026 : `main=14cb787310d1ffda1e8c6f215cfb1435e80573fb`.
Le candidat public de PR #302/#303 expose l'API sur un port **loopback** de
l'hôte et place initialement API, DB et Prometheus sur `rag_net`. Le vhost
public proposé par PR #305 ne transmet que `POST /search/v2` ; le BFF a aussi
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
un scope V2 gouverné parmi les onze collections V4/V5. Il transmet les trois
credentials distincts prévus par le contrat (`Authorization` service,
`X-RAG-API-Key` client et `X-Nexus-Identity` utilisateur) directement à l'API
sur `bff_net`. L'empreinte du client Cockpit dans `api-clients.json` doit
porter uniquement `rag:search`, sans `rag:ingest` ni `rag:admin` ; cette
contrainte et les refus des routes de revue/écriture devront être vérifiés sur
la cible finale avant publication. La visibilité `student → internal` reste
refusée ; aucun filtre
de retrieval, droit, placement ou chunk n'est modifié ici.

Validation locale sans staging ni production : le Compose résolu des deux
couleurs conserve trois images par digest, aucun port DB et les seuls ports
API/Prometheus sur loopback. `NEXUS_REQUIRE_DOCKER=1 pytest -q` sur les tests
Compose, préflight, plan V2 signé et témoin réseau donne **43 succès**. Le
témoin crée deux ponts temporaires et trois conteneurs Node éphémères, sans
port publié ni bind ; un client sur `bff_net` obtient 200 sur les quatre
routes API ci-dessus, tandis que la DB témoin sur `rag_net` est inaccessible
par DNS et par IP privée. Le nettoyage laisse zéro conteneur et zéro réseau
`nexus-bff-witness-*`. Cette preuve est une **segmentation réseau locale** :
elle n'est pas un E2E du vrai Cockpit et ne valide aucun élève public.

`STUDENT_E2E_PASS=false` et `GO_LIVE_READY=false` pour ce lot. L'E2E réel
attendra l'image Cockpit de provenance canonique, un déploiement staging
final à la même couleur et au SHA final, les scopes/placements publics revus
et scellés, puis les réponses 401/403, enseignant/élève, hors scope et
citations sur le chemin Cockpit → BFF → API v2 → pgvector.
