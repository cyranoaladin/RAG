# Rapport Codex — Lot 17B : garde-fous opérationnels des cibles Makefile

## 1. Objectif

Clarifier la sûreté opérationnelle des cibles Makefile afin de distinguer les commandes sûres des commandes restreintes, futures ou interdites hors lot dédié.

Le lot 17B ne lance aucune cible sensible, ne lance aucune ingestion, ne lance aucun scraping, ne démarre aucun runtime API/watch, ne crée aucun embedding, ne touche pas à Qdrant et ne modifie pas `rag-local`.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `adb0131 docs: add rag functional audit` ;
- `git status --short --branch` initial : `## main` ;
- `make cleanup-dry-run` : OK, `would_delete: 0`, `would_move: 0` ;
- `make cleanup-review` : OK, `human_review_required: true`, `destructive_action_available: false` ;
- `make cleanup-decision-draft` : OK, `human_decision_required: true`, `decision_applied: false`, `destructive_action_available: false` ;
- `make metadata-preflight` : OK, `data_staging_absent: True`, `permanent_ledger_unchanged: True`, `real_documents_absent: True` ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : `408 passed in 84.01s`.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `configs/make_target_safety.yml` ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` ;
- `scripts/make_target_safety_audit.py` ;
- `tests/unit/test_make_target_safety_audit.py` ;
- `data/reports/codex_lot_17B_make_target_safety.md`.

Fichier modifié :

- `Makefile`.

## 4. Configuration make_target_safety.yml

La configuration classe toutes les cibles Makefile observées dans les catégories autorisées :

- SAFE_DIAGNOSTIC ;
- SAFE_METADATA_ONLY ;
- SAFE_CLEANUP_REVIEW ;
- SAFE_TESTING ;
- RESTRICTED_METADATA_IMPORT ;
- RESTRICTED_RUNTIME ;
- RESTRICTED_NETWORK ;
- RESTRICTED_DESTRUCTIVE_OR_BACKUP ;
- FUTURE_NOT_READY ;
- UNKNOWN.

Les cibles additionnelles observées par rapport à la liste minimale ont été classées prudemment :

- `install` : RESTRICTED_NETWORK ;
- `format` : RESTRICTED_DESTRUCTIVE_OR_BACKUP ;
- `make-target-safety-audit` : SAFE_DIAGNOSTIC.

## 5. Protocole MAKE_TARGET_SAFETY

Le protocole `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` définit :

- les principes de classification ;
- les catégories de sûreté ;
- les cibles autorisées par défaut ;
- les cibles interdites hors lot dédié ;
- les conditions avant d’utiliser une cible restreinte ;
- les conditions avant de déclarer une cible SAFE.

## 6. Script make_target_safety_audit.py

Le script `scripts/make_target_safety_audit.py` :

- lit le Makefile ;
- extrait les cibles déclarées dans `.PHONY` ;
- extrait les règles réelles du Makefile ;
- compare `.PHONY`, règles réelles et configuration ;
- lit `configs/make_target_safety.yml` ;
- vérifie que chaque cible est classée ;
- vérifie qu’aucune cible sensible connue n’est classée SAFE_* ;
- vérifie qu’aucune cible réelle n’est absente de `.PHONY` ;
- vérifie qu’aucune cible `.PHONY` n’est sans règle réelle ;
- vérifie qu’aucune cible de configuration n’est absente du Makefile ;
- interdit toute cible classée dans `UNKNOWN` ;
- détecte les catégories YAML inconnues ;
- détecte les doublons de classification ;
- détecte les entrées de configuration mal formées ;
- rend les erreurs de configuration en Markdown sans traceback ;
- détecte les cibles SAFE_* dont le nom contient un motif sensible ;
- autorise seulement les exceptions SAFE explicitement testées ;
- produit un rapport Markdown sur stdout ;
- ne lance aucune cible Makefile ;
- ne fait aucun appel réseau ;
- n’écrit aucun fichier ;
- n’ouvre aucun `.env` ;
- ne crée pas `data/staging`.

Options autorisées :

- `--makefile` ;
- `--config`.

## 7. Cible Makefile

Une cible non destructive a été ajoutée :

```makefile
make-target-safety-audit:
	$(PY) scripts/make_target_safety_audit.py
```

Aucune cible destructive, runtime, réseau, ingestion ou scraping n’a été ajoutée.

## 8. Tests ajoutés

Le fichier `tests/unit/test_make_target_safety_audit.py` ajoute 29 tests couvrant :

- existence de la configuration, du protocole et du script ;
- présence de la cible Makefile ;
- absence de chaînes réseau, subprocess ou destructives dans le script ;
- sortie Markdown du script ;
- classification exhaustive de toutes les cibles Makefile ;
- absence de cible sensible dans les catégories SAFE_* ;
- classification stable des cibles ingest, scrape, api, watch, backup, eval-retrieval et cleanup ;
- absence de modification du statut Git ;
- absence de création de `data/staging` ;
- absence de lecture de `.env` ;
- cohérence `.PHONY` et règles réelles ;
- cible réelle absente de `.PHONY` ;
- cible `.PHONY` sans règle ;
- cible de configuration obsolète ;
- continuation `.PHONY` ;
- règle multi-cibles ;
- vrai Makefile validé ;
- catégorie `UNKNOWN` interdite ;
- catégorie YAML inconnue ;
- cible classée deux fois ;
- valeur de catégorie non-liste ;
- entrée non-string ;
- CLI réelle ;
- CLI en mode `python -O` ;
- absence de traceback sur erreur de configuration attendue ;
- détection de `deploy-prod` classé SAFE ;
- détection de `qdrant-upsert` classé SAFE ;
- détection de `embed-corpus` classé SAFE ;
- exceptions SAFE vérifiées ;
- vrai Makefile validé avec `suspicious_safe_classifications_count: 0`.

Résultats observés :

- `python3 -m ruff check ...` : OK ;
- `pytest tests/unit/test_cleanup_dry_run.py -q` : `10 passed` ;
- `pytest tests/unit/test_cleanup_review_package.py -q` : `15 passed` ;
- `pytest tests/unit/test_cleanup_decision_draft.py -q` : `13 passed` ;
- `pytest tests/unit/test_make_target_safety_audit.py -q` : `29 passed` ;
- `make test` : `437 passed in 84.69s`.

## 9. Résultat du make-target-safety-audit

Résultat observé :

- `all_targets_classified: true` ;
- `phony_targets_count: 42` ;
- `rule_targets_count: 42` ;
- `all_make_targets_count: 42` ;
- `rule_targets_not_phony_count: 0` ;
- `phony_targets_without_rule_count: 0` ;
- `extra_config_targets_count: 0` ;
- `invalid_config_categories_count: 0` ;
- `duplicate_classifications_count: 0` ;
- `malformed_config_entries_count: 0` ;
- `unknown_targets_count: 0` ;
- `unclassified_targets_count: 0` ;
- `unsafe_safe_classifications_count: 0` ;
- `suspicious_safe_classifications_count: 0` ;
- `destructive_action_available: false` ;
- `targets_executed: false`.

Le script n’a lancé aucune cible Makefile.

Durcissement par motifs sensibles :

- motifs sensibles ajoutés : oui ;
- `suspicious_safe_classifications_count` ajouté ;
- détection de `deploy-prod` SAFE : oui ;
- détection de `qdrant-upsert` SAFE : oui ;
- détection de `embed-corpus` SAFE : oui ;
- exceptions SAFE vérifiées : oui ;
- vrai Makefile validé avec `suspicious_safe_classifications_count: 0`.

## 10. Cibles SAFE_*

SAFE_DIAGNOSTIC :

- `doctor` ;
- `project-doctor` ;
- `make-target-safety-audit`.

SAFE_METADATA_ONLY :

- `metadata-preflight` ;
- `pilot-template-check` ;
- `pilot-compile-check` ;
- `pilot-rehearsal` ;
- `real-draft-guard-check` ;
- `human-unlock-check` ;
- `real-draft-unlock-gate-check`.

SAFE_CLEANUP_REVIEW :

- `cleanup-dry-run` ;
- `cleanup-review` ;
- `cleanup-decision-draft`.

SAFE_TESTING :

- `test` ;
- `lint` ;
- `typecheck`.

## 11. Cibles restreintes

RESTRICTED_METADATA_IMPORT :

- `ledger-init` ;
- `ledger-doctor` ;
- `manifest-import-fixture` ;
- `manifest-dir-dry-run` ;
- `manifest-dir-import-fixture` ;
- `manifest-readiness` ;
- `manifest-coverage` ;
- `manifest-gate` ;
- `manifest-readiness-clean` ;
- `manifest-coverage-clean` ;
- `manifest-gate-clean` ;
- `manifest-controlled-import-clean` ;
- `manifest-controlled-import-problem` ;
- `review-package-clean-audited`.

RESTRICTED_RUNTIME :

- `watch` ;
- `api`.

RESTRICTED_NETWORK :

- `install` ;
- `scrape-official`.

RESTRICTED_DESTRUCTIVE_OR_BACKUP :

- `format` ;
- `backup`.

## 12. Cibles futures non prêtes

FUTURE_NOT_READY :

- `init` ;
- `ingest` ;
- `ingest-official` ;
- `ingest-internal` ;
- `verify` ;
- `eval-retrieval`.

## 13. Garanties non destructives

Garanties explicites :

- aucune cible sensible lancée ;
- aucune cible ingest lancée ;
- aucune cible scrape lancée ;
- aucune cible api/watch lancée ;
- aucun fichier supprimé ;
- aucun fichier déplacé ;
- aucune archive créée ;
- aucun réseau ;
- aucun `.env` ouvert ;
- aucun `data/staging` créé ;
- `rag-local` non modifié.
- rag-local non modifié.

## 14. Risques restants

- La classification est déclarative : elle doit être maintenue à chaque ajout ou modification de cible Makefile.
- Les cibles restreintes existent encore et restent dangereuses si elles sont lancées hors lot dédié.
- Les cibles FUTURE_NOT_READY ne prouvent pas que les composants associés sont prêts ; elles signalent explicitement l’inverse.

## 15. Verdict

READY_FOR_MAKE_TARGET_SAFETY_REVIEW

## 16. Recommandation pour 17C

Préparer le périmètre d’un corpus pilote strictement synthétique ou metadata-only, sans document réel, sans ingestion, sans embedding et sans Qdrant. Conserver la classification Makefile comme garde-fou préalable à tout lot qui voudrait utiliser une cible restreinte.
