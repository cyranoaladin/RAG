# Rapport Codex — Lot 17I : autorisation de transition metadata-only

## 1. Objectif

Le lot 17I définit une couche déclarative d'autorisation avant tout futur lot réel séparé.

Il répond à la question : quelles conditions déclaratives, humaines et techniques doivent être remplies avant d'autoriser un futur lot réel séparé ?

Le lot reste strictement metadata-only, déclaratif, offline et non destructif.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `6befc2d feat: add controlled readiness audit` ;
- `git status --short --branch` initial : `## main` ;
- `make make-target-safety-audit` : OK ;
- `make pilot-corpus-scope-audit` : OK ;
- `make retrieval-metadata-eval-audit` : OK ;
- `make pedago-interface-contract-audit` : OK ;
- `make source-admission-policy-audit` : OK ;
- `make human-source-review-audit` : OK ;
- `make controlled-readiness-audit` : OK ;
- `make cleanup-dry-run` : OK ;
- `make cleanup-review` : OK ;
- `make cleanup-decision-draft` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : 787 passed in 100.93s.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/TRANSITION_AUTHORIZATION_PROTOCOL.md` ;
- `configs/transition_authorization.yml` ;
- `scripts/transition_authorization_audit.py` ;
- `tests/unit/test_transition_authorization_audit.py` ;
- `data/reports/codex_lot_17I_transition_authorization.md`.

Fichiers modifiés :

- `Makefile` : ajout de `transition-authorization-audit` ;
- `configs/make_target_safety.yml` : classification en `SAFE_METADATA_ONLY` ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` : mention de la nouvelle cible sûre.

## 4. Protocole TRANSITION_AUTHORIZATION

Le protocole `docs/TRANSITION_AUTHORIZATION_PROTOCOL.md` définit :

- les conditions d'autorisation d'un futur lot réel séparé ;
- les décisions d'autorisation autorisées ;
- les conditions bloquantes ;
- les interdictions metadata-only ;
- les conditions minimales avant tout futur lot réel.

## 5. Configuration transition_authorization.yml

La configuration `configs/transition_authorization.yml` est déclarative uniquement.

Elle fixe :

- `authorization_id: transition_authorization_metadata_policy_v1` ;
- `status: metadata_only_transition_authorization` ;
- `controlled_readiness_ref: controlled_readiness_metadata_gate_v1` ;
- `human_source_review_ref: human_source_review_metadata_policy_v1` ;
- `source_admission_policy_ref: source_admission_metadata_policy_v1` ;
- `pedago_interface_ref: pedago_interface_metadata_contract_v1` ;
- `retrieval_eval_ref: math_terminale_specialite_metadata_retrieval_eval_v1` ;
- `pilot_scope_ref: math_terminale_specialite_metadata_only_v1`.

Toutes les autorisations dangereuses valent `false`.

Décisions d'autorisation verrouillées :

- `authorize_metadata_only_preparation` ;
- `require_final_human_signoff` ;
- `block_real_corpus_transition` ;
- `defer_to_separate_real_lot`.

Cas `defer_to_separate_real_lot` ajouté :

- `authorization_case_id: separate_real_lot_deferred` ;
- `decision_reason: separate_real_lot_required` ;
- `real_corpus_authorized: false` ;
- `real_file_authorized: false` ;
- `pipeline_authorized: false`.

## 6. Script transition_authorization_audit.py

Le script :

- lit `configs/transition_authorization.yml` ;
- vérifie les références 17C à 17H ;
- vérifie que toutes les autorisations dangereuses sont à `false` ;
- vérifie les champs d'autorisation obligatoires ;
- vérifie les décisions d'autorisation autorisées ;
- vérifie la couverture complète des décisions d'autorisation critiques ;
- vérifie chaque `authorization_case` ;
- vérifie que `authorization_cases` est une liste non vide ;
- vérifie que chaque `authorization_case` est un mapping ;
- vérifie que `authorization_case_id` est non vide et unique ;
- vérifie que `readiness_gate` vaut `controlled_readiness_metadata_gate_v1` ;
- vérifie que `decision` est autorisée ;
- vérifie que `decision_reason` est non vide ;
- vérifie `final_human_signoff_required: true` ;
- vérifie `rights_confirmation_required: true` ;
- vérifie `provenance_confirmation_required: true` ;
- vérifie `pii_absence_required: true` ;
- vérifie `rollback_plan_required: true` ;
- vérifie `checksum_plan_required: true` ;
- vérifie `separate_real_lot_required: true` ;
- interdit `real_corpus_authorized` ;
- interdit `real_file_authorized` ;
- interdit `pipeline_authorized` ;
- verrouille les raisons de décision ;
- verrouille la raison `defer_to_separate_real_lot: separate_real_lot_required` ;
- interdit les champs `file_path`, `path`, `source_uri`, `url`, `uri`, `checksum`, `sha256` réel et `content` ;
- produit uniquement du Markdown sur stdout ;
- ne lance aucun subprocess ;
- ne fait aucun réseau ;
- n'écrit aucun fichier ;
- ne lit aucun `.env` ;
- ne lit aucun document réel ;
- ne crée pas `data/staging`.

## 7. Cible Makefile

Nouvelle cible :

```makefile
transition-authorization-audit:
	$(PY) scripts/transition_authorization_audit.py
```

La cible est classée `SAFE_METADATA_ONLY`.

Aucune cible sensible contenant `ingest`, `ingestion`, `api`, `upload`, `download`, `sync`, `deploy`, `qdrant`, `embed`, `embedding`, `scrape`, `backup` ou `watch` n'a été ajoutée.

## 8. Tests ajoutés

Le fichier `tests/unit/test_transition_authorization_audit.py` ajoute 65 tests couvrant :

- existence du protocole, de la configuration et du script ;
- présence de la cible Makefile ;
- classification `SAFE_METADATA_ONLY` ;
- absence de cible sensible ajoutée ;
- absence de tokens réseau, subprocess ou destructifs dans le script ;
- succès du script sur la configuration réelle ;
- refus de toutes les autorisations dangereuses à `true` ;
- refus de références 17C à 17H incorrectes ;
- refus de décision déclarée inconnue ;
- refus de champ obligatoire manquant ;
- refus de `authorization_cases` absent, vide, non-list ou avec entrée non-mapping ;
- refus de décision autorisée non couverte par un cas ;
- refus de `authorization_case_id` vide ou dupliqué ;
- refus de `readiness_gate` incorrect ;
- refus de décision inconnue ;
- refus de `decision_reason` vide ;
- refus des validations humaines, droits, provenance, PII, rollback, checksum et lot séparé absents ;
- refus de corpus réel, fichier réel ou pipeline autorisé ;
- refus des raisons de décision incohérentes ;
- refus de raison incohérente pour `defer_to_separate_real_lot` ;
- acceptation de `defer_to_separate_real_lot` avec `decision_reason: separate_real_lot_required` ;
- refus des champs `file_path`, `source_uri`, `url` et `content` ;
- config non mapping sans traceback ;
- absence de modification du statut Git ;
- absence de création de `data/staging` ;
- absence d'ouverture de `.env` ;
- CLI réelle ;
- CLI en mode `python -O` ;
- maintien de `make-target-safety-audit` au vert.

## 9. Résultat du transition-authorization-audit

Résultat ciblé observé :

- `authorization_ready_for_review: true` ;
- `authorization_cases_count: 4` ;
- `metadata_only_authorized_count: 1` ;
- `blocked_real_corpus_count: 1` ;
- `human_signoff_required_count: 1` ;
- `deferred_real_lot_count: 1` ;
- `dangerous_flags_enabled_count: 0` ;
- `missing_required_fields_count: 0` ;
- `malformed_authorization_cases_count: 0` ;
- `authorization_identity_errors_count: 0` ;
- `authorization_decision_errors_count: 0` ;
- `authorization_decision_coverage_errors_count: 0` ;
- `authorization_safety_errors_count: 0` ;
- `forbidden_authorization_fields_count: 0` ;
- `destructive_action_available: false`.

Validation ciblée :

- `python3 -m ruff check scripts/transition_authorization_audit.py tests/unit/test_transition_authorization_audit.py` : OK ;
- `pytest tests/unit/test_transition_authorization_audit.py -q` : 65 passed ;
- `make transition-authorization-audit` : OK.

## 10. Résultat du make-target-safety-audit

Résultat ciblé observé après ajout de la nouvelle cible :

- `all_targets_classified: true` ;
- `phony_targets_count: 49` ;
- `rule_targets_count: 49` ;
- `SAFE_METADATA_ONLY: 14` ;
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
- tests transition authorization : 65 passed ;
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
- `make transition-authorization-audit` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 852 passed in 111.00s.

## 11. Garanties non destructives

- aucun document réel lu ;
- aucun PDF copié ;
- aucun DOCX copié ;
- aucun PPTX copié ;
- aucun XLSX copié ;
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

- La couche d'autorisation reste déclarative : elle n'autorise aucune source réelle.
- Tout futur lot réel devra être séparé, nominatif, validé humainement, et inclure droits, chemins contrôlés, checksums, rollback, parsing, chunking, embeddings, Qdrant et validations dédiées.

Synthèse de conformité avant revue :

- verdict READY_FOR_TRANSITION_AUTHORIZATION_REVIEW ;
- cas defer_to_separate_real_lot ajouté : oui ;
- raison defer_to_separate_real_lot verrouillée : oui ;
- couverture complète des décisions d'autorisation vérifiée : oui ;
- authorization_cases non vide vérifié : oui ;
- source_uri interdit : oui ;
- authorization_decision_coverage_errors_count: 0 ;
- malformed_authorization_cases_count: 0 ;
- protocole TRANSITION_AUTHORIZATION créé : oui ;
- configuration transition_authorization créée : oui ;
- script d'audit créé : oui ;
- cible Makefile créée : oui ;
- cible classée SAFE_METADATA_ONLY : oui ;
- aucune cible sensible ajoutée : oui ;
- références 17C à 17H vérifiées : oui ;
- décisions d'autorisation vérifiées : oui ;
- champs authorization obligatoires vérifiés : oui ;
- authorization_case_id unique vérifié : oui ;
- readiness_gate vérifié : oui ;
- final_human_signoff_required vérifié : oui ;
- rights_confirmation_required vérifié : oui ;
- provenance_confirmation_required vérifié : oui ;
- pii_absence_required vérifié : oui ;
- rollback_plan_required vérifié : oui ;
- checksum_plan_required vérifié : oui ;
- separate_real_lot_required vérifié : oui ;
- real_corpus_authorized interdit : oui ;
- real_file_authorized interdit : oui ;
- pipeline_authorized interdit : oui ;
- raisons de décision verrouillées : oui ;
- champs file/url/content/source_uri interdits : oui ;
- config non mapping sans traceback : oui ;
- make test : 852 passed ;
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

READY_FOR_TRANSITION_AUTHORIZATION_REVIEW

## 14. Recommandation pour 17J

Préparer uniquement un lot metadata-only de durcissement ou de revue de l'autorisation, sans admettre de source réelle ni manipuler de document tant qu'un lot réel séparé n'est pas explicitement validé.
