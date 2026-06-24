# Contracts

Rôle : contrats machine-readable pour les agents, tests et outils de diagnostic.

Peut contenir :

- étapes du pipeline metadata-only ;
- artefacts runtime ;
- commandes publiques ;
- invariants de sécurité.

Interdit :

- secrets ;
- configuration de production ;
- activation implicite de réseau, Qdrant, PostgreSQL ou LLM.

Tests concernés :

- `tests/unit/test_project_contracts.py`
- `python -m rag_pedago.project_doctor`
