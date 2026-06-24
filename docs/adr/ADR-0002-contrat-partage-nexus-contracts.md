# ADR-0002 — Contrat partagé `nexus-contracts` versionné

- **Statut** : Accepté
- **Date** : 2026-06-24
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation plan de contrôle / plan de données / cockpit)
- **ADR liés** : ADR-0003 (tenants), ADR-0004 (ingestion agentique)

## Contexte

ADR-0001 fait du contrat `RetrievalRequest → RetrievalResponse` la couture unique entre le cockpit et `rag-engine`. Ce contrat existait déjà comme code interne à `rag-pedago` (`schema/retrieval.py`, `schema/student_profile.py`, `schema/document.py`). Le Lot 0 l'a extrait dans un package Python `nexus-contracts` (v0.1.0), `rag-pedago` le consommant désormais via ré-export. Il faut figer le statut, le versionnement et les garanties de ce package, car trois services vont en dépendre et toute dérive silencieuse casserait la couture.

## Décision

`packages/contracts/` (`nexus-contracts`) est la **source de vérité unique** du contrat d'échange entre services. Règles :

1. **Périmètre.** Le package contient exclusivement les modèles d'interface : `RetrievalRequest`, `RetrievalNeed`, `RetrievalOptions`, `RetrievalResult`, `RetrievalResponse`, `Citation`, `StudentProfile` et les enums associées (niveaux, voies, statuts, candidats, types de documents). Aucune logique métier, aucun accès I/O, aucune dépendance vers un service.

2. **Source de vérité.** Les définitions vivent dans `nexus-contracts`. Aucun service ne redéfinit ces types localement ; `rag-pedago` les ré-exporte par compatibilité, `rag-engine` et `cockpit` les importent. Modifier une copie locale est interdit.

3. **Versionnement SemVer.**
   - *patch* : correction sans changement d'interface ;
   - *mineur* : ajout rétro-compatible (champ optionnel, nouvelle valeur d'enum non requise) ;
   - *majeur* : changement cassant (champ requis, suppression, renommage, resserrement de validation).
   Tout changement *majeur* exige un ADR dédié et une montée de version coordonnée des trois services.

4. **Tests de contrat.** La CI (locale tant qu'Actions est indisponible) vérifie : l'import du package, la validation des modèles, et les golden queries de `rag-pedago/tests/golden_queries/`. Un changement qui casse une golden query sans bump majeur + ADR échoue.

5. **Distribution monorepo.** Le package s'installe en éditable (`pip install -e packages/contracts`), orchestré par les cibles `make install` des services. La dépendance n'est pas déclarée en runtime tant que le package n'est pas publié sur un index. Industrialisation (uv workspace ou index privé) renvoyée à la Phase 6.

## Conséquences

### Positives
- Une seule définition d'interface ; impossible de diverger par inadvertance entre services.
- Les changements cassants deviennent visibles et tracés (bump majeur + ADR).
- Le cockpit et `rag-engine` se développent contre une cible stable.

### Négatives
- Discipline de versionnement à tenir manuellement tant que la distribution n'est pas industrialisée.
- L'installation éditable impose un ordre (`contracts` avant les services), absorbé par `make install`.

### Risques et mitigations
- *Dérive d'une copie locale* → interdiction explicite + ré-export imposé + revue.
- *Changement cassant non détecté* → golden queries en CI locale, bloquantes.

## Suites
- ADR-0003 : tenants et isolation par niveau (les filtres dérivent de `StudentProfile`).
- Industrialiser la distribution du package en Phase 6.
EOF
