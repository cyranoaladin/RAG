# Rapport Codex — Lot 2 : schémas et taxonomies

## Objectif

Créer le socle de données du RAG pédagogique sans ingestion réelle : schémas
Pydantic stricts, taxonomies minimales contrôlées et documentation du contrat
metadata/retrieval.

## Fichiers créés

- `schema/document.py`
- `schema/taxonomy.py`
- `schema/ledger.py`
- `schema/source.py`
- `schema/retrieval.py`
- `schema/student_profile.py`
- `taxonomy/common/niveaux.yml`
- `taxonomy/common/types_documents.yml`
- `taxonomy/common/epreuves.yml`
- `taxonomy/common/statuts_candidats.yml`
- `taxonomy/common/competences_transversales.yml`
- `taxonomy/maths/terminale_specialite.yml`
- `taxonomy/nsi/terminale.yml`
- `taxonomy/exams/bac_general.yml`
- `taxonomy/exams/anticipee_maths.yml`
- `tests/unit/test_document_schema.py`
- `tests/unit/test_taxonomy_schema.py`
- `tests/unit/test_retrieval_schema.py`
- `tests/unit/test_student_profile_schema.py`
- `docs/METADATA_SCHEMA.md`
- `docs/TAXONOMY_POLICY.md`
- `docs/RETRIEVAL_CONTRACT.md`
- `data/reports/codex_lot_2_schema_taxonomy.md`

## Fichiers modifiés

Aucun fichier existant du lot 1 n'a ete modifie pour le lot 2.

## Tests exécutés

```bash
python3 -m pytest tests/unit/test_document_schema.py tests/unit/test_taxonomy_schema.py tests/unit/test_retrieval_schema.py tests/unit/test_student_profile_schema.py -q
```

## Résultats

- Test rouge initial confirme : les modules `schema.document`,
  `schema.taxonomy`, `schema.retrieval` et `schema.student_profile` etaient
  absents.
- Tests unitaires du lot 2 : `11 passed`.

## Choix techniques

- Pydantic v2 avec `extra="forbid"` pour refuser les champs non prevus.
- Enums partagees dans `schema/document.py` pour les dimensions stables :
  niveau, voie, statut d'enseignement, type documentaire, epreuve, candidat,
  source, droits et modalite.
- Champs critiques obligatoires dans `DocumentMeta`, notamment `rights` et
  `visibility`.
- `DocumentMeta.is_retrievable` encode la regle minimale du lot 2 :
  `rights=unknown` ne doit pas etre servi plus tard.
- `ChunkMeta` impose le lien `doc_id`, le hash, l'index et au moins un contenu
  textuel ou asset.
- Les taxonomies YAML sont validees par `TaxonomySpec`, avec refus des notions
  vides.
- Le contrat retrieval produit des filtres payload explicites depuis le profil
  eleve.

## Limites volontaires du lot

- Aucune ingestion.
- Aucun scraping.
- Aucun appel reseau.
- Aucune connexion Qdrant ou PostgreSQL.
- Aucun LLM.
- Aucun traitement PDF.
- Pas encore de ledger SQLite physique, seulement les modeles de donnees.
- Pas encore de validation croisee automatique entre chaque document et les
  fichiers YAML de taxonomie.

## Prochaine étape recommandée

Lot 3 : implementer le ledger SQLite avec tables minimales, creation de run,
mise a jour d'etat, enregistrement d'erreurs et tests de reprise apres echec.

