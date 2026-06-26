# ADR-0005 — Architecture d'acquisition multi-agents

- **Statut** : Accepté
- **Date** : 2026-06-26
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation), ADR-0004 (ingestion agentique)

## Contexte

L'acquisition de contenu couvre ~420 notions sur 19 taxonomies (11 matières × 4 niveaux). Un script monolithique (`pilot_fetch.py`) ne scale pas : il mélange les responsabilités (découverte de sources, fetch, qualité, staging) et ne priorise pas selon les rapports de correspondance du Lot 9.

## Décision

### Architecture à 3 niveaux

1. **OrchestratorAgent** : répartit le travail entre LevelAgents, agrège les rapports, applique la gouvernance globale. Ne fetch pas lui-même.

2. **LevelAgent** (un par niveau : 3e, 2de, 1re, Tle) : découvre les taxonomies de son niveau par glob, instancie un SubjectAgent par matière/statut, orchestre l'exécution séquentiellement pour respecter le rate limit global.

3. **SubjectAgent** (un par matière/niveau/statut) : connaît sa `TaxonomySpec`, ses sources libres (registre), et la correspondance BO (Lot 9). Priorise les notions `not_found`/`found_partial` du rapport de correspondance.

### Gouvernance

- Tous les agents vérifient `data_staging_allowed` avant écriture.
- `ingestion_allowed` reste le verrou humain : aucun agent n'écrit au corpus.
- Les agents proposent en staging, l'import est un acte séparé (post-revue).

### Registre de sources

Chaque matière dispose d'un registre de sources libres (URL, licence, robots.txt) consultable par le SubjectAgent. Pas de source sans licence vérifiée.

## Conséquences

- Scalabilité : ajouter une matière = ajouter un fichier taxonomie + une entrée registre.
- Priorisation : les notions non couvertes par le BO sont traitées en premier.
- Traçabilité : rapport hiérarchique (niveau → matière → notion → sources).
