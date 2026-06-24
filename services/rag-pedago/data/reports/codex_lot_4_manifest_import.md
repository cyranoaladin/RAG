# Rapport Codex — Lot 4 : import manifest JSONL local

## Fichiers créés

- `rag_pedago/imports/__init__.py`
- `rag_pedago/imports/manifest.py`
- `rag_pedago/imports/import_manifest.py`
- `data/fixtures/manifests/sample_documents.jsonl`
- `tests/unit/test_manifest_import.py`
- `docs/MANIFEST_IMPORT.md`
- `data/reports/codex_lot_4_manifest_import.md`

## Fichiers modifiés

- `Makefile`

## Tests

Tests ajoutes :

- import success avec lignes valides ;
- import partial avec ligne invalide ;
- import failed si aucun document valide ;
- stockage non retrievable pour `rights=unknown` ;
- idempotence documents sur double import ;
- absence d'acces au `source_uri` ;
- rapport Markdown genere ;
- absence de modules reseau `requests`, `httpx`, `urllib.request` charges.

## Résultats

```bash
python3 -m pytest tests/unit/test_manifest_import.py -q
```

```text
8 passed
```

```bash
make test
```

```text
63 passed
```

## Exemple de commande

```bash
python -m rag_pedago.imports.import_manifest data/fixtures/manifests/sample_documents.jsonl --run-id import-sample-001
```

## Limites

- Aucune ingestion de document.
- Aucun parsing PDF.
- Aucun scraping.
- Aucun telechargement.
- Aucune connexion Qdrant.
- Aucune connexion PostgreSQL.
- Aucun appel reseau.
- Aucun LLM.
- Pas encore de lecture de dossiers documentaires.

## Prochaine étape recommandée

Lot 5 : ajouter un import controle de repertoire local de manifests, toujours
sans lire les documents sources, avec detection de doublons de `source_uri` et
rapports de qualite.

Lot 4 prêt : import contrôlé de manifest JSONL local vers ledger SQLite, idempotent, testé, sans ingestion de documents, sans réseau, sans parsing PDF.

