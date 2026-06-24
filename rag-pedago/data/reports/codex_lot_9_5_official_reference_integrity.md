# Rapport Codex — Lot 9.5 : intégrité du référentiel officiel

## Objectif

Durcir le référentiel officiel avant son branchement dans les politiques qualité des manifests.

## Fichiers créés

- `tests/unit/test_official_reference_integrity.py`
- `data/reference/establishment_contexts.yml`
- `data/reference/official_claims.yml`
- `data/reference/subjects/common_subjects.yml`
- `data/reference/exams/eaf.yml`
- `data/reference/exams/anticipee_maths.yml`
- `data/reference/exams/bac_specialite_ecrit.yml`
- `data/reference/exams/philosophie.yml`
- `data/reference/exams/grand_oral.yml`
- `data/reference/exams/controle_continu_bac.yml`
- `data/reference/exams/dnb_scolaire.yml`
- `data/reference/exams/dnb_candidat_individuel.yml`
- `docs/OFFICIAL_REFERENCE_INTEGRITY.md`
- `data/reports/codex_lot_9_5_official_reference_integrity.md`

## Fichiers modifiés

- `schema/official_reference.py`
- `data/reference/levels/troisieme_generale.yml`
- `data/reference/levels/terminale_generale.yml`
- `data/reference/exams/dnb.yml`
- `data/reference/exams/bac_general.yml`
- `data/reference/candidate_statuses.yml`
- `data/reference/options.yml`
- `data/reference/specialties.yml`
- `tests/unit/test_official_reference_data.py`
- `docs/OFFICIAL_REFERENCE_MODEL.md`
- `docs/OFFICIAL_SOURCE_RESEARCH.md`
- `docs/RETRIEVAL_CONTRACT.md`
- `docs/EXAM_PROFILE_POLICY.md`

## Tests

- `python3 -m pytest tests/unit/test_official_reference_integrity.py -q` : 17 passed.
- `make test` : 173 passed.

## Résultats

- Intégrité référentielle testée entre sources, niveaux, examens, sujets, statuts candidats, contextes et claims.
- AEFE est séparé comme contexte d'établissement ; le statut candidat `aefe` est conservé seulement comme compatibilité dépréciée.
- Les examens composés sont séparés en sous-épreuves structurées.
- Les claims officielles couvrent les champs réglementaires critiques.
- Les sources et claims `pending` ne peuvent pas soutenir seules une règle définitive.

## Limites

- Aucun document pédagogique n'a été ingéré.
- Aucun PDF n'a été parsé.
- Aucun OCR, scraping massif, Qdrant, PostgreSQL ou LLM n'a été utilisé.
- Les horaires restent `null` quand ils ne sont pas vérifiés dans ce lot.

## Prochaine étape recommandée

Brancher ces contrôles dans la politique qualité des manifests : documents officiels ou examens sans référence officielle structurée devront produire un warning ou un blocage selon le mode strict.
