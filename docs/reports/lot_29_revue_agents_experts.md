# Rapport de LOT 29 — Revue par panel d'agents experts (ADR-0018)

- **Branche proposée** : `lot-29-revue-agents-experts`
- **Date** : 2026-07-26
- **Prérequis** : LOT 28 fusionné (corpus, ingestion continue, cockpit v2)
- **Verrous levés** : aucun.

## 1. Objet

Directive plateforme : les revues et validations humaines sont remplacées par des revues effectuées par des **agents experts spécialisés**. Ce lot livre le panel de revue déterministe, sa politique, ses tests et l'adaptation du cockpit.

## 2. Livrables

| Livrable | Chemin |
|---|---|
| ADR-0018 (décision de gouvernance) | `docs/adr/ADR-0018-revue-par-agents-experts.md` |
| Politique du panel (seuils, règles, consensus) | `services/rag-pedago/configs/review_policy.yml` |
| Trois reviewers experts (droits / programme / qualité) | `services/rag-pedago/agents/reviewers.py` |
| Orchestrateur du panel + CLI | `services/rag-pedago/agents/review_panel.py` |
| Tests unitaires du panel | `services/rag-pedago/tests/unit/test_review_panel.py` |
| Cockpit : page « Revue agents » (verdicts signés) | `services/cockpit/src/sections/ReviewSection.tsx` |

## 3. Modèle de décision

- **Consensus unanime** : approved ⇔ 3/3 reviewers approuvent.
- **Fail-closed partout** : désaccord, doute, reviewer en échec, taxonomie manquante, droits inconnus, intégrité rompue → **quarantaine**.
- **Signatures** : chaque verdict (reviewer) et chaque décision (panel) sont signés par SHA-256 du payload canonique, écrits en append-only (`data/review/review_panel_manifest.jsonl`, `data/ledger/review_panel.jsonl`).
- **Réversibilité** : les artefacts restent en staging ; une décision peut être rejouée après ajustement de la politique (via PR).

## 4. Règles expertes (résumé)

| Reviewer | Règles |
|---|---|
| RightsExpertAgent | provenance → droits via `rights_map` ; inconnu → quarantaine (règle dure) ; incohérence déclaré/résolu → rejected |
| SubjectExpertAgent | couverture des notions de la taxonomie cible ≥ 5 % ; taxonomie absente → quarantaine ; contenu hors programme → rejected |
| QualityExpertAgent | 200 ≤ mots ≤ 200 000 ; motifs interdits (challenge WAF, paywall) → quarantaine ; intégrité SHA-256 ; champs manifeste requis |

## 5. Preuves

- Tests unitaires du panel : 10 cas (approbation unanime, désaccord → quarantaine, reviewer en échec fail-closed, droits inconnus → quarantaine, intégrité, contenu hors programme, page WAF).
- `--plan` sur staging réel : liste les 9 artefacts LOT 28 en `pending`.
- `--run` : verdicts écrits dans chaque `manifest.json`, manifeste append-only, rapport généré.

## 6. Limites déclarées

- Les reviewers sont **déterministes** (règles expertes codées), pas des juges LLM : c'est un choix de gouvernance (explicabilité, CI, zéro secret). L'ajout d'un reviewer sémantique LLM nécessiterait un ADR ultérieur et une gestion de secrets conforme R-01.
- La couverture de notions à 5 % est un seuil initial prudent pour des **pages hub** eduscol ; il sera recalibré sur données réelles (décisions consignées → mesurable).
