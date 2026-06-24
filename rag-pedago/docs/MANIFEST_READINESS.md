# Manifest readiness

Le readiness report sert de décision humaine pré-ingestion pour un dossier de manifests JSONL locaux. Il ne remplace pas l'import réel : il exécute une analyse en dry-run, applique une politique qualité, puis produit un rapport Markdown lisible et un JSON exploitable.

## Différence avec le dry-run

Le dry-run de l'import répertoire vérifie les lignes, compte les documents et détecte les doublons. Le readiness report ajoute une décision opérationnelle :

- `ready` : aucun blocage ni warning ;
- `ready_with_warnings` : import contrôlé possible seulement après validation humaine ;
- `blocked` : les manifests doivent être corrigés avant tout import réel.

## Différence avec l'import réel

Le readiness report ne crée aucun run, n'écrit aucun document, n'écrit aucun état et n'enregistre aucune erreur dans le ledger. Il écrit uniquement des rapports dans `data/reports/` ou dans le dossier passé via `--output-dir`.

## Actions recommandées

Les issues qualité sont converties en actions courtes et dédupliquées : correction de lignes invalides, fusion de doublons, choix d'une version canonique, clarification des droits, ajout de `programme_version`, ajout du niveau ou de l'épreuve.

## Garanties

- aucun `source_uri` n'est ouvert ;
- aucun appel réseau n'est effectué ;
- aucune ingestion documentaire n'est lancée ;
- aucun PDF n'est lu ou parsé ;
- aucune connexion Qdrant ou PostgreSQL n'est utilisée.

## Commande

```bash
python -m rag_pedago.imports.readiness_report data/fixtures/manifests/batch_001 --batch-id batch-001
```

Options :

- `--strict` : bloque aussi les droits inconnus et applique la politique stricte ;
- `--allow-unknown-rights` : autorise explicitement les droits inconnus en warning ;
- `--output-dir` : choisit le dossier de sortie des rapports.

## Limites

Ce lot ne valide que des métadonnées de manifests. Il ne prouve pas que les fichiers sources existent, sont lisibles ou sont conformes. Ces contrôles appartiendront à un futur lot d'ingestion contrôlée, avec règles explicites et sans lecture implicite des sources pendant l'étape readiness.
