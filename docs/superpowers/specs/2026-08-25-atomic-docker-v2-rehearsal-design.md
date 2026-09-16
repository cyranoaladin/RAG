# Rehearsal Docker atomique V2 — conception

## But

Produire une preuve reproductible, versionnée et fail-closed du chemin de
déploiement atomique V2, sans utiliser les services, ports, clés ou projets de
production. Le rehearsal doit exercer le vrai daemon Docker et le vrai
`deploy_verified_release_cli.py`, avec une fixture contractuellement valide
(`AuthorizationSetV1`, matériaux de release V2, manifeste readiness V2 signé),
puis publier un transcript expurgé et une preuve JSON canonique.

## Périmètre et choix

Le harnais est un CLI autonome de `rag-engine`. Il réutilise les producteurs et
vérificateurs canoniques existants. Une petite fabrique de fixture dédiée,
non importée depuis les tests, reçoit explicitement deux graines Ed25519
générées avec `secrets.token_hex(32)` : une pour le ReviewBinding et une pour le
manifeste readiness. Les graines sont conservées uniquement en mémoire et aucun
argument par défaut ne peut capturer une valeur persistante. Aucune clé privée
n'est écrite dans le bundle, les preuves, le transcript ou Git. Seuls les
digests des ancres publiques sont consignés. Deux fabrications successives
doivent produire des digests de clés publiques distincts.

Les faits de ReviewBinding, d'auteur et d'approbation emploient uniquement les
acteurs explicites `nexus-fixture-reviewer` et `nexus-fixture-author`. La
fixture ne simule jamais l'identité GitHub d'un humain prescrit par le protocole.

La fixture Compose contient exactement les trois services applicatifs attendus
par la provenance (`ingestor`, `multilevel-worker-a-production`,
`multilevel-worker-b-production`) plus un upstream synthétique obligatoire pour
le contrat readiness. Les quatre services utilisent une image Alpine locale
épinglée par digest, n'exposent aucun port et deviennent `healthy`. Les deux
workers portent les binds read-only V2 canoniques. Le projet principal et les
deux projets étrangers reçoivent des noms aléatoires préfixés
`nexus-go-live-rehearsal-v2-`; `infra` est refusé explicitement.

Cette approche évite de dupliquer le contrat V2 et exerce le wrapper réellement.
Une simulation de `docker compose up` ne fournirait pas la preuve demandée ; une
nouvelle implémentation indépendante de la fabrication V2 créerait une seconde
source de vérité inutile.

## Déroulement

1. Vérifier Docker/Compose, l'image locale épinglée et l'absence de ports dans
   les fichiers Compose de fixture.
2. Créer un répertoire temporaire privé `0700`, générer les clés en mémoire,
   matérialiser le bundle V2 réel et figer son digest.
3. Démarrer un service témoin étranger non ciblé et photographier tous les
   conteneurs déjà actifs par ID, instant de démarrage, projet et service.
4. Sur des copies privées du bundle, exercer trois refus avec `execute=True` :
   fichier altéré sans mise à jour du manifeste ; nouveau readiness V2
   correctement signé par la clé éphémère mais déclarant un mauvais digest du
   Compose résolu, avec manifeste de bundle recalculé ; AuthorizationSet altéré
   avec uniquement le manifeste extérieur du bundle recalculé. Chaque cas doit
   atteindre sa couche de refus attendue et invoquer zéro fois la frontière
   `pull/up`. Une photographie Docker et les événements du daemon bornant le cas
   doivent aussi montrer zéro création/démarrage/réseau/volume du projet.
5. Démarrer un service étranger nommé `ingestor`, vérifier que le wrapper refuse
   la collision avant mutation, puis retirer uniquement ce projet de collision.
6. Déployer le bundle valide avec le wrapper, attendre les états `healthy` des
   trois services applicatifs et de l'upstream, puis confirmer que le témoin et
   tous les conteneurs étrangers sont inchangés.
7. Effectuer le rollback avec `docker compose down --timeout 10`, exclusivement
   contre les trois fichiers et l'env du bundle, sans `--remove-orphans`.
8. Exiger zéro conteneur du projet principal et aucun changement du témoin ou
   des services étrangers, puis retirer uniquement le projet témoin.
9. Écrire un transcript sans chemin absolu, secret ou environnement, un JSON
   canonique trié et un inventaire SHA-256.

Un `finally` tente toujours le nettoyage explicite des trois noms de projets.
Il ne lance jamais de commande visant un projet non généré par le harnais.

## Verdicts

Le verdict global vaut `true` seulement si les douze résultats sont prouvés :

- `ATOMIC_DOCKER_V2_REHEARSAL_PASS=true` ;
- `BAD_DIGEST_REFUSED=true` ;
- `BAD_READINESS_REFUSED=true` ;
- `BAD_AUTHORIZATION_SET_REFUSED=true` ;
- `FOREIGN_COLLISION_REFUSED=true` ;
- `FOREIGN_SERVICES_TOUCHED=0` ;
- `ISOLATION_PREFLIGHT_PASS=true` ;
- `PRODUCTION_PORTS_PUBLISHED=0` ;
- `PRODUCTION_PROJECT_NAME_USED=false` ;
- `REMOVE_ORPHANS_USED=false` ;
- `ROLLBACK_REHEARSAL_PASS=true` ;
- `PROJECT_CONTAINERS_REMAINING=0`.

Une exception, un refus tardif après mutation, un conteneur étranger changé, un
port publié, un projet interdit ou un résidu Docker force le verdict global à
`false` et un code de sortie non nul.

La preuve lie en plus le commit et l'arbre Git du harnais, son SHA-256, le digest
du bundle, la référence et l'ID local exacts de l'image, les versions Docker et
Compose, le digest du transcript ainsi que, pour chaque scénario, son code de
sortie, sa classe d'erreur, le nombre d'appels de mutation et les changements
Docker observés. Tout conteneur, réseau ou volume restant pour l'un des projets
générés est un échec. La preuve V1 du 24 août reste inchangée et séparée.

## Tests

Les tests unitaires couvrent d'abord les fonctions pures et le fail-closed :
validation des noms, détection de mutation, diff des photographies, canonicalité
des preuves, absence de secrets et de drapeaux interdits. Un test Docker marqué
exerce ensuite le CLI complet seulement si Docker et l'image épinglée sont
disponibles. La preuve versionnée provient d'une exécution dédiée fraîche, pas
du test unitaire.
