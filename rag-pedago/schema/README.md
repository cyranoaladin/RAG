# schema/

Rôle : modèles Pydantic partagés par les manifests, profils, référentiels et
contrats de retrieval.

Peut contenir :

- nouveaux modèles stricts ;
- enums contrôlés ;
- champs optionnels rétrocompatibles.

Interdit :

- logique d'ingestion ;
- accès réseau ;
- lecture de documents sources.

Tests :

- `python -m pytest tests/unit/test_*schema*.py`
