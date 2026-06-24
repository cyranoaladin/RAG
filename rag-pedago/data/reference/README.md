# data/reference/

Rôle : référentiel institutionnel structuré, local et sourcé.

Peut contenir :

- sources officielles ;
- niveaux ;
- examens ;
- statuts candidats ;
- contextes d'établissement ;
- claims officiels.

Interdit :

- données non vérifiées marquées comme définitives ;
- sources locales `pending` utilisées seules pour une règle définitive ;
- scraping ou téléchargement.

Tests :

- `python -m pytest tests/unit/test_official_reference_*.py`
