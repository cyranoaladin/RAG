# Manifest coverage

Le coverage report compare les métadonnées déclarées dans des manifests JSONL locaux avec des taxonomies pédagogiques contrôlées. Il aide à décider si un lot couvre suffisamment les matières, niveaux, types documentaires, candidats et notions avant toute ingestion documentaire.

## Différence avec readiness

Le readiness report répond à la question : le lot est-il importable sans anomalie bloquante ?

Le coverage report répond à une question différente : le lot couvre-t-il les notions et axes pédagogiques attendus ? Un lot peut être techniquement prêt mais pédagogiquement incomplet.

## Taxonomies

Les taxonomies sont chargées depuis des YAML validés avec `TaxonomySpec`. Les notions connues incluent les `id` des notions et leurs `subnotions`.

Commande exemple :

```bash
python -m rag_pedago.imports.coverage_report data/fixtures/manifests/batch_001 --batch-id batch-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml
```

## Notions connues et inconnues

Les notions déclarées dans les manifests sont comparées aux notions connues des taxonomies chargées :

- `notions_known` : notions déclarées et reconnues ;
- `notions_unknown` : notions déclarées mais absentes des taxonomies ;
- `missing_priority_notions` : notions prioritaires attendues mais absentes des manifests.

## Notions prioritaires

Les notions prioritaires peuvent être passées avec `--priority-notion`. Elles permettent de vérifier une tranche pédagogique ciblée, par exemple terminale spécialité mathématiques : suites, récurrence, probabilités conditionnelles, loi binomiale ou intégrales.

## Statuts

- `coverage_ok` : au moins un document valide, des notions déclarées, aucune notion inconnue, aucune priorité manquante ;
- `coverage_partial` : notions inconnues ou priorités manquantes ;
- `coverage_insufficient` : aucun document valide ou aucune notion déclarée.

## Garanties

- aucun `source_uri` n'est ouvert ;
- aucun appel réseau n'est effectué ;
- aucune ingestion documentaire n'est lancée ;
- aucun PDF n'est lu ou parsé ;
- aucune connexion Qdrant ou PostgreSQL n'est utilisée.

## Limites

Ce rapport évalue uniquement les métadonnées déclarées. Il ne garantit pas que les documents sources existent, que leur contenu correspond aux notions déclarées ou que la couverture est suffisante pour un usage élève réel.
