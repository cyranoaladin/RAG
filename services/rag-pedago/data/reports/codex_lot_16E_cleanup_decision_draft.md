# Rapport Codex — Lot 16E : cleanup decision draft

## 1. Objectif

Produire un brouillon de décision humaine structuré à partir des catégories du dry-run et du cleanup-review, sans appliquer aucune décision.

Le lot 16E ne supprime rien, ne déplace rien, ne crée aucune archive et ne modifie pas `rag-local`.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `144a6f3 feat: add cleanup review package` ;
- `git status --short --branch` initial : `## main` ;
- `make cleanup-dry-run` initial : OK, `would_delete: 0`, `would_move: 0` ;
- `make cleanup-review` initial : OK, `human_review_required: true`, `destructive_action_available: false` ;
- `make metadata-preflight` initial : OK, `data_staging_absent: True`, `permanent_ledger_unchanged: True` ;
- `make doctor` initial : OK ;
- `make project-doctor` initial : OK ;
- `make test` initial : `395 passed in 81.62s`.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/CLEANUP_DECISION_PROTOCOL.md` ;
- `scripts/cleanup_decision_draft.py` ;
- `tests/unit/test_cleanup_decision_draft.py` ;
- `data/reports/codex_lot_16E_cleanup_decision_draft.md`.

Fichier modifié :

- `Makefile`.

## 4. Protocole de décision humaine

`docs/CLEANUP_DECISION_PROTOCOL.md` définit :

- les principes non destructifs ;
- les états de décision autorisés ;
- les règles par catégorie ;
- les règles de sortie ;
- les conditions avant tout futur lot d’action.

Les décisions restent humaines et différées. Les chemins listés ne valent pas autorisation d’action.

## 5. Script cleanup_decision_draft.py

`scripts/cleanup_decision_draft.py` réutilise le dry-run existant :

- `cleanup_dry_run.load_policy()` ;
- `cleanup_dry_run.build_dry_run_report()`.

Le script ne parse pas le Markdown du cleanup-review. Il produit uniquement une sortie Markdown sur stdout et accepte seulement :

- `--config` ;
- `--sample-limit`.

Le bornage est identique au cleanup-review :

- `DEFAULT_SAMPLE_LIMIT = 20` ;
- `MAX_SAMPLE_LIMIT = 200` ;
- erreur explicite : `--sample-limit must be between 1 and 200`.

Les décisions par défaut sont :

- `always_keep_matches` -> `KEEP_REQUIRED` ;
- `never_delete_matches` -> `NEVER_DELETE` ;
- `readonly_repo_matches` -> `READONLY_REPOSITORY` ;
- `deep_scan_exclusions` -> `DEEP_SCAN_EXCLUDED` ;
- `summarize_only_roots` -> `DEEP_SCAN_EXCLUDED` ;
- `archive_candidates` -> `FUTURE_ARCHIVE_CANDIDATE` ;
- `safe_delete_candidates` -> `FUTURE_DELETE_CANDIDATE`.

La colonne `allowed_current_action` vaut toujours `NONE_IN_THIS_LOT`.

## 6. Cible Makefile

La cible non destructive suivante a été ajoutée :

```makefile
cleanup-decision-draft:
	$(PY) scripts/cleanup_decision_draft.py
```

Aucune cible destructive n'a été ajoutée.

## 7. Tests ajoutés

Test ajouté :

```text
tests/unit/test_cleanup_decision_draft.py
```

Le test utilise un mini-workspace `tmp_path` et vérifie :

- l’existence du protocole ;
- l’existence du script ;
- l’absence d’API ou option destructive ;
- l’absence d’import réseau ;
- l’absence de mécanisme subprocess dans le script ;
- le retour `0` ;
- la sortie Markdown ;
- `human_decision_required: true` ;
- `decision_applied: false` ;
- `destructive_action_available: false` ;
- `would_delete: 0` ;
- `would_move: 0` ;
- `NONE_IN_THIS_LOT` ;
- les états de décision attendus ;
- la limite `--sample-limit` ;
- le rejet de `--sample-limit 0` ;
- le rejet de `--sample-limit 100000` ;
- l’exécution en `python3 -O` ;
- l’absence d’écriture fichier ;
- l’absence de lecture du contenu `.env` ;
- l’absence de descente dans `.git` ;
- l’absence de suivi des symlinks ;
- l’absence de création de `data/staging` ;
- l’absence de modification du ledger permanent ;
- l’absence de modification du statut Git ;
- l’existence de la cible Makefile ;
- l’absence de cible destructive.

Cycle TDD observé :

- premier run ciblé : `13 failed`, car protocole, script et cible Makefile absents.
- run ciblé après implémentation : `13 passed in 1.88s`.

## 8. Résultat du cleanup-decision-draft

Résultat attendu de `make cleanup-decision-draft` :

- sortie Markdown `# Cleanup decision draft` ;
- `human_decision_required: true` ;
- `decision_applied: false` ;
- `destructive_action_available: false` ;
- `would_delete: 0` ;
- `would_move: 0` ;
- `NONE_IN_THIS_LOT` ;
- échantillons triés et limités.

Résultat final observé :

- protocole de décision créé : oui ;
- script cleanup-decision-draft créé : oui ;
- cible Makefile créée : oui ;
- tests ajoutés : oui ;
- `python3 -m ruff check scripts/cleanup_dry_run.py scripts/cleanup_review_package.py scripts/cleanup_decision_draft.py tests/unit/test_cleanup_dry_run.py tests/unit/test_cleanup_review_package.py tests/unit/test_cleanup_decision_draft.py` : OK ;
- `pytest tests/unit/test_cleanup_dry_run.py -q` : `10 passed in 1.46s` ;
- `pytest tests/unit/test_cleanup_review_package.py -q` : `15 passed in 1.93s` ;
- `pytest tests/unit/test_cleanup_decision_draft.py -q` : `13 passed in 1.88s` ;
- `make cleanup-dry-run` : OK, `would_delete: 0`, `would_move: 0` ;
- `make cleanup-review` : OK, `human_review_required: true`, `destructive_action_available: false` ;
- `make cleanup-decision-draft` : OK, `human_decision_required: true`, `decision_applied: false`, `destructive_action_available: false`, `would_delete: 0`, `would_move: 0` ;
- `make metadata-preflight` : OK, `data_staging_absent: True`, `permanent_ledger_unchanged: True` ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : `408 passed in 87.63s` ;
- `data/staging` : absent ;
- ledger permanent : présent mais non modifié ;
- `rag-local` : non modifié.

## 9. Garanties non destructives

Garanties explicites :

- aucune suppression ;
- aucun déplacement ;
- aucune archive ;
- aucune décision appliquée ;
- aucun `.env` ouvert ;
- aucun secret lu ;
- aucun ledger modifié ;
- aucun `data/staging` créé ;
- `rag-local` non modifié ;
- aucun push ;
- aucun réseau.

## 10. Limites

Le brouillon de décision ne décide aucune action. Il applique des états par défaut pour structurer une revue humaine ultérieure.

Les compteurs et échantillons restent observationnels et peuvent varier selon les rapports runtime, caches et fichiers locaux présents au moment de l’exécution.

## 11. Risques restants

Risques restants :

- certains chemins peuvent appartenir à plusieurs catégories ;
- les échantillons ne sont pas exhaustifs ;
- les candidats futurs à archive ou suppression ne sont pas validés ;
- tout futur lot d’action devra lister explicitement les chemins et séparer archivage et suppression.

## 12. Verdict

READY_FOR_CLEANUP_DECISION_DRAFT

## 13. Recommandation pour 16F

Ne pas démarrer de lot d’action. Relire humainement le brouillon de décision, puis préparer uniquement une revue documentaire ou un protocole d’approbation explicite.
