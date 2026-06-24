# Rapport Codex — Lot 17F : admission des sources pédagogiques metadata-only

## 1. Objectif

Le lot 17F définit une politique déclarative d’admission des sources pédagogiques avant tout corpus réel.

Le lot reste metadata-only, offline et non destructif : aucun document réel n’est lu ou copié, aucune ingestion n’est lancée, aucun parsing, chunking, embedding ou Qdrant n’est utilisé, et aucun `data/staging` n’est créé.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `95b9ed8 feat: add pedago interface contract audit` ;
- `git status --short --branch` initial : `## main` ;
- `make make-target-safety-audit` : OK ;
- `make pilot-corpus-scope-audit` : OK ;
- `make retrieval-metadata-eval-audit` : OK ;
- `make pedago-interface-contract-audit` : OK ;
- `make cleanup-dry-run` : OK ;
- `make cleanup-review` : OK ;
- `make cleanup-decision-draft` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : 576 passed in 99.97s.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/SOURCE_ADMISSION_POLICY_PROTOCOL.md` ;
- `configs/source_admission_policy.yml` ;
- `scripts/source_admission_policy_audit.py` ;
- `tests/unit/test_source_admission_policy_audit.py` ;
- `data/reports/codex_lot_17F_source_admission_policy.md`.

Fichiers modifiés :

- `Makefile` : ajout de `source-admission-policy-audit` ;
- `configs/make_target_safety.yml` : classification en `SAFE_METADATA_ONLY` ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` : mention de la nouvelle cible sûre.

## 4. Protocole SOURCE_ADMISSION_POLICY

Le protocole `docs/SOURCE_ADMISSION_POLICY_PROTOCOL.md` définit :

- les sources admissibles metadata-only ;
- les sources interdites ;
- les champs metadata obligatoires ;
- les décisions d’admission autorisées ;
- les conditions avant tout corpus réel ;
- la cohérence métier d’admission ;
- les cas de refus documentaire.

## 5. Configuration source_admission_policy.yml

La configuration `configs/source_admission_policy.yml` est déclarative uniquement.

Elle fixe :

- `policy_id: source_admission_metadata_policy_v1` ;
- `status: metadata_only_source_admission_policy` ;
- `pilot_scope_ref: math_terminale_specialite_metadata_only_v1` ;
- `retrieval_eval_ref: math_terminale_specialite_metadata_retrieval_eval_v1` ;
- `pedago_interface_ref: pedago_interface_metadata_contract_v1`.

Toutes les autorisations dangereuses valent `false`.

Sources admissibles verrouillées :

- `official_reference_metadata` ;
- `synthetic_learning_resource` ;
- `teacher_authored_metadata` ;
- `taxonomy_reference` ;
- `codex_report` ;
- `internal_protocol`.

Sources interdites verrouillées :

- fichiers réels ;
- formats PDF/DOCX/PPTX/XLSX ;
- droits inconnus ;
- données élève réelles ;
- URL externe non auditée ;
- parsing, embeddings ou Qdrant requis.

## 6. Script source_admission_policy_audit.py

Le script :

- lit `configs/source_admission_policy.yml` ;
- vérifie les références 17C, 17D et 17E ;
- vérifie que toutes les autorisations dangereuses sont à `false` ;
- vérifie les sources admissibles et interdites ;
- vérifie les champs source obligatoires ;
- vérifie les droits, la provenance, la visibilité et les données personnelles ;
- vérifie que la provenance appartient aux valeurs connues ;
- vérifie que la visibilité reste `internal_review_only` ou `blocked` ;
- vérifie que `admit_metadata_only` impose `no_personal_data` ;
- vérifie que `source_id` est non vide et unique ;
- vérifie que `title` est non vide ;
- vérifie que `human_review_required: true` est obligatoire ;
- vérifie que `admit_metadata_only` impose un `license_status` sûr ;
- vérifie que `refusal_reason` est cohérent avec `admission_decision` ;
- vérifie que les sources admissibles et interdites sont disjointes ;
- interdit les décisions d’admission inconnues dans la configuration ;
- verrouille `refuse_real_document` pour les formats documentaires réels ;
- vérifie `real_file_attached: false` ;
- vérifie `external_url_required: false` ;
- interdit les champs `file_path`, `path`, `url`, `uri`, `checksum`, `sha256` réel et `content` ;
- vérifie les décisions d’admission ;
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
source-admission-policy-audit:
	$(PY) scripts/source_admission_policy_audit.py
```

La cible est classée `SAFE_METADATA_ONLY`.

Aucune cible sensible contenant `ingest`, `ingestion`, `api`, `upload`, `download`, `sync`, `deploy`, `qdrant`, `embed` ou `embedding` n’a été ajoutée.

## 8. Tests ajoutés

Le fichier `tests/unit/test_source_admission_policy_audit.py` ajoute 65 tests couvrant :

- existence du protocole, de la configuration et du script ;
- présence de la cible Makefile ;
- classification `SAFE_METADATA_ONLY` ;
- absence de cible sensible ajoutée ;
- absence de tokens réseau, subprocess ou destructifs dans le script ;
- succès du script sur la configuration réelle ;
- refus de toutes les autorisations dangereuses à `true` ;
- refus de références de politique incorrectes ;
- refus de fichiers réels, URL et contenu ;
- refus de droits inconnus admis ;
- refus de provenance inconnue ;
- refus de visibilité invalide ;
- refus de données personnelles ;
- refus de `source_id` vide ou dupliqué ;
- refus de `title` vide ;
- refus de `human_review_required` absent de la valeur stricte `true` ;
- refus de `license_status` non sûr pour une admission metadata-only ;
- acceptation du `license_status: unknown` uniquement dans un refus cohérent ;
- refus de `refusal_reason` incohérent ;
- refus d’intersection entre sources admissibles et interdites ;
- refus de décision d’admission inconnue dans la configuration ;
- refus documentaire explicite via `refuse_real_document` ;
- refus de `source_kind` non déclaré ;
- refus de champ obligatoire manquant ;
- refus de mismatch scope ;
- config non mapping sans traceback ;
- absence de modification du statut Git ;
- absence de création de `data/staging` ;
- absence d’ouverture de `.env` ;
- CLI réelle ;
- CLI en mode `python -O` ;
- maintien de `make-target-safety-audit` au vert.

Résultats finaux :

- `python3 -m ruff check ...` : OK ;
- `pytest tests/unit/test_source_admission_policy_audit.py -q` : 65 passed ;
- `make test` : 641 passed in 98.62s.

## 9. Résultat du source-admission-policy-audit

Résultat ciblé attendu :

- `policy_ready_for_review: true` ;
- `candidate_sources_count: 3` ;
- `admitted_metadata_only_count: 2` ;
- `refused_sources_count: 1` ;
- `dangerous_flags_enabled_count: 0` ;
- `missing_required_fields_count: 0` ;
- `malformed_sources_count: 0` ;
- `invalid_source_kinds_count: 0` ;
- `forbidden_source_fields_count: 0` ;
- `admission_decision_errors_count: 0` ;
- `rights_policy_errors_count: 0` ;
- `license_policy_errors_count: 0` ;
- `refusal_reason_errors_count: 0` ;
- `source_identity_errors_count: 0` ;
- `human_review_errors_count: 0` ;
- `source_kind_policy_errors_count: 0` ;
- `destructive_action_available: false`.

Durcissements métier ajoutés :

- source_id unique vérifié : oui ;
- title non vide vérifié : oui ;
- human_review_required vérifié : oui ;
- license_status vérifié : oui ;
- refusal_reason cohérent vérifié : oui ;
- allowed/forbidden source kinds disjoints : oui ;
- décisions inconnues interdites : oui ;
- refuse_real_document verrouillé : oui.

Synthèse de verrouillage avant commit :

- verdict READY_FOR_SOURCE_ADMISSION_POLICY_REVIEW ;
- protocole SOURCE_ADMISSION_POLICY créé ;
- configuration source_admission_policy créée ;
- script d’audit créé ;
- cible Makefile créée ;
- cible classée SAFE_METADATA_ONLY ;
- aucune cible sensible ajoutée ;
- source_id unique vérifié ;
- title non vide vérifié ;
- human_review_required vérifié ;
- license_status vérifié ;
- refusal_reason cohérent vérifié ;
- allowed/forbidden source kinds disjoints ;
- décisions inconnues interdites ;
- refuse_real_document verrouillé ;
- sources admissibles verrouillées ;
- sources interdites verrouillées ;
- champs source obligatoires vérifiés ;
- droits vérifiés ;
- provenance vérifiée ;
- visibilité vérifiée ;
- données personnelles interdites ;
- real_file_attached interdit ;
- external_url_required interdit ;
- champs file/url/content interdits ;
- décisions d’admission vérifiées ;
- config non mapping sans traceback ;
- make test : 641 passed ;
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

## 10. Résultat du make-target-safety-audit

Résultat ciblé attendu après ajout de la nouvelle cible :

- `all_targets_classified: true` ;
- `phony_targets_count: 46` ;
- `rule_targets_count: 46` ;
- `all_make_targets_count: 46` ;
- `SAFE_METADATA_ONLY: 11` ;
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
- aucun réseau ;
- aucun `.env` ouvert ;
- aucun `data/staging` créé ;
- `rag-local` non modifié.

## 12. Risques restants

- La politique reste déclarative : elle ne valide pas encore des fichiers réels.
- Les droits réels devront être confirmés humainement avant toute admission de corpus.
- Les chemins, checksums, parsing, chunking, embeddings et Qdrant restent à lotir séparément.

## 13. Verdict

READY_FOR_SOURCE_ADMISSION_POLICY_REVIEW

## 14. Recommandation pour 17G

Préparer la prochaine étape sous forme de lot metadata-only ou de protocole de revue humaine avant tout corpus réel, sans lancer d’ingestion ni manipuler de document réel.
