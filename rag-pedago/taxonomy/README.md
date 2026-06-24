# taxonomy/

Rôle : taxonomies pédagogiques contrôlées par matière et niveau.

Peut contenir :

- notions ;
- sous-notions ;
- compétences ;
- propositions internes explicitement séparées.

Interdit :

- remplacer une référence officielle sans source ;
- ajouter une taxonomie officielle non validée ;
- utiliser un LLM pour décider seul d'une classification finale.

Tests :

- `python -m pytest tests/unit/test_taxonomy*.py`
