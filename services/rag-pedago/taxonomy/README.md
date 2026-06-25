# Taxonomie — Convention et statut

## Convention de nommage

```
taxonomy/{matiere}/{niveau}_{statut}.yml
```

## Validation

```bash
python scripts/validate_taxonomy.py
```

Chaque fichier est validé par `TaxonomySpec` (Pydantic). Un fichier non validé ne doit pas exister.

## Statut des fichiers (19 fichiers, 246 notions, 173 subnotions)

- **Validé BO** : maths terminale spé (64), maths première (23), NSI terminale (36), philo terminale (26)
- **PREMIER JET** : 15 fichiers à réviser par expert matière

## Références BO

| Programme | Référence |
|---|---|
| Lycée général (2019) | BOEN spécial n°1 du 22/01/2019 |
| Terminale spécialités (2019) | BOEN spécial n°8 du 25/07/2019 |
| Collège (2018) | BOEN 2018 |

## Contribuer

1. Créer le fichier YAML dans `taxonomy/{matiere}/`
2. Respecter le schéma `TaxonomySpec` (`schema/taxonomy.py`)
3. Ajouter `# PREMIER JET` en tête si non vérifié par expert
4. Lancer `python scripts/validate_taxonomy.py`
