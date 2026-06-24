# rag_pedago/reference/

Rôle : charger, indexer et résoudre les références officielles locales.

Peut contenir :

- loader YAML ;
- index ;
- resolver de compatibilité ;
- explications de compatibilité.

Interdit :

- scraping ;
- appel réseau ;
- affirmation d'une règle `pending` comme définitive.

Tests :

- `python -m pytest tests/unit/test_official_reference_*.py`
