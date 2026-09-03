# Procédure — rescelller une autorité pendant que le service tourne

> Écrite après l'incident du 2026-08-30 : un rescellement autorisé, tracé et motivé a
> ajouté une cause de panne à un service en fonctionnement, parce que personne n'avait
> demandé si le répertoire rescellé était monté.

## Pourquoi cette procédure existe

`services/rag-pedago/data/releases/prerentree_2026_2027` est monté en bind sur `/app/release`,
et `_configured_release_registry()` **relit le fichier à chaque appel**, sans cache.
`RAG_RELEASE_REGISTRY_SHA256` vit dans `infra/.env`, non versionné, hors de portée de
l'outil de rescellement.

Conséquence mesurée : rescelller met le fichier et l'ancre en désaccord **à la sonde
suivante**, soit quinze secondes. Il n'y a pas de fenêtre.

## Avant tout — les deux questions

1. **Qu'est-ce que ce geste détruit ?** Avant « est-ce que ça marche ». Un redémarrage
   détruit un journal de conteneur ; une recréation sans `image:` détruit l'image.
2. **Ce répertoire est-il monté ?** La table des quatre montages est dans
   `docs/reports/lot_1c_table_des_montages.md`. Elle est à relire, pas à se rappeler.

## La procédure

### 0. Préserver ce qui n'existe qu'en un exemplaire

```bash
docker logs <conteneur> -t                > <sauvegarde>/<conteneur>.log
docker inspect <conteneur>                > <sauvegarde>/<conteneur>.inspect.json   # PUIS EXPURGER
docker tag <image_id> <nom>:<date>-<court>
docker save <image_id> -o <sauvegarde>/image-<court>.tar
```

**Vérifier l'archive par identité, pas par existence** : l'identifiant d'une image est le
sha256 de sa configuration. Extraire `manifest.json`, hacher le blob de configuration, et
comparer à l'identifiant. Puis vérifier chaque couche contre le nom de son blob.

L'`inspect` contient les variables d'environnement **en clair** : expurger avant de le
déposer où que ce soit.

### 1. Arrêter le service

Le fichier étant relu à chaque appel, tout rescellement pendant que le service tourne
produit une incohérence immédiate.

### 2. Rescelller par l'outil, jamais à la main

```bash
NEXUS_REPO_ROOT=<racine> python3 services/rag-pedago/scripts/reseal_release_authorities.py --check
NEXUS_REPO_ROOT=<racine> python3 …/reseal_release_authorities.py --qui-atteste <fichier>
NEXUS_REPO_ROOT=<racine> python3 …/reseal_release_authorities.py --reseal --motif 'AUTORITE=…' --preuve '…'
```

`--qui-atteste` **avant** toute écriture. L'outil refuse un motif générique, une autorité
introuvable, une chaîne hors de sa portée. Ces refus sont la procédure, pas des obstacles.

### 3. Aligner les ancres d'environnement

Le rescellement change l'empreinte du registre. Relever la nouvelle valeur et la porter
dans `infra/.env` :

```bash
sha256sum <racine>/services/rag-pedago/data/releases/<annee>/release-registry.json
# puis RAG_RELEASE_REGISTRY_SHA256=<nouvelle valeur> dans infra/.env
```

**Ces ancres ne sont pas versionnées et l'outil ne les connaît pas.** C'est le maillon que
l'outil ne peut pas tenir, et donc celui que la procédure doit tenir.

### 4. Relancer

`docker restart` **ne relit pas** `infra/.env` : l'environnement est figé à la création du
conteneur. Il faut une recréation.

Si le service ne déclare pas d'`image:` mais un `build:`, **une recréation reconstruit** et
remplace l'image en service. L'archive de l'étape 0 rend le geste réversible :

```bash
docker load -i <sauvegarde>/image-<court>.tar
```

### 5. Vérifier

```bash
curl -s -o /dev/null -w '%{http_code}' http://<hôte>:<port>/health     # attendu 200
```

Si 503, décomposer les contrôles — `/health` refuse sans motif — en important le module
dans le conteneur. **Attention : `docker exec python -c "import api_v2"` démarre un
NOUVEAU processus** ; l'état de module qu'on y lit n'est pas celui du service. Seuls les
contrôles qui relisent des fichiers ou l'environnement y sont significatifs.

## Ce que la procédure ne couvre pas

- La cause d'un 503 antérieur au geste. La rétention des sondes Docker est de cinq entrées.
- Les trois autres montages. Rescelller n'est qu'un cas ; toute écriture sous un montage
  relu à l'exécution appelle les mêmes étapes.
