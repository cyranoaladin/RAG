# Manifest review and approval

Le gate indique si un batch est prêt techniquement. La revue humaine ajoute une
trace d'approbation attachée aux hashes exacts des manifests et rapports.

## Gate vs review package vs approval

- `gate` : décision automatique readiness + coverage.
- `review package` : paquet d'audit avec hashes des manifests, rapports,
  taxonomies et référentiel officiel.
- `approval` : décision humaine signée par un reviewer, liée au hash exact du
  package et au hash du JSON gate.

Un package dont le gate est bloqué peut être généré pour analyse, mais il ne
peut pas être approuvé.

## Hashes

Le review package contient :

- SHA-256 de chaque manifest JSONL ;
- SHA-256 du JSON readiness ;
- SHA-256 du JSON coverage ;
- SHA-256 du JSON gate ;
- SHA-256 stable de `data/reference/` ;
- SHA-256 de chaque taxonomie utilisée ;
- commit Git courant si disponible.

Le JSON gate inclut aussi les hashes des manifests. Si un manifest change après
approbation, le hash gate recalculé ne correspond plus à la décision.

Depuis le lot 12.5, le hash du review package est calculé en JSON canonique :
tri des clés, séparateurs déterministes et sérialisation UTF-8. L'indentation,
l'ordre des clés et la plateforme ne changent pas le hash.

## Import avec revue obligatoire

Commande :

```bash
python -m rag_pedago.imports.controlled_import_cli data/fixtures/manifests/batch_official_profiles_clean \
  --batch-id batch-official-profiles-clean \
  --taxonomy taxonomy/maths/terminale_specialite.yml \
  --taxonomy taxonomy/nsi/terminale.yml \
  --require-review \
  --review-decision data/reviews/review_<id>.json
```

Si `--require-review` est actif :

- une décision review est obligatoire ;
- le package review correspondant est obligatoire ;
- la décision doit être `approved` ;
- le `batch_id` doit correspondre ;
- le hash canonique du package doit correspondre à la décision ;
- les hashes des manifests doivent correspondre ;
- les hashes des taxonomies doivent correspondre ;
- le hash du référentiel officiel doit correspondre ;
- le `gate_json_sha256` courant doit correspondre à celui de la décision ;
- sinon aucune écriture ledger n'est effectuée.

## Reviewer policy et registry

Par défaut, un reviewer non vide suffit. En mode strict, une `ReviewerPolicy`
peut exiger que le reviewer appartienne à `allowed_reviewers`.

Chaque décision est appendue dans `data/reviews/review_registry.jsonl`. Ce
registry est runtime et ignoré par Git.

## Audit SQLite

Depuis le lot 13, les commandes acceptent `--audit-ledger`. Quand l'option est
fournie :

- le package est enregistré dans `review_packages` ;
- la décision est enregistrée dans `review_decisions` ;
- les tentatives d'import contrôlé sont enregistrées dans
  `controlled_import_attempts` ;
- chaque vérification est enregistrée dans
  `controlled_import_verifications`.

Le registry JSONL reste append-only et pratique pour l'export. Le ledger SQLite
devient la source locale requêtable de l'historique de validation.

## Garanties

- aucun `source_uri` n'est ouvert ;
- aucun document n'est ingéré ;
- aucun appel réseau n'est effectué ;
- aucune connexion Qdrant ou PostgreSQL n'est utilisée.

## Limites

La revue valide les métadonnées, rapports et hashes. Elle ne valide pas le
contenu réel d'un PDF, d'une annale, d'un corrigé ou d'un barème.
