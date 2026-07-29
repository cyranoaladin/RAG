# Rapport de LOT 31 — Dettes techniques (D-28-01, sources to_verify, ADR-0019)

- **Branche proposée** : `lot-31-dettes-techniques`
- **Date** : 2026-07-26
- **Prérequis** : LOT 29 + correctifs PR #73 fusionnés
- **Verrous levés** : aucun.

## 1. Objet

Résorption des dettes déclarées : D-28-01 (taxonomies exams lues « vides » → 2 quarantaines systématiques), validation agentique des 11 sources `to_verify`, cadrage du recalibrage des seuils.

## 2. Livrables

| Livrable | Chemin |
|---|---|
| ADR-0019 (revue par domaine + validation sources) | `docs/adr/ADR-0019-revue-differenciee-par-domaine-et-validation-sources.md` |
| SubjectExpert conscient du domaine (`domain: exam` → marqueurs d'examen) | `services/rag-pedago/agents/reviewers.py` |
| Politique : section `exam_domain` (marqueurs, seuil) | `services/rag-pedago/configs/review_policy.yml` |
| Agent de validation des sources to_verify (verdicts signés, sans effet de bord) | `services/rag-pedago/agents/source_validator.py` |
| 2 nouveaux tests (marqueurs exam présents / absents) | `services/rag-pedago/tests/unit/test_review_panel.py` |
| En-tête du fichier sources aligné sur ADR-0018 | `services/rag-pedago/configs/eduscol_sources.yml` |

## 3. Résolution de D-28-01

Les taxonomies `exams/anticipee_maths.yml` et `exams/bac_general.yml` sont des **spécifications d'examen** valides (candidats, épreuves, métadonnées) — le défaut n'était pas le fichier mais la règle appliquée. Le SubjectExpert applique désormais :

- `domain: exam` → marqueurs d'examen (≥ 2 parmi session/sujet/épreuve/annales/corrigé/baccalauréat/durée/examen) ;
- autres domaines → couverture notionnelle (inchangé) ;
- entrée catalogue absente → quarantaine (fail-closed, inchangé).

## 4. Validation des sources (ADR-0018 §6)

`python -m agents.source_validator --run` relit les 11 sources `to_verify` (droits par provenance, HTTP, substance, motifs interdits). Verdicts signés dans `data/reports/source_validation_latest.md`. **La bascule `verified` reste un changement de config soumis à PR** — les flips effectifs sont inclus dans ce lot uniquement pour les sources `verified_candidate`.

## 5. Seuil de couverture (recalibrage)

Le seuil `min_notion_coverage: 0.05` est **maintenu** : les 3 rejets à 0 % (hlp, francais, ses) sont des pages-hub de navigation ; les sous-pages découvertes par l'agent (link discovery) porteront le contenu. Le ledger des décisions rend le recalibrage mesurable — il sera révisé sur données réelles accumulées (dette déclarée, non bloquante).

## 6. Preuves

- 20/20 tests unitaires du panel (dont 2 nouveaux pour le domaine exam).
- CI locale 7/7 PASS.
- `--plan` du validateur : 11 sources listées ; `--run` : verdicts signés + rapport.
