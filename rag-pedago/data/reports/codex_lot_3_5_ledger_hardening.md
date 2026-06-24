# Rapport Codex — Lot 3.5 : durcissement du ledger SQLite

## Corrections effectuées

- Ajout de tests d'integrite pour les cas silencieux.
- `finish_run` leve une erreur explicite si le run est inconnu.
- Ajout de `get_document_meta` et `get_chunk_meta` avec revalidation Pydantic.
- Ajout d'une erreur claire si `metadata_json` est corrompu.
- Ajout d'un module `diagnostics.py` pour `PRAGMA integrity_check`,
  `PRAGMA foreign_key_check`, tables attendues et compteurs.
- Ajout d'une structure `MIGRATIONS` pour preparer les migrations futures.
- Mise a jour de `python -m rag_pedago.ledger.init_db --check`.
- Documentation des regles `created_at` / `updated_at` et upsert chunk.

## Tests ajoutés

- `test_finish_unknown_run_fails`
- `test_get_latest_state_unknown_document_returns_none`
- `test_record_error_unknown_run_fails`
- `test_record_error_unknown_document_fails_if_doc_id_given`
- `test_upsert_document_updates_updated_at_but_preserves_created_at`
- `test_upsert_chunk_same_chunk_id_updates_metadata`
- `test_upsert_chunk_different_id_same_doc_index_fails`
- `test_get_document_meta_revalidates_pydantic_model`
- `test_get_chunk_meta_revalidates_pydantic_model`
- `test_corrupt_document_metadata_json_raises_clear_error`
- `test_diagnostic_reports_expected_tables_and_counts`
- `test_sqlite_allowed_values_match_python_enums`
- `test_migrations_versioning_records_description_once`

## Résultats

```bash
python3 -m pytest tests/unit/test_ledger_integrity.py -q
```

```text
13 passed
```

```bash
make test
```

```text
55 passed
```

## Limites

- Pas d'import de manifest.
- Pas d'ingestion.
- Pas de parsing PDF.
- Pas de scraping.
- Pas de connexion Qdrant.
- Pas de connexion PostgreSQL.
- Pas d'appel reseau.
- Pas de LLM.

## Ce qui reste interdit

- Ecrire dans le depot historique `rag-local`.
- Copier des secrets, `.env`, credentials Google Drive ou uploads.
- Alimenter le ledger depuis des ressources reelles avant le lot d'import
  controle.
- Creer des collections vectorielles.

## Préparation du lot 4

Le ledger peut maintenant recevoir un import controle de manifests JSONL locaux
ou fixtures. Le lot 4 devra rester idempotent, sans telechargement web, et
verifier que les documents sans droits restent non retrievables.

Lot 3.5 prêt : ledger SQLite durci, diagnostics disponibles, revalidation Pydantic possible, aucune ingestion ni connexion externe.

