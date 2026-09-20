# LOT_GO_LIVE_FINAL_CH7A_RUNTIME_WORKER_IMAGE_BINDING_GUARD

- **Branche** : `go-live/ch7a-runtime-worker-image-binding-guard`
- **Base** : `3abcec67` (#239, ancre de répétition)
- **Décision attendue** : `GO_LIVE_CH7A_RUNTIME_WORKER_IMAGE_BINDING_GUARD_PR_OPEN`
- **S'appuie sur** : ADR-0057

> Ce lot **n'autorise aucune image** et **n'exécute rien**. Il ajoute une
> garde. L'autorisation d'un nouveau digest est le lot CH7B, qui viendra
> **après** que cette garde soit fusionnée — sans quoi l'image construite ne
> contiendrait pas ce qu'elle est censée prouver.

## L'écart que ce lot ferme

Le manifeste signé porte `worker_image`. Jusqu'ici, **rien à l'exécution ne
comparait l'image réellement en cours à cette déclaration** : la signature
couvrait une intention, pas un fait. Un conteneur lancé depuis une autre
image passait le gate sans être détecté.

L'écart a été trouvé en situation, pas en relecture : lors de la tentative
d'installation de la readiness sur staging, l'exécution s'est arrêtée sur
`ModuleNotFoundError` — l'absence d'un module, pas une garde. Si le module
avait existé dans cette image plus ancienne, rien n'aurait signalé qu'elle
n'était pas celle que la signature couvre.

## La garde

`require_running_image_matches_manifest(manifest, *, actual=None)` refuse :

| Cas | Refus |
|---|---|
| `NEXUS_ACTUAL_WORKER_IMAGE` absente | « is not configured » — aucun repli |
| variable vide ou faite d'espaces | « set but blank » — jamais traitée comme absente |
| référence sans digest (`:latest`, `:sha-…`, nom nu) | « carries no digest » |
| digest différent de celui signé | « the signature covers that image and no other » |
| même digest, **autre dépôt** | refusé — le dépôt fait partie de l'identité |
| manifeste sans `worker_image` | « names no worker_image » |
| manifeste dont l'image n'est pas épinglée | « not pinned » |

Seule l'égalité exacte, après `strip()`, est acceptée.

### Pourquoi l'identité vient de l'hôte

Un processus ne peut pas lire de façon fiable le digest de l'image dont il
est issu : `/proc` ne le porte pas, et le lui demander reviendrait à demander
au suspect de décliner son identité. L'inspection se fait donc sur l'hôte —
`docker inspect --format '{{index .RepoDigests 0}}'` — et le résultat est
injecté. Le runbook impose cet ordre : inspecter d'abord, injecter ensuite,
jamais une valeur écrite à la main.

`NEXUS_ACTUAL_WORKER_IMAGE` n'a délibérément pas sa place dans
`readiness.env` : ce fichier porte des faits stables, celle-ci est une
constatation faite juste avant l'exécution. L'y figer la rendrait fausse dès
le prochain changement d'image.

### Où la garde s'exécute

Immédiatement après le gate de readiness, **avant** l'ouverture de la moindre
connexion et de la moindre écriture. Une réponse négative rend tout le reste
sans objet.

## Preuves

### Les treize épreuves demandées

| # | Exigence | Test |
|---|---|---|
| 1 | variable absente → refus | `test_ch7a_1_…`, `test_ch7a_1bis_…vide…` |
| 2 | tag seul → refus | `test_ch7a_2_…` (4 formes paramétrées) |
| 3 | digest différent → refus | `test_ch7a_3_…`, `test_ch7a_3bis_…autre_depot` |
| 4 | image signée → acceptée | `test_ch7a_4_…`, `…4bis_espaces`, `…4ter_via_env` |
| 5 | ancien digest CH6 refusé | `test_ch7a_5_…` — avec le vrai digest `2ce7533d…` |
| 6 | `worker_image` absent ou invalide → refus | `test_ch7a_6_…`, `…6bis_…`, `…6ter_contrat` |
| 7 | garde avant toute écriture | `test_ch7a_7_…` (aucune connexion ouverte) et `…7bis_ordre_source` |
| 8 | production readiness inchangée | `test_ch7a_8_…` (trois empreintes) |
| 9 | `enforce_staging_readiness_gate` obligatoire | `test_ch7a_9_…` — et appelé **avant** la garde |
| 10–13 | ni staging, ni DB produit, ni switch, ni Worker B | `test_ch7a_10_a_13_…`, `test_ch7a_11_…` |

L'épreuve 7 ne se contente pas de lire l'ordre du code : elle remplace
`psycopg.connect` par une fonction qui échoue si elle est appelée, lance le
CLI avec une image discordante, et vérifie qu'aucune connexion n'a été
tentée.

Les épreuves 10 à 13 nomment chaque interdiction par le motif qui la
caractérise vraiment. Une première rédaction cherchait `current` pour prouver
l'absence de basculement de lien : elle échouait sur `current_user`, le rôle
PostgreSQL attesté au démarrage, qui n'a rien à voir. Le motif juste est
`os.symlink`, `ln -s`, `/current`.

```
services/rag-engine  pytest tests/test_staging_readiness_gate.py    76 passed
services/rag-engine  ruff check .                                   All checks passed!
services/rag-engine  mypy src                                       143 source files
```

## Ce lot n'autorise rien

L'autorisation staging continue d'épingler le digest de CH6. Ce lot ne la
touche pas. Tant que CH7B n'a pas eu lieu, la seule image autorisée reste
celle qui ne peut pas exécuter le point d'entrée — et la garde ajoutée ici
refuserait de toute façon toute autre image que celle que le manifeste signe.

## La suite, dans l'ordre

1. CH7A fusionné ;
2. `production-image-provenance.yml` relancé sur le `main` qui le contient ;
3. **CH7B** : amendement de l'autorisation au nouveau digest, avec la preuve
   que l'image porte CQ, CR et cette garde ;
4. nouveau manifeste signé — l'actuel (`7bcf8129…`) nomme l'ancien
   `merge_sha` et l'ancienne image, il ne couvre pas la nouvelle ;
5. installation, vérification, exécution.
