# LOT 1c — l'inventaire de modèle doit décrire l'artefact entier

> Bloquant absolu. `main` portait un contrat de release qu'aucun modèle d'embedding
> valide ne pouvait satisfaire.

## Le défaut

`_model_inventory` (`services/rag-pedago/scripts/build_production_profile_release.py`)
énumérait l'instantané du modèle avec `snapshot.iterdir()` — **non récursif** — et
inscrivait `path.name` — **le nom de base, pas le chemin relatif**.

Un artefact `sentence-transformers` porte son mode de pooling dans
`1_Pooling/config.json`. Ce fichier fixe `pooling_mode_mean_tokens: true` : **il
détermine l'espace vectoriel**. Il était omis de l'inventaire scellé.

Le vérificateur d'exécution (`services/rag-engine/src/ingestor/model_artifact.py:150`)
exige une couverture exacte : `set(checksums) != expected_files` → refus. D'où une
alternative sans troisième terme :

| artefact | `verify_embedding_artifact` | `SentenceTransformer(...)` |
|---|---|---|
| réel, 12 fichiers, `1_Pooling` présent | **REFUSÉ** `EMBEDDING_MODEL_ARTIFACT_INVALID` | RÉUSSI, 1024 dim. |
| réduit aux 11 entrées inventoriées par `main` | ACCEPTÉ | **ÉCHEC** `TypeError: Pooling.__init__()` |

Les deux branches ont été **exécutées**, pas déduites, sur des artefacts construits
par liens durs sur les poids réels.

## Identification du générateur, par reproduction

Le générateur d'origine, appliqué aux deux instantanés propres, reproduit **à
l'octet près** les inventaires committés sur `ffc1bae` :

```
EMBEDDING  e15ab71babe2f392…  = HEAD   (omet 1_Pooling/config.json)
RERANKER   d7c1b418087e10bb…  = HEAD   (n'omet rien — aucun sous-répertoire)
```

Le reranker est sain **parce qu'il est plat**, non parce que le générateur était
correct. C'est un test que l'hypothèse « énumération non récursive » pouvait
échouer, et qu'elle a passé.

## La correction

Le défaut est au générateur, pas dans le fichier produit. Corriger la ligne
manquante à la main aurait reproduit le défaut au prochain artefact à
sous-répertoire.

- énumération `rglob` récursive, chemins **relatifs à la racine** en POSIX ;
- refus d'un instantané portant déjà `manifest.json` ou `SHA256SUMS` — ce sont des
  **produits**, jamais des entrées ; les accepter fabriquait une ligne
  `manifest.json` en double, donc un inventaire que le vérificateur refuse toujours,
  sans que rien ne le signale à la production. Défaut observé en mesurant ;
- refus de tout lien symbolique — le vérificateur d'exécution les refuse déjà, et
  un inventaire qui en accepte scelle un artefact invérifiable ;
- la garde préexistante « pas de poids, pas d'inventaire » est conservée.

## L'épreuve

Le générateur **corrigé**, appliqué aux mêmes instantanés :

```
EMBEDDING  58ad18dbb0a154c5…   ← exactement l'empreinte que la PRODUCTION porte
                                  dans RAG_EMBEDDING_MODEL_INVENTORY_SHA256
RERANKER   d7c1b418087e10bb…   ← inchangée
```

L'empreinte `58ad18db…` avait été obtenue autrement, à la main, hors dépôt. Le
générateur corrigé la retrouve **par construction**. Deux chemins indépendants
convergent sur le même octet : c'est la vérification, et elle ne pouvait pas
réussir par hasard.

Le reranker est inchangé — la correction n'a pas d'effet de bord sur un artefact
plat.

## Tests

Huit tests sur `_model_inventory` (`tests/test_build_production_profile_release.py`).
Trois passaient déjà (déterminisme, concordance empreinte/chemin, garde des poids) :
ils prouvent que la correction ne les perd pas. Cinq échouaient :

```
RED   5 failed, 3 passed
GREEN 8 passed
```

## Qualité

```
ruff   All checks passed
mypy   Success: no issues found in 1 source file
```

Cinq échecs **préexistants** dans ce même fichier de tests
(`registered_release`, `aggregate_covers`, `every_authority`,
`authority_binding_mutation`, `preflight_proves`). Antériorité prouvée : le
générateur d'origine remis en place, les cinq échouent à l'identique. Leur cause
est l'état non committé des données de release (11 sujets dans l'arbre de travail,
18 dans `ffc1bae`), sans rapport avec ce lot.

## Escalade — ce que ce lot ne fait pas

**Les inventaires scellés du dépôt ne sont pas régénérés par ce lot.** L'empreinte
`e15ab71b…` est portée par **20 fichiers de `ffc1bae`** — 18 manifests de sujets,
`authority_bindings.json`, l'agrégat — à deux occurrences chacun. La corriger
exige un rescellement de la chaîne, gouverné par les règles du LOT 0
(motif obligatoire, pas de rescellement partiel, ré-attestation par re-production).

Et cette régénération se heurte à un fait hors périmètre : **l'arbre de travail
porte une release de 11 sujets, `ffc1bae` en porte 18**, avec 7 suppressions et
3 ajouts non committés. Les 11 sujets correspondent exactement aux 11 collections
peuplées en base. Ce n'est pas un correctif de `ffc1bae`, c'est une autre
génération de release, et arbitrer laquelle fait foi n'appartient pas à ce lot.

Conformément à `AGENTS.md` § Escalade, le lot s'arrête ici et le signale.
