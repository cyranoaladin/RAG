# ADR-0018 — Revue par panel d'agents experts (remplacement de la revue humaine)

- **Statut** : proposé (LOT 29)
- **Date** : 2026-07-26
- **Amende** : l'acteur de l'étape « review » de la chaîne quality → gate → review (ADR-0005, ADR-0009) et les mentions « revue humaine » d'ADR-0016
- **Contexte** : directive du propriétaire de la plateforme — les revues et validations doivent être effectuées par des agents experts spécialisés, pas par des humains.

## Décision

1. **L'étape « review » est effectuée par un panel d'agents relecteurs experts**, déterministes et auditables (`agents/reviewers.py`, `agents/review_panel.py`) :
   - `RightsExpertAgent` — droits résolus **par provenance** (jamais par classification de texte) ;
   - `SubjectExpertAgent` — conformité au programme officiel (couverture des notions de la taxonomie de la collection cible) ;
   - `QualityExpertAgent` — substance, intégrité SHA-256, complétude des métadonnées, motifs interdits (pages de challenge WAF, paywall).
2. **Consensus unanime** : `approved` exige 3/3. Tout désaccord, tout doute, tout reviewer en échec → **quarantaine** (fail-closed).
3. **Règles dures non délégables** (même aux agents) :
   - droits inconnus pour une provenance → quarantaine automatique, sans exception ;
   - intégrité SHA-256 rompue → quarantaine ;
   - le panel n'écrit **jamais** dans pgvector : l'indexation reste soumise à la chaîne gouvernée complète.
4. **Traçabilité** : chaque verdict est signé (reviewer, règles déclenchées, sha256 du payload), consigné dans `data/review/review_panel_manifest.jsonl` (append-only) et au ledger ; le manifeste staging porte le verdict complet. Toute décision est **réversible et rejouable** (les artefacts restent en staging).
5. **Supervision** : la revue par agents n'exonère pas la supervision de la plateforme — les rapports du panel (`data/reports/review_panel_latest.md`) et la page « Revue agents » du cockpit rendent chaque décision inspectable, et les seuils de la politique (`configs/review_policy.yml`) ne peuvent être modifiés que par PR.
6. **Champ d'application** : artefacts staging issus de l'ingestion continue (ADR-0016) et validation des sources `to_verify` (un agent RightsExpert + QualityExpert relit la source avant bascule `verified`, qui reste un changement de config soumis à PR).

## Conséquences

- `human_review_required: true` dans les manifestes staging devient `review: panel` — le champ est conservé pour traçabilité, l'acteur change (compatibilité : l'ancien champ reste lu par le cockpit).
- Le cockpit « Revue humaine » devient « Revue agents » : affichage des verdicts signés, plus de boutons d'approbation manuels.
- Aucun verrou n'est levé ; `answer_generation_allowed` reste `false`.
