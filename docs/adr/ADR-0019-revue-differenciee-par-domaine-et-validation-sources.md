# ADR-0019 — Revue différenciée par domaine (exam) et validation agentique des sources

- **Statut** : proposé (LOT 31)
- **Date** : 2026-07-26
- **Amende** : ADR-0018 (règles du SubjectExpertAgent) ; ADR-0009 (acteur de la bascule `to_verify` → `verified`)
- **Contexte** : dette D-28-01 — les taxonomies `exams/` sont des spécifications d'examen (candidats, épreuves, métadonnées), pas des listes de notions : le SubjectExpert les lisait comme « vides » et quarantainait systématiquement les artefacts examens. Par ailleurs, 11 sources eduscol `to_verify` attendaient une validation que la directive plateforme impose désormais par agents.

## Décision

1. **Revue différenciée par domaine.** Le SubjectExpertAgent lit le `domain` de la collection cible dans le catalogue :
   - `domain: exam` → verdict aux **marqueurs d'examen** configurés (`session`, `sujet`, `épreuve`, `annales`, `corrigé`, `baccalauréat`, `durée`, `examen` ; seuil `min_markers: 2`) au lieu de la couverture notionnelle. Un sujet d'examen se juge à sa nature d'épreuve, pas à la couverture d'un programme.
   - tout autre domaine → couverture des notions de la taxonomie (inchangé).
   - entrée catalogue absente → quarantaine (fail-closed, inchangé).
2. **Validation des sources par agent.** `agents/source_validator.py` relit chaque source `to_verify` avec les règles RightsExpert (provenance → droits via `rights_map`, règle dure inchangée) et QualityExpert (HTTP 200, substance ≥ `min_words`, aucun motif interdit / challenge WAF). Chaque verdict est **signé** (SHA-256) et consigné (`data/ledger/source_validation.jsonl`, rapport `data/reports/source_validation_latest.md`).
3. **La bascule reste gouvernée.** Le validateur ne modifie **jamais** `eduscol_sources.yml` : la bascule `status: verified` reste un changement de configuration soumis à PR, éclairé par les verdicts signés de l'agent.

## Conséquences

- Les 2 quarantaines systématiques (EAM, épreuves terminales) deviennent des verdicts fondés : un dépôt riche en marqueurs d'examen est approuvé, un dépôt sans marqueurs est rejeté avec raison explicite.
- La règle dure « droits inconnus → quarantaine » s'applique aussi à la validation des sources (non délégable, inchangée).
- Aucun verrou levé ; le panel n'écrit toujours pas dans pgvector.
