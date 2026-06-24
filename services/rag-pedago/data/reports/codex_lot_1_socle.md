# Rapport Codex — Lot 1 Socle

## Objectif

Créer un nouveau dépôt local isolé pour le RAG pédagogique Nexus Réussite sous
`/home/alaeddine/Bureau/rag-pedago`, sans modifier le dépôt historique
`/home/alaeddine/Bureau/rag-local` ni les services de production.

## Fichiers créés

- `AGENTS.md`
- `README.md`
- `pyproject.toml`
- `.env.example`
- `.gitignore`
- `Makefile`
- `docs/LEGACY_RAG_READONLY.md`
- `scripts/doctor.py`
- `tests/test_project_scaffold.py`
- fichiers `.gitkeep` pour conserver les dossiers vides du socle
- `__init__.py` minimaux pour les packages Python de base

## Commandes exécutées

```bash
pwd
git status --short || true
ls -la /home/alaeddine/Bureau
test -d /home/alaeddine/Bureau/rag-pedago && echo "RAG_PEDAGO_EXISTS" || echo "RAG_PEDAGO_NOT_EXISTS"
mkdir -p /home/alaeddine/Bureau/rag-pedago
git -C /home/alaeddine/Bureau/rag-pedago init
python3 -m pytest tests/test_project_scaffold.py -q
python3 scripts/doctor.py
make doctor
make test
git status --short
```

## Tests exécutés

```bash
python3 -m pytest tests/test_project_scaffold.py -q
make doctor
make test
```

## Résultats

- Test rouge initial confirmé : le socle attendu était absent.
- `make doctor` passe.
- `make test` passe avec `3 passed`.
- Aucun SSH exécuté pendant la création du lot 1.
- Aucun secret copié.
- Aucune ingestion, aucun scraping, aucune connexion Qdrant ou PostgreSQL.

## Limites du lot

- Les schémas Pydantic ne sont pas encore implémentés.
- Le ledger SQLite n'est pas encore créé.
- Les configurations YAML métier sont encore absentes.
- Le pipeline d'ingestion n'est pas encore implémenté.
- L'API retrieval n'est pas encore implémentée.
- Docker Compose n'est pas encore configuré pour ce nouveau dépôt.

## Prochaine étape recommandée

Lot 2 : implémenter les schémas Pydantic dans `schema/`, en commençant par
`schema/document.py`, avec tests unitaires de validation stricts.

