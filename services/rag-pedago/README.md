# Nexus RAG Pedago

Projet local isolé pour construire le futur RAG pédagogique Nexus Réussite.

Le dépôt sert à préparer un pipeline déterministe, testable, auditable et
reprenable pour des ressources pédagogiques françaises. À ce stade, il ne traite
que des métadonnées déclarées dans des manifests JSONL et des référentiels
contrôlés. Il ne lit pas encore les documents sources.

## Objectif du projet

Construire progressivement un RAG pédagogique local capable, plus tard, de
servir des cockpits élèves personnalisés avec filtrage fort par niveau, matière,
enseignement, épreuve, statut candidat, droits, références officielles et
citations.

La priorité actuelle est la qualité des métadonnées et de la gouvernance avant
ingestion : référentiels officiels, taxonomies, manifests, gate de décision,
revue humaine, import contrôlé et audit SQLite.

## Installation

Le point d'entrée d'installation supporté est `make install` (installe `nexus-contracts` en éditable depuis le monorepo, puis le service) :

```bash
make install   # installe nexus-contracts puis rag-pedago[dev]
```

> `pip install -e ".[dev]"` seul échouera si `nexus-contracts` n'est pas déjà installé.

## Ce que le projet fait actuellement

- valide des schémas Pydantic métier ;
- maintient des taxonomies Maths/NSI et des référentiels officiels ;
- importe des manifests JSONL locaux dans un ledger SQLite ;
- analyse un dossier de manifests en dry-run ;
- applique une politique qualité configurable ;
- produit des rapports readiness, coverage et gate ;
- génère un review package avec hashes ;
- enregistre une approbation ou un rejet humain ;
- exécute un import contrôlé soumis au gate et, si demandé, à la review ;
- audite packages, décisions, tentatives et vérifications dans SQLite.

## Ce que le projet ne fait pas encore

- pas de parsing PDF ;
- pas d'OCR ;
- pas d'ouverture de `source_uri` ;
- pas de lecture de documents pédagogiques réels ;
- pas de scraping ;
- pas d'appel réseau ;
- pas de Qdrant ;
- pas de PostgreSQL ;
- pas d'embeddings ;
- pas de retrieval opérationnel ;
- pas d'appel LLM runtime.

## Architecture logique

```text
Official Reference
→ DocumentMeta
→ Manifest JSONL
→ Quality Policy
→ Readiness
→ Coverage
→ Gate
→ Review Package
→ Approval
→ Controlled Import
→ Audit Ledger
```

Chaque étape actuelle travaille sur des métadonnées et rapports locaux. Les
documents sources restent hors périmètre jusqu'à un lot explicitement dédié.

## Arborescence principale

- `schema/` : modèles Pydantic partagés.
- `rag_pedago/reference/` : chargement, index et resolver du référentiel officiel.
- `taxonomy/` : taxonomies pédagogiques contrôlées.
- `rag_pedago/imports/` : manifests, qualité, readiness, coverage, gate, review et import contrôlé.
- `rag_pedago/ledger/` : SQLite local, migrations, repository et diagnostics.
- `data/reference/` : données institutionnelles structurées.
- `data/fixtures/` : manifests synthétiques de test.
- `data/reports/` : rapports Codex versionnés et rapports runtime ignorés.
- `docs/` : contrats, politiques et guides.
- `tests/` : tests unitaires et contrats projet.

## Workflows validés

- Batch problématique `batch_001` : gate bloqué.
- Batch mismatch officiel : gate bloqué avec explications de compatibilité.
- Batch officiel clean : gate prêt, review package prêt, approval possible.
- Import contrôlé avec review obligatoire : import metadata-only possible.
- Audit ledger : package, décision, tentative et vérifications requêtables.

Voir [docs/WORKFLOWS.md](docs/WORKFLOWS.md).

## Commandes principales

```bash
make doctor
make test
make project-doctor
make ledger-init
make ledger-doctor
make manifest-readiness
make manifest-coverage
make manifest-gate
make review-package-clean-audited
python -m rag_pedago.imports.controlled_import_cli --help
```

## Invariants de sécurité

- Un fichier `source_uri` ne doit jamais être ouvert dans les étapes actuelles.
- Aucun appel réseau ne doit être introduit.
- Aucune connexion Qdrant ou PostgreSQL ne doit être ajoutée sans lot dédié.
- Aucun LLM runtime ne doit être utilisé sans validation explicite.
- Les secrets, `.env` réels, credentials et uploads historiques sont interdits.
- Le service `services/rag-engine/` (ex `rag-local`) n'est pas modifié par `rag-pedago`.
- Les chemins de production `/srv/nexusreussite/rag-ui` ne doivent pas être modifiés.

## État actuel des lots

Les lots 1 à 13 sont réalisés et commités. Le lot 13 ajoute l'audit runtime des
review packages, décisions humaines et imports contrôlés dans SQLite.

Voir [docs/LOT_STATUS.md](docs/LOT_STATUS.md) pour le détail.

## Prochaine étape recommandée

Créer un export ou tableau de bord local de l'audit ledger pour consulter
l'historique des décisions par batch avant d'envisager un lot d'ingestion
documentaire contrôlée.
