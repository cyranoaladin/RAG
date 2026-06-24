# rag_pedago/ledger/

Rôle : ledger SQLite local pour runs, documents metadata-only, erreurs, review
audit et controlled import audit.

Peut contenir :

- migrations SQLite ;
- repository transactionnel ;
- diagnostics ;
- modèles d'audit.

Interdit :

- stockage de secrets ;
- connexion PostgreSQL ;
- vector store ;
- ingestion documentaire.

Tests :

- `python -m pytest tests/unit/test_ledger_*.py tests/unit/test_review_audit_ledger.py`
