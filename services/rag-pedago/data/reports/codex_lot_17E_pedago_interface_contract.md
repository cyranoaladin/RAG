# Rapport Codex — Lot 17E : contrat d’interface pédagogique metadata-only

## 1. Objectif

Le lot 17E définit un contrat d’interface pédagogique strictement déclaratif et metadata-only.

Il ne crée aucune API réelle, aucun endpoint, aucun serveur, aucun runtime UI, aucun retrieval réel et aucune génération de réponse. Il cadre les personas, interactions, politiques de citation, refus contrôlés et limites avant toute interface réelle.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `7a8e0c5 feat: add retrieval metadata eval audit` ;
- `git status --short --branch` initial : `## main` ;
- `make make-target-safety-audit` : OK ;
- `make pilot-corpus-scope-audit` : OK ;
- `make retrieval-metadata-eval-audit` : OK ;
- `make cleanup-dry-run` : OK ;
- `make cleanup-review` : OK ;
- `make cleanup-decision-draft` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : 520 passed in 96.99s.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/PEDAGO_INTERFACE_CONTRACT_PROTOCOL.md` ;
- `configs/pedago_interface_contract.yml` ;
- `scripts/pedago_interface_contract_audit.py` ;
- `tests/unit/test_pedago_interface_contract_audit.py` ;
- `data/reports/codex_lot_17E_pedago_interface_contract.md`.

Fichiers modifiés :

- `Makefile` : ajout de `pedago-interface-contract-audit` ;
- `configs/make_target_safety.yml` : classification en `SAFE_METADATA_ONLY` ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` : mention de la nouvelle cible sûre.

Synthèse explicite :

- verdict READY_FOR_PEDAGO_INTERFACE_CONTRACT_REVIEW ;
- protocole PEDAGO_INTERFACE_CONTRACT créé : oui ;
- configuration pedago_interface_contract créée : oui ;
- script d’audit créé : oui ;
- cible Makefile créée : oui ;
- cible classée SAFE_METADATA_ONLY : oui ;
- aucune cible contenant `api` ajoutée : oui ;
- `make api` reste RESTRICTED_RUNTIME : oui.
- REQUIRED_CONTRACT_VALUES ajouté : oui ;
- source_trace_required verrouillé : oui ;
- refusal_policy globale complète vérifiée : oui ;
- interactions typées vérifiées : oui ;
- metadata_filters_required minimaux vérifiés : oui ;
- champs runtime interdits vérifiés : oui ;
- config non mapping sans traceback : oui.
- personas verrouillés : oui ;
- interactions verrouillées : oui ;
- citation_policy vérifiée : oui ;
- refusal_policy vérifiée : oui ;
- runtime API interdit : oui ;
- runtime UI interdit : oui ;
- génération de réponse interdite : oui ;
- embeddings interdits : oui ;
- Qdrant interdit : oui ;
- documents réels interdits : oui.

## 4. Protocole PEDAGO_INTERFACE_CONTRACT

Le protocole `docs/PEDAGO_INTERFACE_CONTRACT_PROTOCOL.md` définit :

- le périmètre pédagogique metadata-only ;
- les personas autorisés ;
- les parcours autorisés ;
- les sorties autorisées ;
- les sorties interdites ;
- les interdictions runtime ;
- les conditions avant API/UI réelle.

Il interdit explicitement serveur, endpoint réel, runtime API, composant UI réel, retrieval réel, document réel, PDF, ingestion, parsing, chunking, embedding, Qdrant, génération de réponse finale, réseau et `data/staging`.

## 5. Configuration pedago_interface_contract.yml

La configuration `configs/pedago_interface_contract.yml` est déclarative uniquement.

Elle fixe :

- `contract_id: pedago_interface_metadata_contract_v1` ;
- `status: metadata_only_interface_contract` ;
- `pilot_scope_ref: math_terminale_specialite_metadata_only_v1` ;
- `retrieval_eval_ref: math_terminale_specialite_metadata_retrieval_eval_v1`.

Toutes les autorisations dangereuses valent `false`, notamment :

- `runtime_api_allowed` ;
- `server_start_allowed` ;
- `ui_runtime_allowed` ;
- `answer_generation_allowed` ;
- `embeddings_allowed` ;
- `qdrant_allowed` ;
- `real_documents_allowed` ;
- `network_allowed` ;
- `data_staging_allowed`.

Personas verrouillés :

- `eleve` ;
- `enseignant` ;
- `administrateur_pedagogique`.

Interactions déclaratives :

- `eleve_recherche_fiche_cours` ;
- `enseignant_revue_resultat` ;
- `administrateur_validation_refus`.

## 6. Script pedago_interface_contract_audit.py

Le script :

- lit `configs/pedago_interface_contract.yml` ;
- vérifie les références strictes `contract_id`, `pilot_scope_ref` et `retrieval_eval_ref` ;
- vérifie `status: metadata_only_interface_contract` ;
- vérifie que toutes les autorisations dangereuses sont à `false` ;
- vérifie que les personas requis sont présents ;
- vérifie que chaque interaction contient les champs obligatoires ;
- vérifie les types critiques de chaque interaction ;
- vérifie que chaque persona est autorisé ;
- vérifie que chaque `expected_behavior` est autorisé ;
- vérifie les `input_kind` autorisés ;
- vérifie que `citation_policy` est stricte ;
- vérifie que `refusal_policy` est stricte ;
- vérifie que les interactions non-refus ont les filtres metadata minimaux ;
- vérifie que les interactions de refus n’ont pas de filtres exploitables ;
- vérifie l’absence de champs runtime interdits ;
- vérifie qu’aucune interaction ne demande une génération de réponse ;
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
pedago-interface-contract-audit:
	$(PY) scripts/pedago_interface_contract_audit.py
```

La cible est classée `SAFE_METADATA_ONLY`.

Aucune cible contenant `api` n’a été ajoutée. Les cibles interdites comme `api-ui-audit`, `api-contract-audit`, `ui-api-audit` et `api-metadata-audit` n’existent pas.

## 8. Tests ajoutés

Le fichier `tests/unit/test_pedago_interface_contract_audit.py` ajoute 56 tests couvrant :

- existence du protocole, de la configuration et du script ;
- présence de la cible Makefile ;
- classification `SAFE_METADATA_ONLY` ;
- absence de cible Makefile contenant `api` ajoutée ;
- maintien de `api` en `RESTRICTED_RUNTIME` ;
- absence de tokens réseau, subprocess ou destructifs dans le script ;
- succès du script sur la configuration réelle ;
- sortie Markdown attendue ;
- refus de toutes les autorisations dangereuses à `true` ;
- refus d’un persona requis manquant ;
- refus d’un persona inconnu ;
- refus d’un comportement inconnu ;
- refus de politiques de citation permissives ;
- refus de `source_trace_required: false` global ou par interaction ;
- refus de références 17C/17D incorrectes ;
- refus de `refusal_policy` globale incomplète ;
- refus de `refusal_policy` d’interaction mal typée ou permissive ;
- refus d’interactions mal typées ;
- refus de filtres metadata minimaux manquants ;
- refus de filtres exploitables sur un cas de refus ;
- refus de champs runtime interdits ;
- refus d’une configuration YAML non mapping sans traceback ;
- refus d’une interaction non-refus sans filtres metadata ;
- refus d’une interaction demandant `answer_generation_expected: true` ;
- absence de modification du statut Git ;
- absence de création de `data/staging` ;
- absence d’ouverture de `.env` ;
- CLI réelle ;
- CLI en mode `python -O` ;
- maintien de `make-target-safety-audit` au vert.

Résultats finaux :

- `python3 -m ruff check ...` : OK ;
- `pytest tests/unit/test_pedago_interface_contract_audit.py -q` : 56 passed ;
- `make test` : 576 passed in 100.22s.

## 9. Résultat du pedago-interface-contract-audit

Résultat ciblé :

- `interface_ready_for_review: true` ;
- `interactions_count: 3` ;
- `personas_count: 3` ;
- `invalid_contract_values_count: 0` ;
- `dangerous_flags_enabled_count: 0` ;
- `missing_required_personas_count: 0` ;
- `malformed_interactions_count: 0` ;
- `invalid_personas_count: 0` ;
- `invalid_expected_behaviors_count: 0` ;
- `citation_policy_errors_count: 0` ;
- `refusal_policy_errors_count: 0` ;
- `interaction_contract_errors_count: 0` ;
- `forbidden_runtime_fields_count: 0` ;
- `answer_generation_allowed: false` ;
- `runtime_api_allowed: false` ;
- `server_start_allowed: false` ;
- `ui_runtime_allowed: false` ;
- `embeddings_allowed: false` ;
- `qdrant_allowed: false` ;
- `real_documents_allowed: false` ;
- `destructive_action_available: false`.

## 10. Résultat du make-target-safety-audit

Résultat ciblé après ajout de la nouvelle cible :

- `all_targets_classified: true` ;
- `phony_targets_count: 45` ;
- `rule_targets_count: 45` ;
- `all_make_targets_count: 45` ;
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

- aucun serveur API démarré ;
- aucun runtime UI démarré ;
- aucun document réel lu ;
- aucun PDF/DOCX/PPTX/XLSX copié ;
- aucun PDF copié ;
- aucun DOCX copié ;
- aucun PPTX copié ;
- aucun XLSX copié ;
- aucune ingestion ;
- aucune ingestion lancée ;
- aucun retrieval réel exécuté ;
- aucun embedding ;
- aucun embedding créé ;
- aucun Qdrant ;
- aucun Qdrant touché ;
- aucune réponse générée ;
- aucun réseau ;
- aucun `.env` ouvert ;
- aucun `data/staging` créé ;
- `rag-local` non modifié.

## 12. Risques restants

- Le contrat reste déclaratif : aucune API réelle et aucune UI runtime ne sont implémentées.
- Les messages exacts d’interface utilisateur ne sont pas encore maquettés.
- Les règles d’authentification, journalisation et supervision restent à spécifier avant runtime.
- Les futures intégrations devront rester séparées du retrieval réel, de l’ingestion et de Qdrant.

## 13. Verdict

READY_FOR_PEDAGO_INTERFACE_CONTRACT_REVIEW

## 14. Recommandation pour 17F

Préparer un protocole d’ingestion pilote avec validation humaine, en restant metadata-only tant que les droits, sources, chemins exacts, rollback, parsing, chunking, embeddings et Qdrant ne sont pas lotis séparément.
