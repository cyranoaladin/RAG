# LOT — Préparation du staging externe, sans déploiement

- **Branche** : `glr/staging-preparation` (sur `glr/external-api`)
- **Runbook** : [`docs/runbooks/staging_externe.md`](../runbooks/staging_externe.md)

## Pourquoi maintenant, et pourquoi sans déployer

Le staging externe ne peut pas être monté sur l'image actuelle : tant que la
PR #148 n'est pas fusionnée, l'image ne porte pas ses modules et aucun Compose
n'injecte le registre de clients. Le déployer maintenant échouerait au
démarrage, et on apprendrait au mauvais moment ce qu'on sait déjà.

Ce qui **ne** dépend pas de cette fusion, en revanche, se prépare dès
maintenant : le matériel de secret, le registre de clients, les credentials
que le Cockpit et l'agent externe attendront. Aucun port n'est ouvert, aucune
image n'est lancée.

## Le producteur

`services/rag-engine/scripts/prepare_staging_environment.py` fabrique, hors du
dépôt :

```
api-clients.json    registre du moteur — empreintes SHA-256 seules
staging.env         --env-file du Compose, complet
credentials.env     jetons EN CLAIR, à distribuer hors bande
```

les trois en `0600`, aucun secret n'étant jamais imprimé sur la sortie
standard — un secret qui y passe finit dans un historique de shell ou une
capture de CI.

### Ce qu'il refuse, et pourquoi

| Refus | Raison |
|---|---|
| destination sous le dépôt | un secret committé ne se rattrape pas par une rotation mais par une réécriture d'historique |
| empreinte d'inventaire absente ou malformée | c'est un **fait** du déploiement ; en générer une plausible fabriquerait la preuve que le runtime vérifie |
| répertoire hôte relatif | Compose lirait une source non-chemin comme un volume nommé et rejetterait le projet |
| variable exigée par le Compose et non rendue | un `staging.env` amputé n'échouerait qu'au premier `up` |
| variable rendue sans être exigée | l'environnement cesserait de décrire le Compose |

La liste des variables est **lue du Compose**, jamais recopiée : le jour où
il en exige une de plus, le producteur échoue au lieu de livrer un
environnement incomplet.

### Trois clients, portée minimale

| `client_id` | Portée | Pour |
|---|---|---|
| `cockpit-staging` | `rag:search` | le BFF du Cockpit |
| `agent-externe-staging` | `rag:search` | le test E2E hors réseau |
| `ops-staging` | `rag:admin` | la revue et l'exploitation |

Le Cockpit et l'agent cherchent ; ils n'administrent pas. La console
d'exploitation administre ; elle ne se substitue pas au Cockpit dans le
journal d'accès.

## Mesures

```
STAGING_PREPARATION=PASS

SECRETS_IN_REPOSITORY=0          (refus prouvé sur 3 chemins du dépôt)
PLAINTEXT_TOKENS_IN_REGISTRY=0
PLAINTEXT_TOKENS_ON_STDOUT=0
FILE_MODE=0600                   (les trois fichiers)
API_CLIENTS=3                    portées disjointes, clés distinctes
COMPOSE_VARIABLES_COVERED=21/21  (lues du Compose)
UNKNOWN_VARIABLES=0
REGISTRY_AUTHORITIES=1           (RAG_API_CLIENTS laissé vide)
```

Le registre produit est jugé par le **lecteur du runtime**, pas par le banc :
`load_api_clients()` l'accepte, et chaque jeton en clair résout son client et
lui seul, avec sa portée — `cockpit-staging` cherche et n'administre pas,
`ops-staging` administre et ne cherche pas.

13 épreuves pour le producteur, toutes sur des sorties réelles écrites dans un
`tmp_path` ; 16 pour la recette externe.

## La recette de l'agent extérieur

`scripts/staging_external_acceptance.py` mesure la seule question qui compte :
depuis un client hors réseau et hors conteneur, muni des seuls credentials
qu'on lui a remis, obtient-on des réponses **citées** ?

Il ne construit ni requête ni transport à lui : il réutilise le client externe
livré (`scripts/rag_query_external.py`). Redéfinir ici la forme du contrat
ferait deux vérités, et la recette finirait par valider son propre simulacre.
Un test l'exige — aucun `method="POST"` fabriqué à la main.

**Une portée par exécution**, parce que le jeton d'identité est émis pour une
portée : prétendre en couvrir trois d'un seul appel serait une fiction. La
recette complète se fait en autant d'exécutions que de portées.

Ses refus, tous éprouvés :

| Refus | Raison |
|---|---|
| zéro résultat | un « 200 vide » n'est pas une réponse |
| résultat sans citation | une affirmation nue n'étaye rien |
| citation sans page ni source | elle n'étaye pas davantage |
| résultat hors de la portée signée | le défaut le plus grave, servi silencieusement |
| taxonomie vide, ou qui n'annonce pas la collection visée | interroger ce que le service ne déclare pas servable mesurerait autre chose |
| collection sans question déclarée | une question générique mesurerait que le service répond, pas qu'il enseigne |

Un test confronte la table de questions au **registre de scopes réel** : une
question visant une collection qui n'existe pas ne mesure rien. Il a d'ailleurs
attrapé deux entrées inventées (HLP terminale, HGGSP) qui n'ont aucun scope.

### `/ready` n'existe pas, et n'a pas à exister

Le point 37 du brief demande `GET /ready`. La surface n'en a pas — et `/health`
fait déjà ce travail : autorités de runtime, artefacts de modèle,
réconciliation de base, dimension d'embedding, 503 sinon. C'est la sonde du
healthcheck du Compose. Ajouter `/ready` dupliquerait une surface externe sans
rien mesurer de plus.

## Ce qui reste à l'opérateur

DNS, TLS, hôte et terminaison : le moteur ne termine pas TLS et le Compose ne
publie que sur la loopback. Ces décisions sont nommées dans le runbook, avec
la barrière d'entrée — image par digest, release figée, #148 fusionnée — qu'il
ne faut pas franchir avant l'heure.
