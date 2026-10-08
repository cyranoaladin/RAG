# Dettes de validation — lot observabilité retrieval v2

Base `origin/main` : `ee35544bce5af74d6186ea0ef61f6902a2258ffe`. Les erreurs ci-dessous concernent des fichiers inchangés par ce lot et sont vérifiables sur cette base.

- `make install` dans un `.venv` neuf échoue à télécharger `python-docx==1.1.2` : la résolution DNS de `pypi.org` échoue. Aucune dépendance éditable d'un autre worktree n'a été installée dans ce venv. Les tests ciblés ont été lancés avec le Python disponible et `PYTHONPATH` explicite vers les paquets du worktree courant.
- La collecte de `pytest -q -m 'not integration'` échoue dans les suites legacy par `ModuleNotFoundError: chromadb` et `ModuleNotFoundError: google.oauth2`, faute d'installation complète. Il s'agit d'une limite de l'environnement local, pas d'un test retrieval devenu rouge.
- `mypy src` signale six erreurs dans `pedagogical_chunker.py`, `retrieval_scope_v2.py`, `embedding_provider.py` et `api.py`, tous inchangés par ce lot. Aucun diagnostic n'est signalé dans les modules modifiés.

La CI de la PR devra réexécuter ces vérifications dans un environnement complet. Toute dette de reçu PII/currentness éventuelle sur la base doit être comparée au commit parent avant d'être attribuée à ce lot.
