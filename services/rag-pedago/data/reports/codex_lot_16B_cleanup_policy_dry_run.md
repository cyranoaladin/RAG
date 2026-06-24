# Rapport Codex — Lot 16B : politique de nettoyage et dry-run

## 1. Objectif

Le lot 16B prépare une politique de nettoyage exploitable pour le workspace `/home/alaeddine/Bureau/RAG`, avec allowlist, denylist et script de dry-run.

Ce lot ne nettoie rien. Il classe et affiche uniquement ce qui serait candidat à une future revue humaine.

## 2. Point de départ

Point de départ vérifié :

- dépôt actif : `/home/alaeddine/Bureau/RAG/rag-pedago` ;
- commit en tête : `8bd37b2 docs: audit path migration and cleanup candidates` ;
- `git status --short --branch` initial : `## main` ;
- `rag-local` vérifié en lecture seule ;
- artefacts 16B absents de `rag-local`.

Validations initiales :

- `make metadata-preflight` : OK, `metadata_preflight_ready`, `issues: 0` ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : OK, `370 passed in 81.44s`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/CLEANUP_POLICY.md` ;
- `configs/cleanup_policy.yml` ;
- `scripts/cleanup_dry_run.py` ;
- `tests/unit/test_cleanup_dry_run.py` ;
- `data/reports/codex_lot_16B_cleanup_policy_dry_run.md`.

Fichiers modifiés :

- `Makefile` ;
- `.gitignore`.

## 4. Politique de nettoyage

La politique `docs/CLEANUP_POLICY.md` définit :

- aucun nettoyage sans dry-run ;
- aucun nettoyage sans validation humaine ;
- aucun nettoyage dans `rag-local` sans instruction explicite ;
- aucun secret supprimé automatiquement ;
- aucun ledger supprimé automatiquement ;
- aucun document source supprimé automatiquement ;
- aucun fichier d'infra production supprimé automatiquement.

Catégories documentées :

- supprimables après validation humaine ;
- à ignorer via `.gitignore` ;
- à archiver avant suppression ;
- à conserver ;
- à ne jamais supprimer automatiquement ;
- à examiner humainement.

## 5. Configuration cleanup_policy.yml

La configuration `configs/cleanup_policy.yml` décrit :

- `workspace_root: /home/alaeddine/Bureau/RAG` ;
- `active_repo: rag-pedago` ;
- `readonly_repos: rag-local` ;
- familles candidates à suppression future après validation humaine ;
- familles candidates à archivage futur ;
- familles `never_delete` ;
- familles `always_keep`.

La configuration n'autorise aucune suppression. Elle sert uniquement à classer les chemins pendant le dry-run.

## 6. Script cleanup_dry_run.py

Le script `scripts/cleanup_dry_run.py` :

- lit `configs/cleanup_policy.yml` ;
- parcourt `/home/alaeddine/Bureau/RAG` ;
- ignore `.git` ;
- ne suit pas les symlinks ;
- classe les chemins par catégories ;
- signale `rag-local` comme read-only ;
- affiche des compteurs et exemples ;
- retourne `0` si le dry-run s'exécute correctement.

Le script ne contient pas de mode destructif :

- pas d'option `--apply` ;
- pas d'option `--delete` ;
- pas d'option `--move`.

## 7. Cible Makefile

La cible non destructive suivante a été ajoutée :

```makefile
cleanup-dry-run:
	$(PY) scripts/cleanup_dry_run.py
```

Aucune cible destructive n'a été ajoutée.

## 8. .gitignore

`.gitignore` a été audité.

Règles sûres ajoutées car manquantes :

```gitignore
workspace/scratch/
*.tmp
*.bak
*~
```

Les règles existantes couvraient déjà :

- `__pycache__/` ;
- `*.py[cod]` ;
- `.pytest_cache/` ;
- `.ruff_cache/` ;
- `.mypy_cache/`.

Les rapports Codex `data/reports/codex_lot_*.md` ne sont pas ignorés. Les fixtures synthétiques, docs, tests, schémas et taxonomies ne sont pas ignorés.

## 9. Tests ajoutés

Test ajouté :

```text
tests/unit/test_cleanup_dry_run.py
```

Garanties testées :

- la politique existe ;
- la configuration existe ;
- le script existe ;
- le script ne contient pas d'appels destructifs ;
- le script ne contient pas d'options destructives ;
- le dry-run retourne `0` ;
- le dry-run affiche `would_delete: 0` ;
- le dry-run affiche `would_move: 0` ;
- `rag-local` est signalé comme read-only ;
- des candidats cache ou runtime sont détectés ;
- `git status` n'est pas modifié ;
- `data/staging` n'est pas créé ;
- le ledger permanent n'est pas modifié ;
- le contenu des `.env` n'est pas lu ;
- la configuration protège `.env`, secrets, credentials, SQLite, DB, uploads, raw et `infra/creds` ;
- les rapports Codex sont dans `always_keep`.

Cycle TDD observé :

- premier run ciblé : `7 failed`, car politique, config et script étaient absents ;
- run après implémentation : `7 passed in 116.77s`.

Validation finale ciblée :

- `pytest tests/unit/test_cleanup_dry_run.py -q` : `7 passed in 116.78s`.

## 10. Résultats du dry-run

Commande exécutée :

```text
make cleanup-dry-run
```

Résultat :

```text
cleanup dry-run report
workspace_root: /home/alaeddine/Bureau/RAG
active_repo: rag-pedago
readonly_repo: rag-local
safe_delete_candidates_count: 32878
archive_candidates_count: 2719
never_delete_matches_count: 69
always_keep_matches_count: 102
readonly_repo_matches_count: 81584
would_delete: 0
would_move: 0
```

Le volume élevé de candidats vient principalement de `rag-local/.venv`, des caches Python et des rapports runtime historiques.

Validations finales complémentaires :

- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : `377 passed in 202.89s`.

## 11. Garanties non destructives

Garanties explicites :

- aucun fichier supprimé ;
- aucun fichier déplacé ;
- aucun dossier créé hors fichiers du lot ;
- aucune archive créée ;
- aucun `.env` ouvert ;
- aucun secret lu ;
- aucun ledger modifié ;
- aucun `data/staging` créé ;
- `rag-local` non modifié.
- rag-local non modifié.

Le script n'a aucun mode d'application destructive. Il affiche uniquement des catégories et des compteurs.

## 12. Risques restants

Risques restants :

- le dry-run parcourt `rag-local/.venv`, ce qui produit beaucoup de candidats et ralentit les tests ciblés ;
- certains chemins peuvent matcher plusieurs catégories, par exemple cache et read-only ;
- `rag-local` contient des `.env`, backups et chemins sensibles qui doivent rester en revue humaine stricte ;
- les rapports runtime massifs ne doivent pas être déplacés sans validation humaine ;
- une future action réelle devra séparer clairement suppression et archivage.

## 13. Verdict

READY_FOR_DRY_RUN_REVIEW

## 14. Recommandation pour 16C

Pour le lot 16C, faire une revue humaine de la sortie du dry-run, décider si `rag-local/.venv` doit être exclu des scans détaillés ou traité à part, puis définir un périmètre limité de nettoyage contrôlé.

Aucune suppression ni archive réelle ne doit être lancée avant cette validation.

Message de commit proposé si le verdict est accepté :

```text
docs: add cleanup policy dry-run
```
