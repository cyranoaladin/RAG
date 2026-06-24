# Rapport Codex — Lot 3 : ledger SQLite

## Objectif

Créer un ledger SQLite local, minimal, idempotent et testé pour suivre les
futurs runs, documents, etats, chunks et erreurs, sans ingestion ni connexion
externe.

## Fichiers créés

- `rag_pedago/__init__.py`
- `rag_pedago/ledger/__init__.py`
- `rag_pedago/ledger/db.py`
- `rag_pedago/ledger/models.py`
- `rag_pedago/ledger/repository.py`
- `rag_pedago/ledger/migrations.py`
- `rag_pedago/ledger/init_db.py`
- `data/ledger/.gitkeep`
- `docs/LEDGER_DESIGN.md`
- `tests/unit/test_ledger_schema.py`
- `tests/unit/test_ledger_repository.py`
- `tests/unit/test_ledger_recovery.py`
- `data/reports/codex_lot_3_ledger_sqlite.md`

## Fichiers modifiés

- `.gitignore`
- `Makefile`
- `pyproject.toml`
- `schema/ledger.py`

## Tests

Tests ajoutés :

- creation des tables ;
- idempotence de migration ;
- creation et cloture de run ;
- upsert de document depuis `DocumentMeta` ;
- document `rights=unknown` stocke mais non retrievable ;
- contraintes de foreign keys pour etats et chunks ;
- dernier etat documentaire ;
- unicite `(doc_id, chunk_index)` ;
- enregistrement et listing des erreurs ;
- reprise apres run echoue ;
- rollback de transaction sur erreur.

## Résultats

Commande cible du lot :

```bash
python3 -m pytest tests/unit/test_ledger_schema.py tests/unit/test_ledger_repository.py tests/unit/test_ledger_recovery.py -q
```

Resultat observe :

```text
12 passed
```

## Choix techniques

- SQLite standard via `sqlite3`, sans SQLAlchemy.
- Migrations idempotentes avec `CREATE TABLE IF NOT EXISTS` et
  `INSERT OR IGNORE` dans `schema_migrations`.
- Transactions explicites avec rollback sur exception.
- `metadata_json` contient le `model_dump(mode="json")` complet des modeles
  Pydantic.
- `chunks` accepte un upsert par `chunk_id`, mais refuse deux `chunk_id`
  differents pour le meme `(doc_id, chunk_index)`.
- `data/ledger/rag_pedago.sqlite` est ignore par Git ; seul `.gitkeep` est
  suivi.

## Limites

- Aucune ingestion reelle.
- Aucun parsing PDF.
- Aucun scraping.
- Aucune connexion Qdrant.
- Aucune connexion PostgreSQL.
- Aucun appel reseau.
- Aucun LLM.
- Pas encore de migrations incrementales version 2+.
- Pas encore de CLI de diagnostic avancee au-dela de `ledger-init` et
  `ledger-doctor`.

## Prochaines étapes

Lot 4 : importer de facon controlee des manifests JSONL locaux ou fixtures,
alimenter le ledger avec des documents decouverts, et verifier l'idempotence
sans telechargement ni scraping.

Lot 3 prêt : ledger SQLite minimal créé, testé, idempotent, sans ingestion, sans connexion externe, prêt pour un futur lot 4 d’import contrôlé de manifest.

