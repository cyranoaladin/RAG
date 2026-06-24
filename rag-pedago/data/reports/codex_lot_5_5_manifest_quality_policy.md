# Rapport Codex — Lot 5.5 : politique qualite manifests

## Fichiers créés

- `rag_pedago/imports/quality.py`
- `tests/unit/test_manifest_quality_policy.py`
- `docs/MANIFEST_QUALITY_POLICY.md`
- `data/reports/codex_lot_5_5_manifest_quality_policy.md`

## Fichiers modifiés

- `rag_pedago/imports/manifest.py`
- `rag_pedago/imports/import_manifest_dir.py`
- `tests/unit/test_manifest_directory_import.py`
- `docs/MANIFEST_DIRECTORY_IMPORT.md`

## Tests

Tests ajoutes :

- doublon exact de `doc_id` en warning ;
- conflit de `doc_id` bloquant ;
- doublon `source_uri` bloquant ;
- doublon `sha256` en warning par defaut ;
- droits inconnus en warning par defaut ;
- droits inconnus bloquants selon politique ;
- lignes invalides bloquantes par defaut ;
- dry-run bloque sans ecriture ledger ;
- import reel bloque sans creation de run ;
- rapport avec section qualite ;
- CLI strict avec statut qualite ;
- CLI strict avec `--allow-unknown-rights`.

## Résultats

```bash
python3 -m pytest tests/unit/test_manifest_quality_policy.py -q
```

```text
12 passed
```

```bash
make test
```

```text
93 passed
```

## Limites

- Aucune ingestion documentaire.
- Aucun `source_uri` lu.
- Aucun parsing PDF.
- Aucun OCR.
- Aucun scraping.
- Aucun telechargement.
- Aucune connexion Qdrant ou PostgreSQL.
- Aucun appel LLM.

## Prochaine étape recommandée

Lot 6 : ajouter un mode de validation qualite configure par fichier YAML et un
rapport de pre-ingestion pouvant etre relu avant tout import reel.

Lot 5.5 prêt : politique qualité configurable ajoutée, blocage strict possible, rapports qualité lisibles, aucun document source lu, aucune ingestion documentaire, aucun réseau.

