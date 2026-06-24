# Rapport Codex — Lot 17H : transition contrôlée metadata-only

## 1. Objectif

Le lot 17H définit un gate déclaratif de transition contrôlée avant toute source réelle.

Il agrège les garanties des lots 17C, 17D, 17E, 17F et 17G afin de répondre à la question : le système est-il prêt pour une revue humaine de transition, sans encore autoriser de source réelle, de document réel, d’ingestion, de parsing, de chunking, d’embedding ou de Qdrant ?

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `d55f5b4 feat: add human source review audit` ;
- `git status --short --branch` initial : `## main` ;
- `make make-target-safety-audit` : OK ;
- `make pilot-corpus-scope-audit` : OK ;
- `make retrieval-metadata-eval-audit` : OK ;
- `make pedago-interface-contract-audit` : OK ;
- `make source-admission-policy-audit` : OK ;
- `make human-source-review-audit` : OK ;
- `make cleanup-dry-run` : OK ;
- `make cleanup-review` : OK ;
- `make cleanup-decision-draft` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : 708 passed in 97.81s.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/CONTROLLED_READINESS_PROTOCOL.md` ;
- `configs/controlled_readiness.yml` ;
- `scripts/controlled_readiness_audit.py` ;
- `tests/unit/test_controlled_readiness_audit.py` ;
- `data/reports/codex_lot_17H_controlled_readiness.md`.

Fichiers modifiés :

- `Makefile` : ajout de `controlled-readiness-audit` ;
- `configs/make_target_safety.yml` : classification en `SAFE_METADATA_ONLY` ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` : mention de la nouvelle cible sûre.

## 4. Protocole CONTROLLED_READINESS

Le protocole `docs/CONTROLLED_READINESS_PROTOCOL.md` définit :

- le périmètre agrégé 17C à 17G ;
- les interdictions avant toute source réelle ;
- les gates préalables obligatoires ;
- les décisions de transition autorisées ;
- les conditions de revue transitionnelle ;
- les conditions minimales avant un futur lot réel.

## 5. Configuration controlled_readiness.yml

La configuration `configs/controlled_readiness.yml` est déclarative uniquement.

Elle fixe :

- `readiness_id: controlled_readiness_metadata_gate_v1` ;
- `status: metadata_only_controlled_readiness` ;
- `pilot_scope_ref: math_terminale_specialite_metadata_only_v1` ;
- `retrieval_eval_ref: math_terminale_specialite_metadata_retrieval_eval_v1` ;
- `pedago_interface_ref: pedago_interface_metadata_contract_v1` ;
- `source_admission_policy_ref: source_admission_metadata_policy_v1` ;
- `human_source_review_ref: human_source_review_metadata_policy_v1`.

Toutes les autorisations dangereuses valent `false`.

Gates requis vérifiés :

- `pilot_scope_gate` ;
- `retrieval_metadata_eval_gate` ;
- `pedago_interface_contract_gate` ;
- `source_admission_policy_gate` ;
- `human_source_review_gate` ;
- `make_target_safety_gate` ;
- `metadata_preflight_gate` ;
- `project_doctor_gate`.

Décisions de transition vérifiées :

- `continue_metadata_only` ;
- `require_human_signoff` ;
- `defer_real_corpus_lot` ;
- `do_not_proceed`.

Preuves de couverture ajoutées :

- `gate_evidence` ajouté : oui ;
- couverture complète des gates prouvée : oui ;
- `evidence_ref` sans URL ni document réel vérifié : oui ;
- `safe_target` sans cible sensible vérifié : oui ;
- cohérence `gate_status` / `decision` vérifiée : oui.

## 6. Script controlled_readiness_audit.py

Le script :

- lit `configs/controlled_readiness.yml` ;
- vérifie les références 17C/17D/17E/17F/17G ;
- vérifie que toutes les autorisations dangereuses sont à `false` ;
- vérifie les gates requis ;
- vérifie une preuve `gate_evidence` pour chaque gate requis ;
- vérifie que chaque preuve pointe vers un artefact metadata-only ou une cible sûre connue ;
- interdit les URLs, documents réels, `data/staging`, `file_path` et `source_uri` dans `evidence_ref` ;
- interdit les termes sensibles dans `safe_target` ;
- vérifie les décisions de transition autorisées ;
- vérifie la cohérence stricte `gate_status` / `decision` ;
- vérifie les champs de transition obligatoires ;
- vérifie que `transition_id` est non vide et unique ;
- vérifie que `gate_id` est déclaré dans `required_gates` ;
- vérifie que `gate_status` vaut `passed`, `blocked` ou `deferred` ;
- vérifie `human_signoff_required: true` ;
- interdit `real_corpus_allowed` ;
- interdit `real_file_allowed` ;
- interdit `external_url_allowed` ;
- vérifie `rollback_required: true` ;
- vérifie `next_lot_required: true` ;
- verrouille les décisions `defer_real_corpus_lot` et `require_human_signoff` ;
- interdit les champs `file_path`, `path`, `url`, `uri`, `checksum`, `sha256` réel et `content` ;
- produit uniquement du Markdown sur stdout ;
- ne lance aucun subprocess ;
- ne fait aucun réseau ;
- n’écrit aucun fichier ;
- ne lit aucun `.env` ;
- ne lit aucun document réel ;
- ne crée pas `data/staging`.

## 7. Cible Makefile

Nouvelle cible :

```makefile
controlled-readiness-audit:
	$(PY) scripts/controlled_readiness_audit.py
```

La cible est classée `SAFE_METADATA_ONLY`.

Aucune cible sensible contenant `ingest`, `ingestion`, `api`, `upload`, `download`, `sync`, `deploy`, `qdrant`, `embed` ou `embedding` n’a été ajoutée.

## 8. Tests ajoutés

Le fichier `tests/unit/test_controlled_readiness_audit.py` ajoute 79 tests couvrant :

- existence du protocole, de la configuration et du script ;
- présence de la cible Makefile ;
- classification `SAFE_METADATA_ONLY` ;
- absence de cible sensible ajoutée ;
- absence de tokens réseau, subprocess ou destructifs dans le script ;
- succès du script sur la configuration réelle ;
- refus de toutes les autorisations dangereuses à `true` ;
- refus de références 17C/17D/17E/17F/17G incorrectes ;
- refus de gate requis manquant ;
- refus de décision déclarée inconnue ;
- refus de champ de transition obligatoire manquant ;
- refus de transition malformed ;
- refus de `transition_id` vide ou dupliqué ;
- refus de `gate_id` inconnu ;
- refus de `gate_status` inconnu ;
- refus de décision inconnue ;
- refus de `decision_reason` vide ;
- refus de `human_signoff_required: false` ;
- refus de `real_corpus_allowed: true` ;
- refus de `real_file_allowed: true` ;
- refus de `external_url_allowed: true` ;
- refus de `rollback_required: false` ;
- refus de `next_lot_required: false` ;
- refus de décisions `defer_real_corpus_lot` ou `require_human_signoff` avec motif incohérent ;
- refus de `continue_metadata_only` si un corpus réel est autorisé ;
- refus des champs `file_path`, `url` et `content` ;
- config non mapping sans traceback ;
- absence de modification du statut Git ;
- absence de création de `data/staging` ;
- absence d’ouverture de `.env` ;
- CLI réelle ;
- CLI en mode `python -O` ;
- maintien de `make-target-safety-audit` au vert.
- présence et structure de `gate_evidence` ;
- couverture exacte de tous les gates requis ;
- rejet des preuves de gate manquantes, inconnues ou dupliquées ;
- rejet des `evidence_ref` contenant URL, document réel, `data/staging` ou `source_uri` ;
- rejet des `safe_target` contenant une cible sensible ;
- cohérence stricte entre `gate_status` et `decision`.

## 9. Résultat du controlled-readiness-audit

Résultat ciblé observé :

- `readiness_ready_for_review: true` ;
- `transition_checks_count: 3` ;
- `passed_gates_count: 1` ;
- `deferred_gates_count: 1` ;
- `blocked_gates_count: 1` ;
- `dangerous_flags_enabled_count: 0` ;
- `missing_required_gates_count: 0` ;
- `missing_required_fields_count: 0` ;
- `malformed_transition_checks_count: 0` ;
- `transition_identity_errors_count: 0` ;
- `transition_decision_errors_count: 0` ;
- `transition_safety_errors_count: 0` ;
- `forbidden_transition_fields_count: 0` ;
- `gate_evidence_errors_count: 0` ;
- `gate_coverage_errors_count: 0` ;
- `sensitive_target_errors_count: 0` ;
- `transition_status_decision_errors_count: 0` ;
- `destructive_action_available: false`.

Validation ciblée :

- `python3 -m ruff check scripts/controlled_readiness_audit.py tests/unit/test_controlled_readiness_audit.py` : OK ;
- `pytest tests/unit/test_controlled_readiness_audit.py -q` : 79 passed ;
- `make controlled-readiness-audit` : OK.

## 10. Résultat du make-target-safety-audit

Résultat ciblé observé après ajout de la nouvelle cible :

- `all_targets_classified: true` ;
- `phony_targets_count: 48` ;
- `rule_targets_count: 48` ;
- `SAFE_METADATA_ONLY: 13` ;
- `unclassified_targets_count: 0` ;
- `unsafe_safe_classifications_count: 0` ;
- `suspicious_safe_classifications_count: 0` ;
- `targets_executed: false`.

Validation complète sûre :

- ruff complet : OK ;
- tests cleanup dry-run : 10 passed ;
- tests cleanup review : 15 passed ;
- tests cleanup decision draft : 13 passed ;
- tests make target safety : 29 passed ;
- tests pilot corpus scope : 31 passed ;
- tests retrieval metadata eval : 52 passed ;
- tests pedago interface contract : 56 passed ;
- tests source admission policy : 65 passed ;
- tests human source review : 67 passed ;
- tests controlled readiness : 79 passed ;
- `make cleanup-dry-run` : OK ;
- `make cleanup-review` : OK ;
- `make cleanup-decision-draft` : OK ;
- `make make-target-safety-audit` : OK ;
- `make pilot-corpus-scope-audit` : OK ;
- `make retrieval-metadata-eval-audit` : OK ;
- `make pedago-interface-contract-audit` : OK ;
- `make source-admission-policy-audit` : OK ;
- `make human-source-review-audit` : OK ;
- `make controlled-readiness-audit` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 787 passed in 99.96s.

## 11. Garanties non destructives

- aucun document réel lu ;
- aucun PDF copié ;
- aucun DOCX copié ;
- aucun PPTX copié ;
- aucun XLSX copié ;
- aucun PDF/DOCX/PPTX/XLSX copié ;
- aucune source réelle admise ;
- aucune ingestion lancée ;
- aucun parsing lancé ;
- aucun chunking lancé ;
- aucun embedding créé ;
- aucun Qdrant touché ;
- aucun réseau ;
- aucun `.env` ouvert ;
- aucun `data/staging` créé ;
- `rag-local` non modifié.

## 12. Risques restants

- La transition reste déclarative : elle n’autorise aucune source réelle.
- Tout futur lot réel devra être séparé, nominatif, validé humainement, et inclure droits, chemins contrôlés, checksums, rollback, parsing, chunking, embeddings, Qdrant et validations dédiées.

## 12 bis. Synthèse de conformité

- verdict READY_FOR_CONTROLLED_READINESS_REVIEW ;
- protocole CONTROLLED_READINESS créé : oui ;
- configuration controlled_readiness créée : oui ;
- script d’audit créé : oui ;
- cible Makefile créée : oui ;
- cible classée SAFE_METADATA_ONLY : oui ;
- aucune cible sensible ajoutée : oui ;
- références 17C/17D/17E/17F/17G vérifiées : oui ;
- gates requis vérifiés : oui ;
- gate_evidence ajouté : oui ;
- couverture complète des gates prouvée : oui ;
- evidence_ref sans URL ni document réel vérifié : oui ;
- safe_target sans cible sensible vérifié : oui ;
- cohérence gate_status / decision vérifiée : oui ;
- décisions de transition vérifiées : oui ;
- champs transition obligatoires vérifiés : oui ;
- transition_id unique vérifié : oui ;
- gate_id vérifié : oui ;
- gate_status vérifié : oui ;
- human_signoff_required vérifié : oui ;
- real_corpus_allowed interdit : oui ;
- real_file_allowed interdit : oui ;
- external_url_allowed interdit : oui ;
- rollback_required vérifié : oui ;
- next_lot_required vérifié : oui ;
- décisions defer/require signoff verrouillées : oui ;
- champs file/url/content interdits : oui ;
- config non mapping sans traceback : oui ;
- make test : 787 passed ;
- aucun document réel lu ;
- aucun PDF/DOCX/PPTX/XLSX copié ;
- aucune source réelle admise ;
- aucune ingestion ;
- aucun parsing ;
- aucun chunking ;
- aucun embedding ;
- aucun Qdrant ;
- aucun réseau ;
- aucun .env ouvert ;
- aucun data/staging créé ;
- rag-local non modifié.

## 13. Verdict

READY_FOR_CONTROLLED_READINESS_REVIEW

## 14. Recommandation pour 17I

Préparer uniquement un lot de revue humaine ou de cadrage metadata-only supplémentaire, sans source réelle ni manipulation documentaire tant qu’un lot réel séparé n’est pas explicitement validé.
