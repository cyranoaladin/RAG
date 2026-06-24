# Rapport Codex — Lot 2.5 : consolidation schema metier

## Objectif

Consolider les schemas, taxonomies et regles metier avant le ledger SQLite :
profils AEFE/candidats libres/double cursus, carte d'examen, droits d'usage,
confiance source et taxonomies terminale plus completes.

## Fichiers créés

- `schema/exam_profile.py`
- `docs/EXAM_PROFILE_POLICY.md`
- `tests/unit/test_exam_profile_schema.py`
- `tests/unit/test_rights_policy.py`
- `tests/unit/test_source_trust_schema.py`
- `tests/unit/test_taxonomy_consolidation.py`
- `data/reports/codex_lot_2_5_schema_consolidation.md`

## Fichiers modifiés

- `schema/document.py`
- `schema/source.py`
- `schema/student_profile.py`
- `taxonomy/maths/terminale_specialite.yml`
- `taxonomy/nsi/terminale.yml`
- `docs/METADATA_SCHEMA.md`
- `docs/TAXONOMY_POLICY.md`
- `docs/RETRIEVAL_CONTRACT.md`
- `tests/unit/test_student_profile_schema.py`

## Tests ajoutés

- Existence des notions cles en maths terminale specialite.
- Existence des notions cles en NSI terminale.
- Refus des notions vides via le schema de taxonomie existant.
- Verification que les competences matiere existent dans la taxonomie commune.
- Warnings `ExamProfile` pour candidats libres, specialites insuffisantes et options incoherentes.
- Profils eleves AEFE, candidat libre, double cursus et maths expertes.
- Matrice de droits par contexte d'exposition.
- `SourceTrust` pour sources officielles verifiees et brouillons generes.

## Résultats

```bash
make test
```

Resultat observe :

```text
30 passed in 0.23s
```

## Choix techniques

- Les warnings metier sont portes par les modeles Pydantic, afin de rester
  deterministes et testables avant toute ingestion.
- Les nouvelles dimensions Nexus de `StudentProfile` sont optionnelles pour ne
  pas bloquer les profils incomplets.
- `ExamProfile` est separe de `StudentProfile` : la carte d'examen peut etre
  inconnue ou incertaine meme si le profil pedagogique est utilisable.
- Les droits sont exprimes sous forme de matrice `Rights -> AccessContext`.
- Les taxonomies utilisent des identifiants ASCII stables pour les futurs
  payloads vectoriels et rapports.
- `SourceTrust` differencie la confiance de source et les droits : une source
  fiable ne rend pas automatiquement un document exposable.

## Limites volontaires

- Aucune ingestion.
- Aucun scraping.
- Aucun appel reseau.
- Aucune connexion Qdrant.
- Aucune connexion PostgreSQL.
- Aucun traitement PDF.
- Aucun LLM.
- Pas encore de validation croisee automatique des documents contre toutes les
  taxonomies YAML.
- Pas encore de persistance SQLite des warnings ou etats documentaires.

## Points à valider avant lot 3

- Confirmer les codes de warnings a conserver comme API stable.
- Confirmer si `public_allowed` doit rester un alias historique ou disparaitre
  dans une migration ulterieure.
- Confirmer les contextes d'acces exacts pour parent, eleve inscrit,
  proprietaire de copie et administrateur.
- Confirmer la liste officielle Nexus des offres (`nexus_offer`) et groupes.
- Confirmer les libelles finaux des specialites/options pour eviter les
  variantes libres.

## Prochaine étape recommandée

Lot 3 : creer le ledger SQLite minimal en s'appuyant sur ces schemas consolides,
avec migrations simples, run records, etats documentaires, erreurs et tests de
reprise apres echec.

Lot 2.5 prêt : le modèle métier est suffisamment consolidé pour lancer un ledger SQLite minimal au lot 3, sans ingestion ni connexion externe.

