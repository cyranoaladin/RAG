# ADR-0050 — Extension contractuelle additive de l'enum Niveau (Sixième et Cinquième)

- **Statut** : **Accepté**
- **Date** : 2026-08-27
- **Décideur** : Nexus Réussite (opérateur)
- **S'appuie sur** : ADR-0002, ADR-0015, ADR-0040, ADR-0048

## Contexte

Conformément à l'ADR-0048 (Périmètre produit du GO-LIVE : collège, lycée général, STMG), le modèle structurel de la plateforme doit couvrir l'intégralité du cycle collège (6e, 5e, 4e, 3e).
L'enum canonique `Niveau` dans `nexus-contracts` contenait `quatrieme`, `troisieme`, `seconde`, `premiere`, `terminale`, ainsi que les alias de cycles/voies, mais ne supportait pas explicitement les niveaux `sixieme` (Cycle 3) et `cinquieme` (Cycle 4).

Pour préserver le principe selon lequel le cycle ne remplace jamais le niveau pour le routage pédagogique et éviter tout fallback incorrect (ex: `cycle4` ou alias non canoniques), l'enum `Niveau` doit être étendu de manière additive.

## Décision

1. Ajouter les valeurs `sixieme = "sixieme"` et `cinquieme = "cinquieme"` à l'enum canonique `Niveau` dans `packages/contracts/src/nexus_contracts/document.py`.
2. Incrémenter la version SemVer mineure de `nexus-contracts` à `0.15.0` (évolution rétrocompatible strictement additive).
3. Mettre à jour les schémas et validateurs associés pour accepter `sixieme` et `cinquieme` comme niveaux valides dans les profils élèves et les portées curriculaires.

## Limites et activation

Cette extension est purement structurelle au niveau des contrats. Elle n'active aucune collection physique ni ne modifie les verrous de gouvernance de serving tant que des autorisations de release dédiées et des corpus vérifiés ne sont pas scellés.
