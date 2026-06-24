# tests/

Rôle : vérifier schémas, référentiels, workflows metadata-only, ledger et
contrats projet.

Peut contenir :

- tests unitaires ;
- fixtures temporaires via `tmp_path` ;
- tests de contrats machine-readable.

Interdit :

- réseau ;
- lecture de `source_uri` ;
- dépendance à une base de production ;
- tests qui nécessitent Qdrant, PostgreSQL ou LLM.

Commande principale :

```bash
make test
```
