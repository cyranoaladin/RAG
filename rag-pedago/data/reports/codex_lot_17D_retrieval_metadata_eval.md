# Rapport Codex — Lot 17D : évaluation retrieval metadata-only

## 1. Objectif

Le lot 17D prépare une première évaluation retrieval strictement metadata-only pour le périmètre pilote mathématiques terminale spécialité.

L’objectif est de cadrer des requêtes pédagogiques synthétiques, leurs filtres metadata attendus, les contraintes de droits et visibilité, les exigences de citation et les cas de refus, sans moteur retrieval réel.

## 2. Point de départ

- dépôt actif : `/home/alaeddine/Bureau/RAG/rag-pedago` ;
- HEAD initial : `48c1359 feat: add pilot corpus scope audit` ;
- dépôt historique `rag-local` vérifié en lecture seule ;
- validations initiales sûres exécutées avant modification : `make make-target-safety-audit`, `make pilot-corpus-scope-audit`, `make cleanup-dry-run`, `make cleanup-review`, `make cleanup-decision-draft`, `make metadata-preflight`, `make doctor`, `make project-doctor`, `make test` ;
- `make test` initial : 468 passed.

## 3. Fichiers créés ou modifiés

- `Makefile` : ajout de la cible sûre `retrieval-metadata-eval-audit` ;
- `configs/make_target_safety.yml` : classification de `retrieval-metadata-eval-audit` en `SAFE_METADATA_ONLY` ;
- `configs/retrieval_metadata_eval.yml` : configuration déclarative de l’évaluation metadata-only ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` : mention de la nouvelle cible sûre ;
- `docs/RETRIEVAL_METADATA_EVAL_PROTOCOL.md` : protocole d’évaluation retrieval metadata-only ;
- `scripts/retrieval_metadata_eval_audit.py` : audit non destructif de la configuration ;
- `tests/unit/test_retrieval_metadata_eval_audit.py` : tests unitaires du protocole, de la configuration, du script, de la cible Makefile et des garanties ;
- `data/reports/codex_lot_17D_retrieval_metadata_eval.md` : présent rapport.

Synthèse explicite du périmètre 17D :

- protocole RETRIEVAL_METADATA_EVAL créé : oui ;
- configuration retrieval_metadata_eval créée : oui ;
- script d’audit créé : oui ;
- cible Makefile créée : oui ;
- cible classée SAFE_METADATA_ONLY : oui ;
- eval-retrieval reste FUTURE_NOT_READY : oui.

## 4. Protocole RETRIEVAL_METADATA_EVAL

Le protocole définit une évaluation autorisée uniquement sur :

- requêtes synthétiques ;
- profils élèves synthétiques ;
- filtres metadata attendus ;
- exigences de citation ;
- critères de pertinence pédagogique ;
- cas de refus ;
- cohérence déclarative.

Il interdit explicitement les documents réels, PDF, DOCX, PPTX, XLSX, ingestion, parsing, chunking, embeddings, Qdrant, réseau, génération de réponse finale et `data/staging`.

## 5. Configuration retrieval_metadata_eval.yml

La configuration `retrieval_metadata_eval.yml` contient :

- `eval_id: math_terminale_specialite_metadata_retrieval_eval_v1` ;
- `status: metadata_only_eval` ;
- `pilot_scope_ref: math_terminale_specialite_metadata_only_v1` ;
- toutes les autorisations dangereuses à `false` ;
- des champs de filtres obligatoires ;
- des champs de cas obligatoires ;
- une politique de citation stricte ;
- 6 cas synthétiques, dont 4 cas `metadata_filter_only` et 2 cas de refus.

`eval-retrieval` reste classée `FUTURE_NOT_READY` et n’a pas été lancée.

## 6. Script retrieval_metadata_eval_audit.py

Le script :

- lit uniquement la configuration YAML ;
- vérifie `status: metadata_only_eval` ;
- vérifie que les autorisations dangereuses restent à `false` ;
- vérifie `answer_generation_allowed: false` ;
- vérifie `embeddings_allowed: false` ;
- vérifie `qdrant_allowed: false` ;
- vérifie `real_documents_allowed: false` ;
- vérifie les champs obligatoires des cas ;
- vérifie `REQUIRED_STUDENT_PROFILE_VALUES` pour chaque profil élève ;
- vérifie les comportements attendus autorisés ;
- vérifie que les cas `metadata_filter_only` ont des `expected_filters` complets ;
- vérifie les droits retrieval (`allowed_for_retrieval`) ;
- vérifie la visibilité `student_visible` ;
- vérifie les notions non vides ;
- vérifie les compétences non vides ;
- vérifie que les citations sont exigées ;
- vérifie `expected_citation_policy` par cas ;
- vérifie que `answer_without_source_allowed: false` ;
- vérifie les critères pédagogiques ;
- verrouille les cas de refus avec `expected_filters: {}` et critères `must_refuse_*` ou `no_answer_generation` ;
- traite une configuration non mapping sans traceback ;
- produit uniquement du Markdown sur stdout ;
- ne lance aucun subprocess ;
- n’écrit aucun fichier ;
- ne lit aucun `.env` ;
- ne lit aucun document réel ;
- ne crée pas `data/staging`.

## 7. Cible Makefile

Nouvelle cible :

```makefile
retrieval-metadata-eval-audit:
	$(PY) scripts/retrieval_metadata_eval_audit.py
```

La cible est classée `SAFE_METADATA_ONLY` dans `configs/make_target_safety.yml`.

## 8. Tests ajoutés

Les tests ajoutés couvrent :

- présence du protocole, de la configuration et du script ;
- présence de la cible Makefile ;
- classification `SAFE_METADATA_ONLY` ;
- maintien de `eval-retrieval` en `FUTURE_NOT_READY` ;
- absence de tokens réseau, subprocess et destructifs dans le script ;
- succès du script sur la configuration réelle ;
- sortie Markdown attendue ;
- interdiction des embeddings, Qdrant, documents réels et génération de réponse ;
- citations obligatoires ;
- refus de `answer_without_source_allowed: true` ;
- refus d’un cas `metadata_filter_only` sans filtres ;
- refus de filtres incomplets ou incohérents ;
- refus de profils élèves incohérents avec le scope 17C ;
- refus de politiques de citation par cas mal typées ou permissives ;
- refus de critères pédagogiques vides ou incomplets ;
- refus de cas de refus avec filtres exploitables ou génération attendue ;
- refus d’une configuration YAML non mapping sans traceback ;
- refus d’un comportement inconnu ;
- refus d’un cas mal formé ;
- non-modification du statut Git ;
- absence de création de `data/staging` ;
- absence d’ouverture de `.env` ;
- exécution CLI réelle ;
- exécution CLI en mode `python3 -O` ;
- maintien de `make-target-safety-audit` au vert.

Résultats finaux :

- `python3 -m ruff check ...` : OK ;
- `pytest tests/unit/test_retrieval_metadata_eval_audit.py -q` : 52 passed ;
- `make test` : 520 passed in 89.85s.

## 9. Résultat du retrieval-metadata-eval-audit

Résultat ciblé :

- `eval_ready_for_review: true` ;
- `cases_count: 6` ;
- `metadata_filter_cases_count: 4` ;
- `refusal_cases_count: 2` ;
- `dangerous_flags_enabled_count: 0` ;
- `missing_required_filter_fields_count: 0` ;
- `malformed_cases_count: 0` ;
- `invalid_expected_behaviors_count: 0` ;
- `citation_policy_errors_count: 0` ;
- `student_profile_errors_count: 0` ;
- `expected_filter_errors_count: 0` ;
- `case_citation_policy_errors_count: 0` ;
- `pedagogical_criteria_errors_count: 0` ;
- `refusal_case_errors_count: 0` ;
- `answer_generation_allowed: false` ;
- `embeddings_allowed: false` ;
- `qdrant_allowed: false` ;
- `real_documents_allowed: false` ;
- `destructive_action_available: false`.

Durcissements 17D-Fix :

- REQUIRED_STUDENT_PROFILE_VALUES ajouté : oui ;
- expected_filters complets vérifiés : oui ;
- droits retrieval vérifiés : oui ;
- visibilité `student_visible` vérifiée : oui ;
- notions non vides vérifiées : oui ;
- compétences non vides vérifiées : oui ;
- `expected_citation_policy` par cas vérifiée : oui ;
- critères pédagogiques vérifiés : oui ;
- cas de refus verrouillés : oui ;
- config non mapping sans traceback : oui ;
- `student_profile_errors_count: 0` ;
- `expected_filter_errors_count: 0` ;
- `case_citation_policy_errors_count: 0` ;
- `pedagogical_criteria_errors_count: 0` ;
- `refusal_case_errors_count: 0`.

Garanties fonctionnelles du scope retrieval metadata-only :

- évaluation metadata-only validée : oui ;
- embeddings interdits : oui ;
- Qdrant interdit : oui ;
- documents réels interdits : oui ;
- génération de réponse interdite : oui ;
- citations obligatoires : oui.

## 10. Résultat du make-target-safety-audit

Résultat ciblé après ajout de la nouvelle cible :

- `all_targets_classified: true` ;
- `phony_targets_count: 44` ;
- `rule_targets_count: 44` ;
- `all_make_targets_count: 44` ;
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
- `targets_executed: false`.

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
- aucune réponse générée ;
- aucun réseau ;
- aucun `.env` ouvert ;
- aucun `data/staging` créé ;
- `rag-local` non modifié.

## 12. Risques restants

- L’évaluation reste déclarative : aucun scoring retrieval réel n’est encore mesuré.
- Aucun corpus réel validé n’est disponible pour calculer des métriques de rappel, précision ou citation.
- Les libellés metadata devront être revérifiés avant tout passage à un moteur retrieval réel.
- Les cas synthétiques devront être enrichis par un golden set validé humainement avant usage produit.

## 13. Verdict

READY_FOR_RETRIEVAL_METADATA_EVAL_REVIEW

## 14. Recommandation pour 17E

Préparer la spécification API/UI pédagogique metadata-only : workflows élève et enseignant, exigences de citation, refus contrôlés, traçabilité des sources et séparation stricte entre revue déclarative et retrieval réel.
