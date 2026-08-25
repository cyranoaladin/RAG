# Lot technique — rehearsal Docker atomique V2 du 25 août 2026

## Verdict

Le harnais reproductible V2 a été exécuté contre le daemon Docker local avec
une fixture contractuelle `AuthorizationSetV1` +
`ProductionReadinessManifestV2`. Il utilise uniquement des projets isolés
préfixés `nexus-go-live-rehearsal-v2-`, l'image Alpine déjà présente et épinglée
par digest, aucun port et deux clés Ed25519 générées en mémoire pour ce run.
Les faits de revue utilisent exclusivement les acteurs synthétiques
`nexus-fixture-reviewer` et `nexus-fixture-author`, jamais les identités GitHub
humaines prescrites par le protocole de production.

```text
ATOMIC_DOCKER_V2_REHEARSAL_PASS=true
BAD_DIGEST_REFUSED=true
BAD_READINESS_REFUSED=true
BAD_AUTHORIZATION_SET_REFUSED=true
FOREIGN_COLLISION_REFUSED=true
FOREIGN_SERVICES_TOUCHED=0
ISOLATION_PREFLIGHT_PASS=true
PRODUCTION_PORTS_PUBLISHED=0
PRODUCTION_PROJECT_NAME_USED=false
REMOVE_ORPHANS_USED=false
ROLLBACK_REHEARSAL_PASS=true
PROJECT_CONTAINERS_REMAINING=0
```

Le bundle valide a exécuté exactement une frontière `pull` puis une frontière
`up`, et ses quatre services de fixture ont atteint l'état `healthy`. Les trois
bundles invalides et la collision étrangère ont été refusés avec
`mutation_boundary_calls=0`. Le mauvais readiness est correctement signé par la
clé éphémère du run mais porte un mauvais digest du Compose résolu : le refus
atteint donc la liaison sémantique readiness V2, pas seulement l'intégrité
extérieure du bundle.

## Provenance exacte

```text
HARNESS_COMMIT=816645a10fe797a7c1e62b2a46be5d19a238727c
HARNESS_TREE=fd732b7bab5f508ed6aeded13f3b71cf5ef8e2cb
HARNESS_SHA256=3773ea790aa8d006f54ef72d7e50d62dc9e607f574eebccb81810c1e938dffe3
BUNDLE_DIGEST=bf7d3b324e9756ceebbf736f09a1c1141544987e3128d3125f70ce8e75535072
BUNDLE_MANIFEST_SHA256=0161aa91611c22e4897908ce0c912b186bfeab15d857220859c5a77d29086177
IMAGE_REF=alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
IMAGE_LOCAL_ID=sha256:bf8527eb54c3680e728d5b4b383a8ba730d72dae7236fbc8dff97ed6b224a731
DOCKER_ENGINE=29.1.3
DOCKER_COMPOSE=5.5.0
```

Artefacts :

- `docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.json` — preuve
  canonique triée ;
- `docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.transcript.txt` —
  transcript borné, sans chemin absolu ni valeur de clé ;
- `docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.sha256` — hashes du
  harnais, de la fabrique, du JSON et du transcript ;
- `services/rag-engine/scripts/atomic_docker_v2_rehearsal.py` — harnais ;
- `services/rag-engine/scripts/atomic_docker_v2_rehearsal_fixture.py` — fabrique
  V2 paramétrée sans clé par défaut.

La preuve historique V1 du 24 août est conservée byte-identical ; son statut
`UNVERIFIED` n'est pas réécrit rétrospectivement.

## Isolation et nettoyage

- un préflight Docker prouve les trois inventaires générés vides avant la
  première mutation ; les noms ont 128 bits d'aléa et `infra` est refusé ;
- le registre exhaustif des commandes mutantes prouve que
  `--remove-orphans` n'a jamais été utilisé ;
- l'inspection Docker après `up` prouve zéro port publié ;
- la collision réelle est créée dans un projet distinct puis retirée seule ;
- un service témoin étranger reste identique par ID, instant de démarrage,
  projet et service avant/après déploiement et rollback ;
- les inventaires finaux conteneurs, réseaux et volumes sont tous vides pour les
  trois projets générés ; chaque cible de cleanup est enregistrée avant son
  premier `compose up`, les codes retour sont vérifiés et un second passage est
  tenté si le premier laisse un résidu.

Le JSON versionné contient aussi les 38 hashes de membres du bundle, l'identité
et l'état `healthy` observés pour les quatre services, le code retour du rollback
et son inventaire Docker vide.

## Limites honnêtes

Cette preuve exerce le mécanisme V2 avec une fixture synthétique réelle et une
image locale immuable. Elle ne remplace ni les futures images GHCR de production,
ni le vrai `AuthorizationSet` du corpus final, ni la signature offline de
readiness, ni le `FINAL CUTOVER GO`. Aucune base de données ou service de
production n'a été muté par ce lot.
