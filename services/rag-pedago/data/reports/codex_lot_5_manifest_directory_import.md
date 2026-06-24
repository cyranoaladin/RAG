# Rapport Codex — Lot 5 : import repertoire de manifests

## Fichiers créés

- `rag_pedago/imports/import_manifest_dir.py`
- `tests/unit/test_manifest_directory_import.py`
- `data/fixtures/manifests/batch_001/maths_terminales.jsonl`
- `data/fixtures/manifests/batch_001/nsi_terminales.jsonl`
- `data/fixtures/manifests/batch_001/candidats_libres.jsonl`
- `docs/MANIFEST_DIRECTORY_IMPORT.md`
- `data/reports/codex_lot_5_manifest_directory_import.md`

## Fichiers modifiés

- `Makefile`
- `rag_pedago/imports/manifest.py`

## Tests

Tests ajoutes :

- import reel multi-manifests ;
- statut partial avec lignes invalides ;
- detection de doublons `doc_id` ;
- detection de doublons `source_uri` ;
- detection de doublons `sha256` ;
- dry-run sans ecriture ledger ;
- garantie de non lecture `source_uri` ;
- dossier vide refuse clairement ;
- rapport Markdown global ;
- sortie CLI resumee.

## Résultats

```bash
python3 -m pytest tests/unit/test_manifest_directory_import.py -q
```

```text
10 passed
```

```bash
make test
```

```text
81 passed
```

## Limites

- Aucun document source n'est lu.
- Aucun PDF n'est parse.
- Aucun OCR.
- Aucun scraping.
- Aucun telechargement.
- Aucune connexion Qdrant.
- Aucune connexion PostgreSQL.
- Aucun LLM.
- Import non recursif uniquement.

## Prochaine étape recommandée

Lot 6 : ajouter un mode de validation qualite plus strict avant ingestion,
notamment politiques de blocage configurables pour doublons, droits inconnus et
metadonnees pedagogiques manquantes.

Lot 5 prêt : import contrôlé de répertoire de manifests JSONL locaux, dry-run, détection de doublons, rapport global, sans lecture source_uri, sans réseau, sans ingestion documentaire.

