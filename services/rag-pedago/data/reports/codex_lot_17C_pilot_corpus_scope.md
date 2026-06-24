# Rapport Codex — Lot 17C : cadrage du corpus pilote metadata-only

## 1. Objectif

Préparer le périmètre d'un premier corpus pilote strictement synthétique ou metadata-only pour le RAG pédagogique.

Le lot 17C ne lance aucune ingestion, ne copie aucun document réel, ne parse aucun fichier, ne crée aucun embedding, ne touche pas à Qdrant et ne crée pas `data/staging`.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `aec6647 chore: audit make target safety` ;
- `git status --short --branch` initial : `## main` ;
- `make make-target-safety-audit` : OK ;
- `make cleanup-dry-run` : OK ;
- `make cleanup-review` : OK ;
- `make cleanup-decision-draft` : OK ;
- `make metadata-preflight` : OK ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : `437 passed in 86.65s`.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Fichiers créés ou modifiés

Fichiers créés :

- `docs/PILOT_CORPUS_SCOPE_PROTOCOL.md` ;
- `configs/pilot_corpus_scope.yml` ;
- `scripts/pilot_corpus_scope_audit.py` ;
- `tests/unit/test_pilot_corpus_scope_audit.py` ;
- `data/reports/codex_lot_17C_pilot_corpus_scope.md`.

Fichiers modifiés :

- `Makefile` : ajout de la cible non destructive `pilot-corpus-scope-audit` ;
- `configs/make_target_safety.yml` : classification `SAFE_METADATA_ONLY` de la nouvelle cible ;
- `docs/MAKE_TARGET_SAFETY_PROTOCOL.md` : ajout de la nouvelle cible dans les cibles SAFE_METADATA_ONLY autorisées par défaut.

La modification du protocole Makefile est nécessaire parce que le lot 17B impose que toute cible Makefile appelable soit classée et documentée.

Synthèse explicite du lot :

- protocole PILOT_CORPUS_SCOPE créé : oui ;
- configuration pilot_corpus_scope créée : oui ;
- script d’audit créé : oui ;
- cible Makefile créée : oui ;
- cible classée SAFE_METADATA_ONLY : oui ;
- scope metadata-only validé : oui ;
- documents réels interdits : oui ;
- ingestion interdite : oui ;
- embeddings interdits : oui ;
- Qdrant interdit : oui ;
- réseau interdit : oui.

## 4. Protocole PILOT_CORPUS_SCOPE

Le protocole `docs/PILOT_CORPUS_SCOPE_PROTOCOL.md` définit :

- l'objectif du cadrage ;
- le périmètre mathématiques terminale spécialité ;
- le contexte AEFE Tunisie ou francophone équivalent ;
- le statut candidat scolarisé ;
- les interdictions explicites : documents réels, PDF, DOCX, PPTX, XLSX, ingestion, parsing, chunking, embeddings, Qdrant, scraping, réseau et `data/staging` ;
- les ressources autorisées : métadonnées synthétiques, fixtures versionnées, référentiels, taxonomies, rapports Codex et protocoles ;
- les métadonnées minimales ;
- les critères d'acceptation ;
- les exclusions ;
- les conditions avant tout futur corpus réel ;
- la cohérence stricte du scope avant revue.

## 5. Configuration pilot_corpus_scope.yml

La configuration `configs/pilot_corpus_scope.yml` est déclarative uniquement.

Elle fixe :

- `pilot_id: math_terminale_specialite_metadata_only_v1` ;
- `status: metadata_only_scope` ;
- `subject: mathematiques` ;
- `level: terminale` ;
- `track: generale` ;
- `teaching: specialite_mathematiques` ;
- `teaching_status: specialite` ;
- `context: aefe_tunisie` ;
- `candidate_status: candidat_scolarise` ;
- `candidate_ref: scolarise`.

Toutes les autorisations dangereuses valent `false` :

- `real_documents_allowed` ;
- `pdf_allowed` ;
- `docx_allowed` ;
- `pptx_allowed` ;
- `xlsx_allowed` ;
- `ingestion_allowed` ;
- `parsing_allowed` ;
- `chunking_allowed` ;
- `embeddings_allowed` ;
- `qdrant_allowed` ;
- `network_allowed` ;
- `data_staging_allowed`.

## 6. Script pilot_corpus_scope_audit.py

Le script `scripts/pilot_corpus_scope_audit.py` :

- lit `configs/pilot_corpus_scope.yml` ;
- verrouille `REQUIRED_SCOPE_VALUES` ;
- vérifie que les interdictions sont toutes à `false` ;
- vérifie que le statut est `metadata_only_scope` ;
- vérifie que le périmètre mentionne mathématiques, terminale et spécialité ;
- vérifie que les ressources autorisées restent synthétiques ou metadata-only ;
- vérifie que toutes les ressources autorisées obligatoires sont présentes ;
- vérifie que toutes les exclusions critiques sont présentes ;
- vérifie les champs obligatoires ;
- vérifie les critères d'acceptation ;
- rend une configuration non mapping en Markdown sans traceback ;
- produit uniquement du Markdown sur stdout ;
- ne lance aucun sous-processus ;
- ne fait aucun réseau ;
- n'écrit aucun fichier ;
- n'ouvre aucun `.env` ;
- ne lit aucun document réel ;
- ne crée pas `data/staging`.

Option autorisée :

- `--config`.

## 7. Cible Makefile

Une cible non destructive a été ajoutée :

```makefile
pilot-corpus-scope-audit:
	$(PY) scripts/pilot_corpus_scope_audit.py
```

Elle est classée `SAFE_METADATA_ONLY` dans `configs/make_target_safety.yml`.

## 8. Tests ajoutés

Le fichier `tests/unit/test_pilot_corpus_scope_audit.py` ajoute 31 tests couvrant :

- existence du protocole, de la configuration et du script ;
- présence de la cible Makefile ;
- classification `SAFE_METADATA_ONLY` ;
- absence de chaînes réseau, subprocess ou destructives dans le script ;
- exécution module et sortie Markdown ;
- test paramétré de toutes les autorisations dangereuses ;
- refus d'une valeur de scope invalide ;
- refus d'un statut candidat invalide ;
- refus si `official_exam_ref` manque ;
- refus si `difficulty` manque ;
- refus d'une ressource autorisée non sûre ;
- refus si une ressource autorisée obligatoire manque ;
- refus si une exclusion critique manque ;
- refus d'une configuration YAML non mapping sans traceback ;
- refus si un champ obligatoire manque ;
- absence de modification du statut Git ;
- absence de création de `data/staging` ;
- absence d'ouverture de `.env` ;
- CLI réelle ;
- CLI en mode `python -O`.

Résultats ciblés observés :

- `python3 -m ruff check scripts/pilot_corpus_scope_audit.py tests/unit/test_pilot_corpus_scope_audit.py` : OK ;
- `pytest tests/unit/test_pilot_corpus_scope_audit.py -q` : `31 passed in 0.62s`.
- `make test` : `468 passed in 87.31s`.

## 9. Résultat du pilot-corpus-scope-audit

Résultat observé :

- `pilot_id: math_terminale_specialite_metadata_only_v1` ;
- `status: metadata_only_scope` ;
- `scope_ready_for_review: true` ;
- `invalid_scope_values_count: 0` ;
- `dangerous_flags_enabled_count: 0` ;
- `missing_required_metadata_fields_count: 0` ;
- `unsafe_allowed_resource_kinds_count: 0` ;
- `missing_allowed_resource_kinds_count: 0` ;
- `missing_excluded_resource_kinds_count: 0` ;
- `missing_acceptance_checks_count: 0` ;
- `real_documents_allowed: false` ;
- `ingestion_allowed: false` ;
- `embeddings_allowed: false` ;
- `qdrant_allowed: false` ;
- `network_allowed: false` ;
- `data_staging_allowed: false` ;
- `destructive_action_available: false` ;
- `Blocking issues: none`.

`make make-target-safety-audit` après ajout de la cible 17C :

- `all_targets_classified: true` ;
- `phony_targets_count: 43` ;
- `rule_targets_count: 43` ;
- `SAFE_METADATA_ONLY: 8` ;
- `unsafe_safe_classifications_count: 0` ;
- `suspicious_safe_classifications_count: 0` ;
- `targets_executed: false`.

Durcissements ajoutés :

- verrouillage REQUIRED_SCOPE_VALUES : oui ;
- test toutes autorisations dangereuses : oui ;
- official_exam_ref obligatoire : oui ;
- difficulty obligatoire : oui ;
- ressources autorisées obligatoires : oui ;
- exclusions obligatoires : oui ;
- config non mapping sans traceback : oui.

## 10. Garanties non destructives

- aucun document réel copié ;
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
- aucun .env ouvert ;
- aucun data/staging créé ;
- rag-local non modifié.

## 11. Risques restants

- Le cadrage ne valide pas encore de contenu pédagogique réel.
- Le périmètre reste metadata-only : il ne prouve pas la qualité d'un futur corpus documentaire.
- Les droits, sources exactes, chemins et SHA-256 d'un futur corpus réel devront être validés humainement dans un lot séparé.
- Aucun retrieval, embedding ou Qdrant n'est autorisé ni testé par ce lot.

## 12. Verdict

READY_FOR_PILOT_CORPUS_SCOPE_REVIEW

## 13. Recommandation pour 17D

Préparer une évaluation retrieval strictement hors embeddings réels, par exemple sous forme de golden questions metadata-only et critères de pertinence pédagogiques, sans ingestion, sans Qdrant et sans document réel.
