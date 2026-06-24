# Rapport Codex — Lot 16C : optimisation du cleanup dry-run

## 1. Objectif

Optimiser le dry-run de nettoyage sans nettoyer, déplacer, archiver ni créer de staging. Le lot 16C garde le dry-run comme outil de classification et de revue humaine uniquement.

## 2. Point de départ

Point de départ vérifié sur `/home/alaeddine/Bureau/RAG/rag-pedago` :

- commit en tête : `7109922 docs: add cleanup policy dry-run` ;
- `git status --short --branch` initial : `## main` ;
- `make cleanup-dry-run` initial : OK, mais scan profond de `rag-local/.venv` ;
- `make metadata-preflight` initial : OK ;
- `make doctor` initial : OK ;
- `make project-doctor` initial : OK ;
- `make test` initial : `377 passed in 204.10s`.

`rag-local` a été vérifié en lecture seule. Son état initial contenait déjà :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

Aucun fichier de `rag-local` n'a été modifié.

## 3. Problème identifié dans 16B

Le dry-run 16B parcourait profondément tout le workspace, sauf les dossiers `.git`. En pratique, `rag-local/.venv` et les caches lourds dominaient les compteurs :

- `safe_delete_candidates_count: 32878` ;
- `readonly_repo_matches_count: 81584`.

Les tests unitaires appelaient aussi plusieurs fois la configuration réelle, ce qui rendait `pytest tests/unit/test_cleanup_dry_run.py -q` trop lent pour un test unitaire.

## 4. Fichiers créés ou modifiés

Fichiers modifiés :

- `configs/cleanup_policy.yml` ;
- `scripts/cleanup_dry_run.py` ;
- `tests/unit/test_cleanup_dry_run.py` ;
- `docs/CLEANUP_POLICY.md`.

Fichier créé :

- `data/reports/codex_lot_16C_cleanup_dry_run_optimization.md`.

## 5. Configuration deep_scan_exclusions

La configuration ajoute :

```yaml
deep_scan_exclusions:
  - "rag-local/.venv/**"
  - "rag-local/.mypy_cache/**"
  - "rag-local/.pytest_cache/**"
  - "rag-local/.ruff_cache/**"
  - "**/.git/**"

summarize_only_roots:
  - "rag-local/.venv"
  - "rag-local/.mypy_cache"
  - "rag-local/.pytest_cache"
  - "rag-local/.ruff_cache"
```

Ces chemins sont exclus du scan profond uniquement. Ils ne deviennent ni supprimables, ni déplaçables, ni archivables automatiquement.

## 6. Optimisation du script

`scripts/cleanup_dry_run.py` charge maintenant :

- `deep_scan_exclusions` ;
- `summarize_only_roots`.

Le parcours `os.walk` reste sans symlinks et top-down, mais il retire les racines exclues de la descente récursive après les avoir signalées dans le rapport.

Nouveaux compteurs :

- `deep_scan_exclusions_count` ;
- `summarize_only_roots_count`.

Nouveaux échantillons :

- `deep_scan_exclusions_sample` ;
- `summarize_only_roots_sample`.

Le script conserve :

- `would_delete: 0` ;
- `would_move: 0` ;
- aucun mode `--apply`, `--delete` ou `--move`.

## 7. Optimisation des tests

`tests/unit/test_cleanup_dry_run.py` utilise maintenant un mini-workspace temporaire créé dans `tmp_path` pour tester la classification :

- `rag-pedago/data/reports/codex_lot_1.md` ;
- `rag-pedago/data/reports/manifest_directory_import_batch-test.md` ;
- `rag-pedago/docs/CLEANUP_POLICY.md` ;
- `rag-pedago/tests/sample.py` ;
- `rag-pedago/__pycache__/sample.pyc` ;
- `rag-local/.venv/ignored.pyc` ;
- `rag-local/patch-ci.diff` ;
- `rag-local/.env` ;
- `rag-local/drive_sync_state.db`.

Le test prouve que `rag-local/.venv/ignored.pyc` n'apparaît pas dans la sortie quand `rag-local/.venv` est une racine exclue du scan profond.

Tests de verrouillage ajoutés en finalisation 16C-Fix :

- test `.git` ajouté : oui, `rag-pedago/.git/config` et `rag-local/.git/config` ne doivent pas apparaître dans la sortie ;
- test symlink ajouté : oui, `rag-pedago/link-to-outside-heavy` ne doit pas conduire à scanner `outside-heavy/hidden.pyc`.

Un seul test utilise encore la configuration réelle pour vérifier que le dry-run ne modifie pas :

- le statut Git du vrai dépôt ;
- `data/staging` ;
- le ledger permanent.

Cycle TDD observé :

- test ciblé rouge avant implémentation : `3 failed, 5 passed in 29.92s` ;
- test ciblé vert après implémentation : `8 passed in 1.30s`.
- finalisation 16C-Fix après ajout des tests `.git` et symlink : `10 passed`, environ `1.3s` selon les runs locaux.

## 8. Résultats du dry-run

Dry-run optimisé :

```text
cleanup dry-run report
workspace_root: /home/alaeddine/Bureau/RAG
active_repo: rag-pedago
readonly_repo: rag-local
safe_delete_candidates_count: 210
archive_candidates_count: 2864
never_delete_matches_count: 18
always_keep_matches_count: 103
readonly_repo_matches_count: 381
deep_scan_exclusions_count: 6
summarize_only_roots_count: 4
would_delete: 0
would_move: 0
```

Racines exclues observées :

- `rag-local/.git` ;
- `rag-local/.mypy_cache` ;
- `rag-local/.pytest_cache` ;
- `rag-local/.ruff_cache` ;
- `rag-local/.venv` ;
- `rag-pedago/.git`.

Les compteurs du dry-run sont des observations de l’état courant du workspace. Ils peuvent varier si de nouveaux rapports runtime, caches ou fichiers locaux apparaissent. Ils ne constituent pas une autorisation de suppression. La décision de nettoyage doit s’appuyer sur une revue humaine des chemins, pas sur les compteurs seuls.

## 9. Résultats des tests

Résultats finaux :

- test `.git` ajouté : oui ;
- test symlink ajouté : oui ;
- `python3 -m ruff check scripts/cleanup_dry_run.py tests/unit/test_cleanup_dry_run.py` : OK ;
- pytest ciblé : `10 passed`, environ `1.3s` selon les runs locaux ;
- `make cleanup-dry-run` : OK, `would_delete: 0`, `would_move: 0`, `deep_scan_exclusions_count: 6`, `summarize_only_roots_count: 4` ;
- `make metadata-preflight` : OK, `data_staging_absent: True`, `permanent_ledger_unchanged: True` ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : `380 passed`, environ `79s` sur ce poste ;
- `data/staging` : absent ;
- ledger permanent : présent mais non modifié ;
- `rag-local` : non modifié.

## 10. Garanties non destructives

Garanties maintenues :

- aucun fichier supprimé ;
- aucun fichier déplacé ;
- aucune archive créée ;
- aucun `.env` ouvert ;
- aucun secret lu ;
- aucun ledger modifié ;
- aucun `data/staging` créé ;
- `rag-local` non modifié.
- compteurs observationnels documentés.

Le script ne contient pas :

- `unlink(` ;
- `remove(` ;
- `rmdir(` ;
- `shutil.rmtree` ;
- `shutil.move` ;
- `--apply` ;
- `--delete` ;
- `--move` ;
- `find -delete` ;
- `rm -rf` ;
- `git clean`.

## 11. Risques restants

Risques restants :

- les compteurs restent des compteurs de classification, pas une liste validée pour action ;
- ces compteurs sont observationnels et peuvent varier selon les rapports runtime, caches et fichiers locaux présents au moment du dry-run ;
- les fichiers sensibles situés dans les racines exclues ne sont plus détaillés par le scan profond, ce qui est volontaire pour les dossiers lourds mais impose une revue séparée si ces racines deviennent un sujet de nettoyage ;
- les chemins de `rag-local` restent en lecture seule et ne doivent pas être nettoyés sans lot dédié.

## 12. Verdict

READY_FOR_OPTIMIZED_DRY_RUN_REVIEW

## 13. Recommandation pour 16D

Ne pas lancer de nettoyage réel en 16D sans revue humaine du rapport optimisé. Le prochain lot devrait définir un périmètre très limité de revue, séparant clairement les candidats de suppression des candidats d'archivage, avec rollback documentaire et confirmation explicite que `rag-local` reste exclu de toute action.
