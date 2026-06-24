# AGENTS.md — Nexus RAG Pedago

Ce dépôt est le socle local isolé du futur RAG pédagogique Nexus Réussite. Il ne
dépend pas du dépôt historique `rag-local` et ne doit pas toucher aux services de
production.

## Règles d'or

- Travailler uniquement dans `/home/alaeddine/Bureau/RAG/rag-pedago`.
- Lire le code et les contrats avant de modifier.
- Ne modifier qu'un lot atomique à la fois.
- Écrire les tests avant le code pour tout comportement nouveau.
- Produire un rapport Codex dans `data/reports/`.
- Ne jamais masquer un échec de test ou de diagnostic.

## Ordre de travail obligatoire

1. Lire `README.md`.
2. Lire `AGENTS.md`.
3. Lire `docs/WORKFLOWS.md`.
4. Lancer `make doctor`.
5. Lancer les tests ciblés du lot.
6. Modifier seulement les fichiers nécessaires.
7. Lancer `make test`.
8. Lancer les commandes finales demandées.
9. Vérifier `git status --short --branch`.

## Interdictions

- Ne jamais ajouter une lecture de `source_uri` sans lot dédié et validation humaine.
- Ne jamais introduire de dépendance réseau.
- Ne jamais connecter Qdrant ou PostgreSQL avant instruction explicite.
- Ne jamais utiliser un LLM runtime dans ce dépôt sans lot dédié.
- Ne jamais parser de PDF, OCRiser ou lire un document source dans les lots metadata-only.
- Ne jamais copier de secrets, credentials, `.env` réels, dumps ou uploads.
- Ne jamais modifier `/home/alaeddine/Bureau/RAG/rag-local`.
- Ne jamais modifier `/srv/nexusreussite/rag-ui`.
- Ne jamais supprimer un fichier brut de `data/raw/`.
- Ne jamais contourner robots.txt.
- Ne jamais ingérer une ressource sans statut de droit.

## Règles de schéma

- Ne jamais modifier `schema/document.py` sans tâche dédiée explicite.
- Ne jamais dupliquer le schéma documentaire dans un autre module.
- Toute évolution de schéma doit être accompagnée de tests.
- Toute évolution de schéma doit préserver la compatibilité des métadonnées existantes ou documenter une migration.

## Règles de taxonomie

- Ne jamais modifier à la main des taxonomies officielles déjà validées.
- Toute notion inconnue doit aller dans `taxonomy/proposals/` ou équivalent.
- Les taxonomies officielles doivent rester alignées avec les sources institutionnelles.
- Une sortie LLM ne peut pas créer seule une notion officielle.

## Règles d'immuabilité documentaire

- Ne jamais réécrire un document source.
- Ne jamais modifier un fichier brut dans `data/raw/`.
- Les fichiers normalisés doivent être dérivés des sources et reproductibles.
- Toute correction manuelle doit être tracée séparément et justifiée.

## Règles d'idempotence et de ledger

- Ne jamais retraiter un document, un chunk ou un embedding si le hash d'entrée n'a pas changé.
- Ne jamais créer de doublon vectoriel pour un même `chunk_id`.
- Toute étape d'ingestion doit être reprenable après interruption.
- Le ledger est la source de vérité de l'état du pipeline.

## Règles de scraping

- Ne jamais lancer de scraping massif non limité.
- Toujours respecter `robots.txt` lorsque la source l'exige.
- Toujours appliquer un rate limiting.
- Ne jamais contourner une authentification ou un accès restreint.
- Toute source distante doit avoir une politique de droit et de provenance.

## Règles de droits et visibilité

- Ne jamais mélanger ressources propriétaires Nexus et ressources publiques sans métadonnée `rights` et `visibility`.
- Ne jamais exposer une ressource propriétaire dans un contexte public.
- Un document avec `rights=unknown` doit être bloqué par le retrieval tant qu'il n'est pas qualifié.
- Toute réponse future du RAG doit pouvoir citer la provenance du chunk utilisé.

## Règles LLM

- Ne jamais utiliser un LLM comme source de vérité finale pour classifier une ressource.
- Le LLM peut aider à enrichir des champs ambigus, mais sa sortie doit être validée contre les taxonomies et contrats.
- Toute décision LLM critique doit être traçable.

## Livraison de module

Chaque module livré doit avoir, lorsque pertinent :

- tests unitaires ;
- tests d'intégration si dépendance externe ;
- logs structurés ;
- gestion d'erreur ;
- reprise après interruption ;
- rapport de sortie ;
- documentation minimale.

## Commits

- Committer seulement quand l'utilisateur le demande.
- Avant commit : `make doctor`, `make test`, commandes finales du lot.
- Ne pas inclure de runtime ignoré : ledger SQLite, review registry, rapports runtime.
- Garder les rapports Codex versionnés.

## Tests

- Tests unitaires dans `tests/unit/`.
- Tests de scaffold dans `tests/`.
- Contrats projet dans `tests/unit/test_project_contracts.py`.
- Doctor projet dans `tests/unit/test_project_doctor.py`.

## Runtime artifacts

Les artefacts runtime sont ignorés par Git :

- `data/ledger/**` sauf `.gitkeep` ;
- rapports readiness, coverage, gate, controlled import, review package ;
- `data/reviews/review_*.json` ;
- `data/reviews/review_registry.jsonl`.

Les rapports Codex `data/reports/codex_lot_*.md` sont versionnés.

## Créer un nouveau lot

1. Valider et committer le lot précédent si demandé.
2. Écrire les tests rouges du nouveau comportement.
3. Implémenter le minimum.
4. Documenter le comportement.
5. Créer `data/reports/codex_lot_<n>_<slug>.md`.
6. Exécuter les commandes finales.
7. Ne pas committer sans instruction.

## Rapport Codex

Chaque rapport doit contenir :

- objectif ;
- fichiers créés ;
- fichiers modifiés ;
- tests exécutés ;
- résultats ;
- limites volontaires ;
- prochaine étape recommandée.

## Ne pas casser les invariants

Les contrats machine-readable dans `docs/contracts/` décrivent les étapes, les
artefacts et les interdictions. Si un lot change un invariant, il doit modifier
les contrats, les tests et la documentation dans le même changement.
