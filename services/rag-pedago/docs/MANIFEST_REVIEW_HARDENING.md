# Manifest review hardening

Le lot 12.5 durcit la chaîne review package -> décision humaine -> import
contrôlé. L'objectif est d'empêcher toute modification silencieuse entre la
revue et l'import.

## JSON canonique

Les hashes de package utilisent un JSON canonique :

- `model_dump(mode="json")` pour les modèles Pydantic ;
- tri des clés ;
- séparateurs JSON déterministes ;
- encodage UTF-8.

Deux payloads identiques avec un ordre de clés différent produisent le même
hash. Toute modification de champ produit un hash différent.

## Vérification du review package

Avec `--require-review`, l'import contrôlé exige :

- `--review-decision` ;
- `--review-package`.

Le hash canonique du package chargé doit correspondre au
`review_package_sha256` stocké dans la décision.

## Vérification des manifests

L'import recalcule les SHA-256 des manifests JSONL. Il refuse :

- manifest modifié ;
- manifest supprimé ;
- manifest ajouté.

L'ordre de lecture ne change pas la décision, car les chemins sont triés.

## Vérification taxonomies et référentiel officiel

L'import recalcule :

- `official_reference_sha256` sur `data/reference/` ;
- `taxonomy_sha256` pour chaque taxonomie utilisée.

Tout écart bloque avant écriture ledger.

## Reviewer policy

Par défaut, un reviewer non vide est accepté. En politique stricte :

- `require_known_reviewer=true` ;
- le reviewer doit appartenir à `allowed_reviewers`.

La CLI d'approbation expose :

```bash
--allowed-reviewer "Nexus Direction" --require-known-reviewer
```

## Registry

Chaque décision approuvée ou rejetée ajoute une ligne JSONL dans :

```text
data/reviews/review_registry.jsonl
```

Le registry est append-only dans le scénario normal et ignoré par Git.

## Limites

Ces garanties valident les manifests, rapports, taxonomies et référentiel
officiel vus au moment de la revue. Elles ne valident toujours pas le contenu
réel d'un document pédagogique, PDF, annale, corrigé ou barème.
