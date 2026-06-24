# Rapport Codex — Lot 4.5 : durcissement import manifest

## Corrections

- Ajout de `manifest_sha256` dans `ImportReport`, la CLI et le rapport Markdown.
- Detection explicite de `run_id` deja existant avant ecriture.
- Rapport Markdown restructure avec `Summary`, `Valid documents`,
  `Non retrievable documents`, `Invalid lines` et `Notes`.
- Ajout des listes `valid_doc_ids`, `not_retrievable_doc_ids` et des resumes de
  documents valides.
- Normalisation des erreurs avec `line_number`, `error_type`, `message`,
  `doc_id` et `raw_excerpt`.
- Renforcement des garanties de non lecture des `source_uri`.
- Sortie CLI enrichie avec `manifest_sha256` et `documents_not_retrievable`.

## Tests

Tests ajoutes dans `tests/unit/test_manifest_import_hardening.py` :

- hash manifest stable et hex 64 caracteres ;
- run_id existant refuse sans ecriture partielle ;
- rapport auditable avec sections et documents ;
- `source_uri` file non ouvert ;
- absence statique de dependances reseau ;
- erreurs JSON et validation normalisees ;
- compteurs coherents et lignes vides ignorees ;
- CLI enrichie.

## Résultats

```bash
python3 -m pytest tests/unit/test_manifest_import_hardening.py tests/unit/test_manifest_import.py -q
```

```text
16 passed
```

```bash
make test
```

```text
71 passed
```

## Limites

- Aucune ingestion reelle.
- Aucun parsing PDF.
- Aucun scraping.
- Aucun telechargement.
- Aucune connexion Qdrant.
- Aucune connexion PostgreSQL.
- Aucun appel LLM.
- Pas encore d'import de dossier de manifests.
- Pas encore de detection globale de doublons de `source_uri`.

## Recommandations lot 5

- Ajouter un import de repertoire de manifests JSONL locaux.
- Produire un rapport de qualite global par lot de manifests.
- Detecter les doublons de `source_uri`, `doc_id` et hash entre manifests.
- Ajouter un mode dry-run qui valide sans ecrire dans le ledger.

Lot 4.5 prêt : import manifest durci, rapports auditables, hash manifest, erreurs normalisées, aucune lecture source_uri, aucun réseau, aucune ingestion.

