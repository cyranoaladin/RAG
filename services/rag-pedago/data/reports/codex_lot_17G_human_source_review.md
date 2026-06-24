# Rapport Codex — Lot 17G : revue humaine metadata-only des sources

## 1. Objectif

Le lot 17G définit une procédure déclarative de revue humaine avant toute admission réelle de source pédagogique.

Le lot reste metadata-only, offline et non destructif : aucune source réelle n’est admise, aucun document réel n’est lu ou copié, aucune ingestion n’est lancée, aucun parsing, chunking, embedding ou Qdrant n’est utilisé, et aucun `data/staging` n’est créé.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `c4dcd1f feat: add source admission policy audit` ;
- `git status --short --branch` initial : `## main` ;
- `make make-target-safety-audit` : OK ;
- `make pilot-corpus-scope-audit` : OK ;
- `make retrieval-metadata-eval-audit` : OK ;
- `make pedago-interface-contract-audit` : OK ;
- `make source-admission-policy-audit` : OK ;
- `make cleanup-dry-run` : OK ;
- `make cleanup-review` : OK ;
- `make cleanup-decision-draft` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : 641 passed in 98.46s.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/HUMAN_SOURCE_REVIEW_PROTOCOL.md` ;
- `configs/human_source_review.yml` ;
- `scripts/human_source_review_audit.py` ;
- `tests/unit/test_human_source_review_audit.py` ;
- `data/reports/codex_lot_17G_human_source_review.md`.

Fichiers modifiés :

- `Makefile` : ajout de `human-source-review-audit` ;
- `configs/make_target_safety.yml` : classification en `SAFE_METADATA_ONLY` ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` : mention de la nouvelle cible sûre.

## 4. Protocole HUMAN_SOURCE_REVIEW

Le protocole `docs/HUMAN_SOURCE_REVIEW_PROTOCOL.md` définit :

- les rôles de revue humaine ;
- les étapes de revue ;
- les décisions de revue autorisées ;
- les conditions minimales d’approbation ;
- les conditions avant admission réelle ;
- les interdictions metadata-only.

## 5. Configuration human_source_review.yml

La configuration `configs/human_source_review.yml` est déclarative uniquement.

Elle fixe :

- `review_policy_id: human_source_review_metadata_policy_v1` ;
- `status: metadata_only_human_source_review` ;
- `source_admission_policy_ref: source_admission_metadata_policy_v1` ;
- `pilot_scope_ref: math_terminale_specialite_metadata_only_v1` ;
- `retrieval_eval_ref: math_terminale_specialite_metadata_retrieval_eval_v1` ;
- `pedago_interface_ref: pedago_interface_metadata_contract_v1`.

Toutes les autorisations dangereuses valent `false`.

Sources connues verrouillées :

- `official_programme_metadata_reference` ;
- `refused_unknown_rights_example` ;
- `future_real_source_placeholder`.

Rôles de revue verrouillés :

- `reviewer_pedagogique` ;
- `reviewer_droits` ;
- `reviewer_technique` ;
- `responsable_validation`.

Décisions de revue verrouillées :

- `approve_metadata_only` ;
- `reject_real_document` ;
- `reject_unknown_rights` ;
- `reject_private_data` ;
- `request_more_information` ;
- `defer_until_real_source_lot`.

## 6. Script human_source_review_audit.py

Le script :

- lit `configs/human_source_review.yml` ;
- vérifie les références 17C, 17D, 17E et 17F ;
- vérifie que toutes les autorisations dangereuses sont à `false` ;
- vérifie que `known_source_ids` est non vide, sans doublon et couvre les sources revues ;
- vérifie les rôles requis ;
- vérifie la couverture effective de chaque rôle requis dans `review_cases` ;
- vérifie les décisions autorisées ;
- vérifie les champs de revue obligatoires ;
- vérifie que `review_id` est non vide et unique ;
- vérifie que `source_id` est non vide ;
- vérifie `reviewer_role` ;
- vérifie `decision_reason` ;
- vérifie `human_validation_required: true` ;
- vérifie `no_real_file_confirmed: true` ;
- vérifie `no_external_url_confirmed: true` ;
- vérifie les checks nécessaires pour `approve_metadata_only` ;
- exige que `approve_metadata_only` soit porté par `responsable_validation` ;
- verrouille les cas de rejet ;
- verrouille les cas `defer_until_real_source_lot` sur `responsable_validation` ;
- interdit les conflits de décision par source ;
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
human-source-review-audit:
	$(PY) scripts/human_source_review_audit.py
```

La cible est classée `SAFE_METADATA_ONLY`.

Aucune cible sensible contenant `ingest`, `ingestion`, `api`, `upload`, `download`, `sync`, `deploy`, `qdrant`, `embed` ou `embedding` n’a été ajoutée.

## 8. Tests ajoutés

Le fichier `tests/unit/test_human_source_review_audit.py` ajoute 67 tests couvrant :

- existence du protocole, de la configuration et du script ;
- présence de la cible Makefile ;
- classification `SAFE_METADATA_ONLY` ;
- absence de cible sensible ajoutée ;
- absence de tokens réseau, subprocess ou destructifs dans le script ;
- succès du script sur la configuration réelle ;
- refus de toutes les autorisations dangereuses à `true` ;
- refus de références de politique incorrectes ;
- refus de `known_source_ids` absent, vide ou dupliqué ;
- refus d’un `source_id` inconnu ;
- refus de rôle requis manquant ;
- refus de couverture de rôle incomplète ;
- refus de décision déclarée inconnue ;
- refus de champ de revue obligatoire manquant ;
- refus de `review_id` vide ou dupliqué ;
- refus de `reviewer_role` inconnu ;
- refus de décision inconnue ;
- refus de `decision_reason` vide ;
- refus de validation humaine absente ;
- refus d’un fichier réel non confirmé absent ;
- refus d’une URL externe non confirmée absente ;
- refus d’approbation metadata-only sans checks complets ;
- refus d’approbation metadata-only portée par un rôle non responsable ;
- refus des cas de rejet avec motif incohérent ;
- refus des cas différés portés par un rôle non responsable ;
- refus des conflits approbation/rejet ou approbation/différé sur une même source ;
- refus des champs `file_path`, `url` et `content` ;
- config non mapping sans traceback ;
- absence de modification du statut Git ;
- absence de création de `data/staging` ;
- absence d’ouverture de `.env` ;
- CLI réelle ;
- CLI en mode `python -O` ;
- maintien de `make-target-safety-audit` au vert.

## 9. Résultat du human-source-review-audit

Résultat ciblé observé :

- `review_ready_for_review: true` ;
- `review_cases_count: 5` ;
- `approved_metadata_only_count: 1` ;
- `rejected_cases_count: 1` ;
- `deferred_cases_count: 1` ;
- `dangerous_flags_enabled_count: 0` ;
- `missing_required_roles_count: 0` ;
- `missing_required_fields_count: 0` ;
- `malformed_review_cases_count: 0` ;
- `review_identity_errors_count: 0` ;
- `review_decision_errors_count: 0` ;
- `review_check_errors_count: 0` ;
- `forbidden_review_fields_count: 0` ;
- `known_source_errors_count: 0` ;
- `role_coverage_errors_count: 0` ;
- `source_decision_conflicts_count: 0` ;
- `destructive_action_available: false`.

Validation ciblée :

- `python3 -m ruff check scripts/human_source_review_audit.py tests/unit/test_human_source_review_audit.py` : OK ;
- `pytest tests/unit/test_human_source_review_audit.py -q` : 67 passed ;
- `make human-source-review-audit` : OK.

## 10. Résultat du make-target-safety-audit

Résultat ciblé observé après ajout de la nouvelle cible :

- `all_targets_classified: true` ;
- `phony_targets_count: 47` ;
- `rule_targets_count: 47` ;
- `SAFE_METADATA_ONLY: 12` ;
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
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 708 passed in 103.13s.

Durcissement 17G-Fix :

- known_source_ids ajouté : oui ;
- source_id connus vérifiés : oui ;
- couverture des rôles vérifiée : oui ;
- validation responsable exigée pour approve_metadata_only : oui ;
- conflits de décisions par source vérifiés : oui ;
- cas deferred verrouillés : oui ;
- known_source_errors_count: 0 ;
- role_coverage_errors_count: 0 ;
- source_decision_conflicts_count: 0.

## 11. Garanties non destructives

- aucun document réel lu ;
- aucun PDF copié ;
- aucun DOCX copié ;
- aucun PPTX copié ;
- aucun XLSX copié ;
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

- La procédure reste déclarative : elle ne valide pas encore des fichiers réels.
- Toute admission réelle doit rester lotie séparément avec droits, fichiers, checksums, parsing, chunking, embeddings, Qdrant et rollback explicitement validés.

Checklist de conformité avant commit :

- verdict READY_FOR_HUMAN_SOURCE_REVIEW ;
- protocole HUMAN_SOURCE_REVIEW créé ;
- configuration human_source_review créée ;
- script d’audit créé ;
- cible Makefile créée ;
- cible classée SAFE_METADATA_ONLY ;
- aucune cible sensible ajoutée ;
- known_source_ids ajouté ;
- source_id connus vérifiés ;
- couverture des rôles vérifiée ;
- validation responsable exigée pour approve_metadata_only ;
- conflits de décisions par source vérifiés ;
- cas deferred verrouillés ;
- rôles de revue verrouillés ;
- décisions de revue verrouillées ;
- champs review obligatoires vérifiés ;
- review_id unique vérifié ;
- reviewer_role vérifié ;
- decision_reason vérifié ;
- human_validation_required vérifié ;
- no_real_file_confirmed vérifié ;
- no_external_url_confirmed vérifié ;
- checks approve_metadata_only vérifiés ;
- cas de rejet verrouillés ;
- champs file/url/content interdits ;
- config non mapping sans traceback ;
- make test : 708 passed ;
- aucun document réel lu ;
- aucun PDF/DOCX/PPTX/XLSX copié ;
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

READY_FOR_HUMAN_SOURCE_REVIEW

## 14. Recommandation pour 17H

Préparer uniquement un lot metadata-only ou un protocole de transition vers un futur lot de sources réelles, sans admettre de source réelle ni manipuler de document.
