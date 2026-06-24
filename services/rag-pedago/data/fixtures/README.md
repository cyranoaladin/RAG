# data/fixtures/

Rôle : données synthétiques de tests.

Peut contenir :

- manifests JSONL fictifs ;
- URI `fixture://...` ;
- cas propres et cas volontairement problématiques.

Interdit :

- documents réels sensibles ;
- secrets ;
- fichiers d'upload historiques ;
- documents sources à parser.

Tests :

- `python -m pytest tests/unit/test_manifest*.py tests/unit/test_clean_batch_gate.py`
