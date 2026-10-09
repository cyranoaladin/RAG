# ADR-0067 — Déployer le candidat public signé dans une couleur isolée

- **Statut** : proposé ; accepté seulement après revue du HEAD exact et fusion.
- **Date** : 2026-10-09.
- **S'appuie sur** : ADR-0066, le Compose public du lot 309 et le wrapper atomique existant.
- **Contrat** : aucun changement de `nexus-contracts`.

## Problème

Le lot 310 produit un bundle public V2 privé et vérifié mais refuse toujours
`--execute`. La voie V1 du wrapper exécute `pull`/`up` dans l'ancien projet et
ne peut pas servir de cutover blue-green. Un `compose up` manuel depuis un
checkout rouvrirait la divergence entre la preuve signée et le runtime.

## Décision

La voie publique conserve `plan-only` par défaut. Une exécution demande
simultanément `--execute`, `--final-cutover-go`, la readiness V2 signée et
vérifiée, l'inventaire V2 lié à la signature, le bundle intact, et un passage
frais de `check_go_live_readiness.py --assert-ready` sur un checkout propre au
SHA signé. Le GO est une saisie opérateur après l'autorisation humaine du
cutover ; le drapeau ne constitue pas, seul, une preuve de cette autorisation.

Avant `pull`, le préflight public valide les cinq services exacts, les deux
images applicatives et trois images amont par digest, les matériaux et secrets
hors Git, les montages en lecture seule, le projet/couleur
`nexus-rag-blue|green` et l'absence de toute ressource préexistante dans ce
projet. Le projet renvoyé par le préflight est confronté à la couleur choisie.
Après `pull`, signature, bundle, matériaux, readiness et inventaire du projet
sont revérifiés avant `up -d --no-build --pull never --wait --wait-timeout 300`
sur les cinq services explicites. Le service Prometheus de ce Compose n'a pas
de healthcheck : après `up`, une sonde sur son port local exige `/-/ready` et
le chargement des quatre alertes du groupe `retrieval-v2`. Le succès de
`compose --wait` seul ne suffit donc pas au verdict de santé. Aucun worker,
writer ou endpoint d'ingestion n'est ajouté. `--remove-orphans` et le projet
historique `infra` sont absents.

Un verrou exclusif non bloquant par couleur dans l'espace réseau du daemon
Docker local couvre le premier inventaire puis tout `pull`, `up` et éventuel
`down`, même si deux processus reçoivent des répertoires d'état distincts.
Avant ce verrou, le CLI exige l'endpoint Unix Docker local, vérifie son pair
`SO_PEERCRED` (daemon direct ou activation par `docker.socket` de systemd) et
refuse un namespace réseau différent de celui du daemon. La voie publique
exige en outre `--deployment-state-root` explicite, privé et durable ; le même
chemin doit être repris pour son rollback. Cette exclusion est limitée aux
invocations host-local de ce wrapper ; un acteur Docker extérieur à ce
protocole n'acquiert pas son verrou. Après succès, un état 0600 fixe digest du
bundle, chemin du bundle,
SHA source et identifiants des cinq conteneurs. Le rollback explicite refuse
un ancien bundle ou des conteneurs dont les IDs ou les labels Compose ne
correspondent plus à cette génération. Si `up` échoue, expire, ou si la sonde
Prometheus échoue, le wrapper n'exécute `down --timeout 10` que lorsque les
conteneurs présents portent tous les labels exacts du bundle courant ; une
identité absente ou ambiguë impose un refus sans `down`. Aucun volume n'est
supprimé. Si une panne survient après publication de l'état, le rollback réussi
ne retire cet état que si ses quatre identités concordent encore avec la
génération visée ; sinon l'état reste en place pour diagnostic. Le rollback
reste accessible même si le garde readiness devient
rouge après le lancement. Aucun routage Nginx ni ancien projet n'est changé
par ce lot : le switch et son rollback sont une opération de cutover distincte,
après preuve de santé et GO final.

Les volumes nommés PostgreSQL, Prometheus et Redis restent présents après
`down` sans `-v`. C'est un refus volontaire de réutiliser implicitement des
données d'une génération ou d'une initialisation partielle : le prochain
déploiement de la même couleur est bloqué par l'inventaire non vide. Une remise
à zéro, hors wrapper et après sauvegarde/autorisation opérateur, exige zéro
conteneur et réseau du projet, l'inspection des **seuls** volumes
`<projet>_rag_pgvector_data`, `<projet>_rag_prometheus_data` et
`<projet>_session_redis_data`, et leurs labels Compose exacts
`com.docker.compose.project=<projet>` et `com.docker.compose.volume` égal au
nom logique attendu. Les IDs de volumes inspectés sont figés avant retrait
ciblé, puis un nouvel inventaire doit être entièrement vide. Si un nom, un
label, un ID ou un autre service est ambigu, aucune suppression n'est permise.
Ce lot ne fournit pas de purge automatique et ne promet pas que la couleur
est immédiatement redéployable après rollback.

La voie V1, ses commandes et son protocole restent inchangés.
