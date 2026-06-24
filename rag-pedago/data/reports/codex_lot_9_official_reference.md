# Rapport Codex — Lot 9 : référentiel officiel institutionnel

## Sources consultées

- Éduscol — Enseigner au cycle 4 : https://eduscol.education.gouv.fr/4362/enseigner-au-cycle-4
- Ministère — Les programmes du collège : https://www.education.gouv.fr/les-programmes-du-college-470408
- BO — Attendus de fin d'année et repères annuels : https://www.education.gouv.fr/bo/19/Hebdo22/MENE1913283N.htm
- Ministère — DNB : https://www.education.gouv.fr/le-diplome-national-du-brevet-10613
- BO — DNB session 2026 : https://www.education.gouv.fr/bo/2025/Hebdo33/MENE2515977N
- Ministère — Seconde générale et technologique : https://www.education.gouv.fr/reussir-au-lycee/les-enseignements-de-la-seconde-generale-et-technologique-41651
- Ministère — Voie générale au lycée : https://www.education.gouv.fr/reussir-au-lycee/la-voie-generale-au-lycee-9749
- Ministère — Baccalauréat général : https://www.education.gouv.fr/reussir-au-lycee/le-baccalaureat-general-10457
- Ministère — Questions/réponses baccalauréat : https://www.education.gouv.fr/reussir-au-lycee/tout-savoir-sur-le-baccalaureat-les-reponses-vos-questions-325499
- Ministère — Calcul de la note au baccalauréat : https://www.education.gouv.fr/reussir-au-lycee/comment-calculer-votre-note-au-baccalaureat-325511
- Éduscol — Candidats individuels BGT : https://eduscol.education.gouv.fr/5694/candidats-individuels-au-baccalaureat-general-et-au-baccalaureat-technologique
- Éduscol — Inscriptions BGT : https://eduscol.education.gouv.fr/5682/inscriptions-au-baccalaureat-general-et-technologique
- Ministère — Mathématiques au lycée : https://www.education.gouv.fr/l-enseignement-des-mathematiques-dans-la-reforme-du-lycee-en-classe-de-premiere-et-terminale-de-la-454023
- BO — Mathématiques complémentaires : https://www.education.gouv.fr/bo/22/Hebdo30/MENE2215445N.htm
- Académie d'Aix-Marseille — candidats isolés de Tunisie : https://www.ac-aix-marseille.fr/inscriptions-aux-baccalaureats-general-et-technologique-2026-121766
- Cyclades : https://candidat.examens-concours.gouv.fr/

## Fichiers créés

- `schema/official_reference.py`
- `data/reference/official_sources.yml`
- `data/reference/levels/troisieme_generale.yml`
- `data/reference/levels/seconde_generale_technologique.yml`
- `data/reference/levels/premiere_generale.yml`
- `data/reference/levels/terminale_generale.yml`
- `data/reference/exams/dnb.yml`
- `data/reference/exams/bac_general.yml`
- `data/reference/candidate_statuses.yml`
- `data/reference/specialties.yml`
- `data/reference/options.yml`
- `docs/OFFICIAL_SOURCE_RESEARCH.md`
- `docs/OFFICIAL_REFERENCE_MODEL.md`
- `tests/unit/test_official_reference_schema.py`
- `tests/unit/test_official_reference_data.py`
- `data/reports/codex_lot_9_official_reference.md`

## Fichiers modifiés

- `schema/document.py`
- `schema/exam_profile.py`
- `schema/student_profile.py`
- `schema/source.py`
- `docs/METADATA_SCHEMA.md`
- `docs/EXAM_PROFILE_POLICY.md`
- `docs/RETRIEVAL_CONTRACT.md`

## Tests

- `python3 -m pytest tests/unit/test_official_reference_schema.py tests/unit/test_official_reference_data.py -q` : 20 passed.
- `make test` : 156 passed.

## Résultats

- Référentiel institutionnel minimal ajouté pour troisième, seconde GT, première générale, terminale générale, DNB, bac général, statuts candidats, spécialités et options.
- Les règles attendues sont testées : DNB candidat individuel avec langue vivante spécifique, bac 40/60, première à 3 EDS, terminale à 2 EDS, philosophie, Grand oral, maths expertes et maths complémentaires.
- Les sources locales IFT détaillées restent marquées `verification_status: pending`.

## Limites

- Aucune ingestion documentaire n'a été effectuée.
- Aucun PDF n'a été parsé.
- Aucun OCR, scraping massif, Qdrant, PostgreSQL ou LLM n'a été utilisé.
- Les données horaires et coefficients restent minimales ; elles devront être enrichies source par source.

## Points à vérifier manuellement

- Calendriers locaux Tunisie/IFT par session.
- Documents exacts à fournir au bureau des examens de Tunis.
- Centres d'examen et convocations individuelles.
- Tout changement de réglementation postérieur au 2026-06-14.

## Prochaine étape recommandée

Brancher le référentiel officiel dans les politiques qualité des manifests afin de signaler les documents sans `official_level_ref`, `official_exam_ref`, `official_subject_ref` ou `candidate_status_ref` lorsque le type de document l'exige.
