# Lot 11.2 - Consolidation post-retour Codex

## Contexte

Objectif du lot : auditer l'etat reel apres le retour Codex sur le Lot 11, fermer les dettes techniques avant nouveau developpement fonctionnel, rendre les cibles qualite reproductibles et documenter les ecarts connus.

Ce lot ne lance aucune ingestion reelle, ne demarre aucun serveur runtime et ne modifie aucun verrou `*_allowed` de gouvernance.

## Etat initial

Commandes executees au demarrage du lot :

```text
$ git status --short
(sortie vide)

$ git branch --show-current
lot-11.1/gouvernance-parsing

$ git diff --stat
(sortie vide)

$ git diff --name-status
(sortie vide)
```

Le travail a ete isole sur la branche :

```text
lot-11.2/consolidation-post-codex
```

Extrait de `git log --oneline -20` au demarrage :

```text
6e1d0ee rag-pedago: fix lot 11 source selection
eda4ab4 fix(lot-11.2): seal gating with tests + recount real coverage
1a54f27 fix(lot-11.1): regularize parsing governance + bot feedback
af89a0f feat(lot-11): verified article table replaces title guessing
7201d10 Lot 10+10.1 — Multi-agents + priorisation (#22)
```

Fichiers modifies avant intervention : aucun dans le worktree courant. Fichiers supprimes avant intervention : aucun dans le worktree courant. Fichiers non suivis avant intervention : aucun.

## Audit Lot 11

Les corrections annoncees par le retour Codex precedent etaient presentes dans l'etat local :

- `fetch_notion()` selectionne au plus une ressource finale acceptable par couple `(matiere, notion_id)`.
- Les candidats restants sont conserves dans `candidate_urls` et `ignored_candidate_urls`.
- `chosen_url`, `source_label`, `selection_reason` et `fallback_used` sont renseignes.
- Les pages Wikiversity de navigation ne sont pas retenues directement ; une sous-page retenue porte `url == chosen_url == sub_url`, `page_type == subpage` et un `source_label` deterministe.
- `SubjectAgent.fetch()` ecrit le fichier canonique `{matiere}_{notion_id}.json`.
- `notion_articles.yml` contient `algorithmique_suites / mathematiques` et `dictionnaires / nsi`.
- Le test de non-regression sur les longs articles avec marqueurs de navigation mineurs existe dans `test_fetch.py`.

Dette identifiee et corrigee dans ce lot : `SubjectAgent` importait un helper prive de `taxonomy_fetcher`. Le helper est devenu une API publique documentee `cleanup_previous_notion_files()`.

## Corrections appliquees

- `services/rag-pedago/Makefile` : installation reproductible dans `.venv`, y compris pour `mypy`, afin que `make typecheck` ne depende plus de l'environnement Python systeme.
- `services/rag-engine/Makefile` : suppression de l'installation implicite non deterministe des outils qualite ; les dependances doivent venir des fichiers de requirements versionnes.
- `services/rag-pedago/scrapers/taxonomy_fetcher.py` : exposition publique de `cleanup_previous_notion_files()` et usage par `fetch_taxonomy()`.
- `services/rag-pedago/agents/subject_agent.py` : import de l'API publique au lieu du helper prive.
- `services/rag-pedago/configs/make_target_safety.yml` : classification explicite de la cible `venv` comme cible reseau/restreinte, coherente avec `install`.
- Tests ajoutes ou renforces pour : ecriture canonique par `fetch_taxonomy`, nettoyage strictement borne a la notion, absence de fichiers staging suffixes par source, gouvernance des verrous, reproductibilite `mypy`, hashes independants du cwd, tolerance de `project_doctor` aux fichiers suivis supprimes pendant la lecture, blocage des chemins legacy `rag-local`.

## Decisions techniques

### `python -m pytest -q` a la racine

La commande racine avec Python systeme n'est pas canonique dans ce depot multi-services. Elle collecte simultanement des packages qui exigent des environnements et `PYTHONPATH` differents.

Preuve d'audit :

```text
$ python3 -m pytest -q
ERROR packages/contracts/tests/test_contracts.py - ModuleNotFoundError: No module named 'nexus_contracts'
ERROR services/rag-engine/tests/backend/test_auth.py - ModuleNotFoundError: No module named 'src'
ERROR services/rag-engine/tests/integration - ModuleNotFoundError: No module named 'chromadb'
ERROR services/rag-engine/tests/test_drive_sync.py - ModuleNotFoundError: No module named 'google'
ERROR services/rag-pedago/tests/unit/test_fetch.py - ModuleNotFoundError: No module named 'scrapers'
ERROR services/rag-pedago/tests/unit/test_project_doctor.py - ModuleNotFoundError: No module named 'rag_pedago'
!!!!!!!!!!!!!!!!!!! Interrupted: 69 errors during collection !!!!!!!!!!!!!!!!!!!
1 skipped, 69 errors in 1.92s
```

Decision : la reference reproductible reste `bash scripts/ci-local.sh` et les Makefiles par service. Aucun test `rag-engine` n'a ete masque ou supprime.

### Gouvernance

`pedago_interface_contract.yml` et `source_admission_policy.yml` ne portent pas le meme perimetre :

- `pedago_interface_contract.yml` autorise le fetch reseau et le staging dans un perimetre controle Lot 11 ;
- `source_admission_policy.yml` maintient les verrous d'admission corpus/pipeline a `false` ;
- `transition_authorization.yml` documente l'autorisation de fetch reseau via ADR-0004 sans autoriser ingestion, parsing, chunking, embeddings ou indexation.

Un test d'audit semantique verrouille cette separation et interdit une contradiction silencieuse.

## Staging

Etat courant des fichiers suivis dans `services/rag-pedago/data/staging` :

```text
services/rag-pedago/data/staging/agents/terminale/mathematiques/mathematiques_algorithmique_suites.json
services/rag-pedago/data/staging/agents/terminale/mathematiques/mathematiques_derivation.json
services/rag-pedago/data/staging/agents/terminale/mathematiques/mathematiques_suites.json
services/rag-pedago/data/staging/agents/terminale/nsi/nsi_dictionnaires.json
services/rag-pedago/data/staging/programmes/mathematiques_seconde_enseignement_commun.pdf
services/rag-pedago/data/staging/programmes/mathematiques_seconde_enseignement_commun.pdf.meta.json
services/rag-pedago/data/staging/programmes/nsi_premiere_specialite.pdf
services/rag-pedago/data/staging/programmes/nsi_premiere_specialite.pdf.meta.json
```

Commandes d'audit :

```text
$ git ls-files -d services/rag-pedago/data/staging
(sortie vide)

$ git ls-files -o --exclude-standard services/rag-pedago/data/staging
(sortie vide)
```

Les suppressions massives de staging etaient deja presentes dans le commit parent `6e1d0ee`. Elles concernent les anciens fichiers par source et des sorties generees devenues non canoniques. Ce lot ne rajoute aucune suppression staging pendante.

Verification ajoutee : si un fichier canonique `{matiere}_{notion_id}.json` existe, aucun fichier concurrent `*_wikipedia*.json` ou `*_wikiversity*.json` de la meme notion ne doit exister.

## Exemple avant / apres

`mathematiques_suites.json` avant le correctif Lot 11 retenait une sous-page Wikiversity tout en conservant le `chosen_url` de la page parente :

```text
url: https://fr.wikiversity.org/wiki/Suites_et_r%C3%A9currence/Op%C3%A9rations_sur_les_limites
chosen_url: https://fr.wikiversity.org/wiki/Suites_et_r%C3%A9currence
source_label: wikiversity_suites_ch3
page_type: subpage
selection_reason: null
fallback_used: null
```

Etat courant verifie :

```text
url: https://fr.wikipedia.org/wiki/Suite_%28math%C3%A9matiques%29
chosen_url: https://fr.wikipedia.org/wiki/Suite_%28math%C3%A9matiques%29
source_label: wikipedia_suites
page_type: article
selection_reason: first_acceptable_candidate
fallback_used: false
candidate_urls: [Wikipedia Suite, Wikiversity Suites et recurrence]
ignored_candidate_urls: [Wikiversity Suites et recurrence]
```

Autres notions verifiees :

- `mathematiques_derivation.json` retient Wikipedia `Derivee`, ignore le candidat Wikiversity et conserve une trace de selection.
- `mathematiques_algorithmique_suites.json` retient Wikipedia `Suite_(mathematiques)` avec fallback des candidats explicites.
- `nsi_dictionnaires.json` retient `Tableau_associatif` avant `Table_de_hachage`, selon la priorite YAML.

## Tests ajoutes ou maintenus

- `test_fetch_notion_keeps_only_first_successful_article`
- `test_fetch_notion_selects_one_wikiversity_subpage_with_real_url`
- `test_fallback_uses_label_before_notion_id`
- `test_fallback_keeps_qualified_wikipedia_and_wikiversity_variants`
- `test_subject_agent_writes_only_canonical_notion_file`
- `test_notion_articles_contains_required_lot_11_entries`
- `test_long_article_with_minor_nav_markers_not_flagged_as_navigation`
- `test_fetch_taxonomy_writes_only_canonical_notion_file`
- `test_cleanup_previous_notion_files_is_scoped_to_exact_notion`
- `test_no_source_suffixed_staging_file_for_canonical_notion`
- `test_typecheck_target_has_mypy_available_after_install`
- `test_review_package_hash_is_cwd_independent`
- `test_controlled_import_hash_is_cwd_independent`
- `test_project_doctor_tolerates_git_tracked_file_deleted_between_scan_and_read`
- `test_real_draft_guard_blocks_legacy_rag_local_paths`

## Commandes executees

### `services/rag-pedago`

```text
$ make install
Successfully installed nexus-rag-pedago-0.1.0

$ make lint
All checks passed!

$ make typecheck
Success: no issues found in 66 source files

$ make test
1045 passed in 157.99s (0:02:37)

$ python -m pytest tests/unit/test_taxonomy_fetcher.py -q
9 passed in 0.18s

$ python -m pytest tests/unit/test_fetch.py -q
17 passed in 0.22s
```

### `services/rag-engine`

```text
$ make install
(installation terminee sans installation implicite hors requirements)

$ make lint
All checks passed!

$ make typecheck
Success: no issues found in 32 source files

$ make test
........................................................................ [ 59%]
.................................................                        [100%]
```

### Racine

```text
$ bash scripts/ci-local.sh
CI LOCAL — SUMMARY
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  governance-locks
  PASS  taxonomy-validation
  PASS  governance-guard-tests
  PASS  ci-failsafe-tests

Total: 7 passed, 0 failed
```

Note : `rag-engine` signale 3 warnings de test non bloquants (`crypt` deprecie dans `passlib`, avertissement de compatibilite `requests`, `datetime.utcnow()` deprecie dans `python-jose`). Aucun avertissement n'ouvre une regression fonctionnelle de ce lot.

## Dettes restantes

Aucune dette technique nouvelle n'est identifiee a ce stade. La seule clarification explicite est que `python3 -m pytest -q` depuis la racine n'est pas une commande canonique ; elle reste remplacee par `scripts/ci-local.sh` et les Makefiles des services.

## Etat git avant commit

```text
$ git branch --show-current
lot-11.2/consolidation-post-codex

$ git status --short
 M services/rag-engine/Makefile
 M services/rag-pedago/Makefile
 M services/rag-pedago/agents/subject_agent.py
 M services/rag-pedago/configs/make_target_safety.yml
 M services/rag-pedago/scrapers/taxonomy_fetcher.py
 M services/rag-pedago/tests/unit/test_cleanup_decision_draft.py
 M services/rag-pedago/tests/unit/test_cleanup_review_package.py
 M services/rag-pedago/tests/unit/test_controlled_import.py
 M services/rag-pedago/tests/unit/test_make_target_safety_audit.py
 M services/rag-pedago/tests/unit/test_project_doctor.py
 M services/rag-pedago/tests/unit/test_real_draft_guard.py
 M services/rag-pedago/tests/unit/test_review_package.py
 M services/rag-pedago/tests/unit/test_taxonomy_fetcher.py
?? docs/reports/lot_11_2_consolidation_post_codex.md
?? services/rag-pedago/tests/unit/test_governance_policy_scope_consistency.py

$ git diff --check
(sortie vide)
```

## Recommandations prochain lot

- Continuer a utiliser les Makefiles par service et `scripts/ci-local.sh` comme commandes de reference.
- Ne rendre `python -m pytest -q` racine canonique que dans un lot dedie, avec environnement racine unifie et configuration pytest explicite.
- Ne pas rouvrir l'ecriture multi-fichiers par source sans refactor complet de `fetch_taxonomy`, `SubjectAgent.fetch`, rapports et chemins de staging.
