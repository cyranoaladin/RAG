# Préparation de la cible d'inférence et du candidat blue-green — 9 octobre 2026

## Portée et verdict

Lecture directe de `origin/main` après `git fetch`, au commit
`2534579b3e522627b06dc98b879abfa957cd2be1` et à l'arbre
`851a5f5f244a157ad6a2f0299c26e4698dca3204`. Inventaire distant en
lecture seule sur l'alias SSH déjà autorisé `nexus-prod` (`korrigo`) à
`2026-10-09T12:44:55Z`–`12:45:29Z`. Aucun conteneur, volume, fichier Nginx ou
service de production distant n'a été modifié.

**Verdict : cible d'inférence dédiée non disponible dans l'inventaire accessible ;
capacité C0 non qualifiée ; bascule blue-green non autorisée.** Le Compose livré
ici est un *candidat de topologie* à tester avec la release publique successeur,
pas une release prête à déployer. Les manifests V4/V5 rehearsal ne sont jamais
des entrées de promotion.

## Faits opposables de capacité

L'hôte `korrigo` expose 12 threads logiques sur un Intel i7-8700, soit 6 cœurs
physiques, 62 Gio de RAM et de nombreux services sans rapport avec ce produit.
Le conteneur staging API du SHA précité utilise l'image
`sha256:826a7d086a850cd97bb120c93e6e91d9fe30e575fbedffcaa34c5ac28298a121`,
une limite de 8 CPU et 12 Gio, et reste sur le même hôte partagé. Un instantané
`docker stats --no-stream` à 12:45 UTC (0,21 % CPU, 1,005 Gio) ne représente
**pas** une mesure de charge.

Le code final de ce SHA garde `INFERENCE_MAX_CONCURRENCY=1` par processus dans
`inference_runtime.py`. L'image API installe `torch==2.4.1+cpu`. Ajouter un GPU
à cet hôte sans une image/runtime CUDA distinctement vérifiés ne change donc
pas l'exécution. La mesure historique C0 sur le staging final reste rouge :
240 réponses HTTP 503 sur 240 requêtes à 8 clients, après échec du warmup
canonique. La base n'était pas saturée (8 connexions sur 10) ; la contention
est dans l'inférence/reranker. La trace historique de profilage BS avait déjà
mesuré au mieux ~0,85 requête/s sur l'hôte partagé, alors que 8 clients avec
une médiane ≤ 3 s exigent au moins 2,67 requêtes/s par la loi de Little. Ces
mesures ne prédisent pas le débit d'un nouveau matériel : elles définissent
seulement le défaut à corriger, sans changer les budgets.

Une cible de qualification acceptable doit être **physiquement réservée** à
l'inférence et annoncée avant la mesure. Le profil de provisionnement proposé
pour une première mesure CPU est ≥ 24 cœurs physiques, ≥ 64 Gio RAM, stockage
SSD/NVMe ≥ 150 Gio, réseau privé vers sa base/son proxy et aucun co-locataire
de production historique. Ce sont des minima de *candidat*, déduits du facteur
de débit manquant et d'une marge de contention ; ils ne constituent pas une
preuve que C0 passera. Un seul processus API conserve un seul créneau et ne
peut utiliser cette capacité pour plusieurs inférences simultanées. Il faudra
mesurer le nombre de réplicas/processus et leurs budgets CPU/RAM sur la cible
dédiée, avec agrégation et scraping par réplica, puis relancer le profil C0
inchangé : 8 clients, 240 requêtes, p50 ≤ 3000 ms, p95 ≤ 6000 ms, p99 ≤
7500 ms, zéro erreur, zéro timeout, ≤ 10 connexions DB.

Le **manque externe précis** est une identité de machine dédiée joignable avec
les accès opérateur existants et un droit d'exécuter un projet de qualification
isolé. Aucun secret ne doit être transmis dans le chat. À ce jour, les seuls
alias RAG accessibles dans la configuration SSH locale sont `nexus-prod`,
`nexus-prod-direct` et `nexus-prod-staging-direct`, qui atteignent le même hôte.
Il serait trompeur de déclarer le staging `nexus-staging` ou une nouvelle pile
sur `korrigo` « dédié ».

## Candidat blue-green isolé

`services/rag-engine/infra/docker-compose.public-blue-green.yml` complète le
Compose V2 pour un projet explicitement nommé `nexus-rag-blue` ou
`nexus-rag-green`, jamais `infra` ni `nexus-staging`. Il contient uniquement
`pgvector`, `ingestor` (API lecture/revue, image par digest) et `prometheus`.
Chaque projet obtient son réseau et ses volumes DB/Prometheus propres. La DB
n'a pas de port publié ; l'API et Prometheus n'ont que des ports loopback
distincts par couleur. Aucun worker d'ingestion n'est lancé, et le Dockerfile
de l'API V2 porte une allowlist de modules sans writer.

Les sources de montage déclarées visent des fichiers en lecture seule sous un
répertoire de matériaux de release durable, hors checkout, et un magasin privé
distinct pour le registre de clients API. Ce répertoire doit être assemblé depuis le **SHA
final**, inclure les scripts SQL/init, configurations, modèle E5, reranker,
release-registry publique scellée, corpus servable et règles Prometheus, puis
être rehaché et figé avant `compose up`. Il ne doit être ni un lien `current`
mutable ni un répertoire Git. Le mot de passe DB et les secrets de signature
restent fournis par le magasin de secrets existant, jamais par Git.

Le Compose existant seul ne satisfait pas cette contrainte : il monte
`./postgres`, `./prometheus`, `../configs` et d'autres chemins du dépôt. Le
wrapper `deploy_verified_release_cli.py` actuel matérialise ses trois fichiers
Compose canoniques dans une copie temporaire, puis fait un `compose up` en
place ; il ne sélectionne pas encore deux projets/couleurs, n'inclut pas cet
overlay dans son digest signé et ne garantit pas la durée de vie des montages
relatifs. **Ce wrapper ne doit pas être invoqué comme preuve de cutover
blue-green prêt**. Le travail d'intégration doit lier l'overlay résolu,
les matériaux durables et le projet/couleur au manifeste de readiness signé,
préserver l'ancien projet, refuser tout bind de checkout, vérifier health et
charge avant une modification Nginx atomique, puis conserver l'ancienne cible
pour rollback. La partie Cockpit/BFF doit être ajoutée après fixation des
scopes de #294 et de son digest d'image ; elle n'est pas couverte par ce
Compose de recherche.

Sur `korrigo`, la configuration Nginx lue en direct dirige actuellement
`rag-api.nexusreussite.academy` vers `127.0.0.1:18002` et
`rag-ui.nexusreussite.academy` vers `127.0.0.1:18502` ; ce sont des services
historiques. Le cutover final devra modifier uniquement les vhosts RAG après
le gate humain, avec `nginx -t`, reload, test externe et restauration immédiate
du fichier précédent sur échec. Aucun switch n'a été fait ici.

## Observabilité réelle

Le staging `nexus-staging-prometheus-1` monte bien
`/etc/prometheus/rules` et l'API locale `/api/v1/rules` a renvoyé un groupe
`retrieval-v2` de **4 alertes** le 9 octobre à 12:45 UTC. En revanche,
`rag_prometheus` historique ne monte que
`/etc/prometheus/prometheus.yml` et `/prometheus` ; le répertoire de règles
est absent dans le conteneur et son `/api/v1/rules` renvoie `[]` à la même
heure. La production actuelle ne dispose donc pas de ces alertes chargées.
L'overlay du candidat monte explicitement la configuration V2 et le
répertoire des règles depuis les matériaux figés. Avant readiness, l'API du
Prometheus de la *couleur candidate* devra réellement lister les quatre
alertes et `up{job="rag-engine-v2"}=1` ; la validité du YAML seule ne suffit
pas. Le test `promtool check config` local a trouvé 1 fichier de règles et
4 règles syntaxiquement valides.

## Vérifications exécutées et limites

- `python3 -m pytest -q services/rag-engine/tests/test_public_blue_green_compose.py`
  : 1 test réussi. Il résout la fusion Compose réelle, vérifie les trois
  services, toutes les images déclarées par digest, aucun `build`, sources de
  bind synthétiques sous les deux racines déclarées, tous les binds read-only,
  API/Prometheus loopback et DB sans port. Il ne vérifie ni `realpath` des
  sources sur la cible ni empreinte des matériaux ; le wrapper final doit
  refuser les symlinks, les chemins résolus dans un checkout et tout digest
  divergent avant mutation.
- `promtool check config` via l'image Prometheus épinglée
  `sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94`
  : configuration valide, 4 règles.
- `atomic_docker_v2_rehearsal.py` rejoué localement au SHA main ci-dessus :
  `ATOMIC_DOCKER_V2_REHEARSAL_PASS=true`, preuve synthétique datée
  `2026-10-09T12:49:11Z`, projets isolés, 0 port de production publié,
  `remove-orphans=false`. JSON local hors Git, SHA-256
  `b1d29635713825ee3af1a9067e48930fd6ab8d57bca443cba855dfb93b121535`.
  Le premier appel avec sortie hors dépôt a échoué
  **après** exercice à la rédaction du chemin relatif ; un second appel avec
  sortie locale au worktree a terminé avec exit 0. Cette preuve est une fixture,
  ni le candidat final ni le rollback de la release finale.

Les tests ne vérifient pas encore : présence/empreinte de chaque matériau
final, DSN pointant la DB de la bonne couleur, authentification BFF, 11
collections, qualité, charge, backup/restore, readiness signée, rollback de
la release finale et switch Nginx. Aucun `PRODUCTION_READY`, `GO_LIVE_READY`
ou `RAG_PRODUCTION_DEPLOYED` n'est revendiqué.
