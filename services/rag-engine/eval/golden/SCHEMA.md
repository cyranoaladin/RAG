# Suite dorée NSI (LOT 39)

Chaque fichier `*.yml` / `*.yaml` contient une liste de requêtes dorées.

Champs par requête :

- `id` : identifiant stable.
- `query` : formulation élève en français.
- `intent` : `definition`, `methode`, `exercice`, `annale`, `correction`.
- `collection` : collection v2 cible (`rag_nexus_nsi_terminale_specialite` ou `rag_nexus_nsi_premiere_specialite`).
- `niveau` : `premiere` ou `terminale`.
- `relevant_chunk_ids` : liste non vide d'IDs `chunk_id` pertinents (requis ;
  l'alias `relevant_chunk` est accepté).
- `graded_relevance` : map optionnelle `{chunk_id: score}` avec des scores finis
  et positifs ou nuls. Ses grades strictement positifs doivent correspondre à
  `relevant_chunk_ids`.
- `must_not_return` : liste requise des IDs qui constituent une fuite
  pédagogique ; elle peut être vide pour une requête donnée.

Règle d'interprétation :

- Si `graded_relevance` est absent, les `relevant_chunk_ids` sont évalués avec score `1.0`.
- `niveau` et `collection` doivent former une paire cohérente parmi les deux
  collections NSI autorisées.
- Un fichier vide, une clé de suite inconnue ou une requête sans jugement
  pertinent rend toute la suite invalide.
- `must_not_return` est utilisé pour calculer `filter_leak_rate`.
- Les métriques LOT 39 évaluent **tout le périmètre doré** (200+ requêtes minimum).

Exemple :

```yaml
- id: nsi_term_arbres_001
  query: "Comment fonctionne un arbre binaire de recherche ?"
  intent: methode
  collection: rag_nexus_nsi_terminale_specialite
  niveau: terminale
  relevant_chunk_ids:
    - c0123
    - c0456
  graded_relevance:
    c0123: 3
    c0456: 1
  must_not_return:
    - c9876
    - c6543
```
