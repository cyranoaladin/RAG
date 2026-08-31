# LOT 1c — table des quatre montages du service servi

> Établie après qu'un rescellement a écrit dans un répertoire monté et ajouté une cause de
> panne. Un avertissement particulier sur `configs/` avait été donné ; il en fallait une
> table.

| source hôte | cible | mode | relu par le service |
|---|---|---|---|
| `services/rag-pedago/data/releases/prerentree_2026_2027` | `/app/release` | bind, RW=false | **à chaque appel** |
| `services/rag-engine/configs` | `/app/configs` | bind, RW=false | mise en cache après premier chargement |
| `~/rag-model-artifacts/e5-large-…-materialise` | `/models/e5-large` | bind, RW=false | **stat à chaque sonde** (ctime, taille) |
| `~/rag-model-artifacts/ms-marco-…` | `/models/reranker` | bind, RW=false | **stat à chaque sonde** |

**Les quatre sont des montages bind sur l'arbre de travail.** Aucun n'est une copie figée
identifiée par empreinte. `RW=false` signifie que le *conteneur* ne peut pas écrire ; il
n'empêche nullement l'hôte de modifier la source, et le conteneur lit alors la nouvelle
valeur.

## Ce qui est relu, et comment on le sait

**`/app/release` — relu à chaque appel.** `_configured_release_registry()` lit
`RAG_RELEASE_REGISTRY_PATH` et charge le fichier sans décorateur de cache. **Prouvé par
exécution :** le service a répondu 200 à `/health` pendant 3 000 sondes avec l'empreinte
`cd72fca6`, puis 503 dès que le fichier a valu `c9a844d4`. S'il y avait cache de démarrage,
le contrôle passerait encore.

**`/models/*` — relus par `stat` à chaque sonde.** `model_artifact_attestation_ready`
recompare les états mémorisés au démarrage : chemins, tailles, **et `ctime_ns`**. Les poids
ne sont pas rehachés, mais les métadonnées sont relues. Créer un lien dur vers un fichier du
montage, geste qui ne modifie pas un octet, change son `ctime` et **suffit à faire diverger
l'attestation**.

**`/app/configs` — chargé puis mis en cache.** Une modification n'est donc pas immédiate,
mais elle est effective au redémarrage suivant, sans reconstruction d'image.

## La règle qui manquait

Trois des quatre montages sont relus à l'exécution. **Toute écriture dans l'arbre de travail
sous l'un de ces chemins est une modification de la production**, immédiate ou différée au
redémarrage.

Avant d'écrire dans l'un de ces répertoires : arrêter le service, ou accepter et prévoir
l'effet. La procédure de rescellement en production le formalise.

## Ce que le LOT 1c doit corriger

1. **Les quatre montages doivent être des copies figées**, identifiées par empreinte et
   vérifiées au démarrage — pas des vues sur un répertoire de travail.
2. **L'attestation des poids doit porter sur le contenu, pas sur les métadonnées.** Un
   `ctime` change à une copie, un `rsync`, une restauration de sauvegarde, un lien dur —
   tous gestes qui préservent le contenu à l'octet près. Une attestation qui rougit après
   une restauration empêchera la reprise le jour où elle sera nécessaire.
