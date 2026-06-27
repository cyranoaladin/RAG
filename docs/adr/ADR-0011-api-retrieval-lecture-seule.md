# ADR-0011 — API de retrieval en lecture seule

- **Statut** : Accepté
- **Date** : 2026-06-27
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0008 (pgvector), ADR-0010 (cross-service governance)

## Contexte

Le retrieval pgvector fonctionne en script local (Lot 14-16). Pour l'exposer aux clients (cockpit, agents), il faut une API HTTP. Les verrous `server_start_allowed` et `runtime_api_allowed` sont actuellement à `false`.

## Décision

- **Lever** `server_start_allowed` et `runtime_api_allowed` à `true` dans le contrat pedago et la baseline.
- **Scope STRICT** : API de retrieval en LECTURE SEULE. Pas d'écriture pgvector, pas d'ingestion via l'API, pas de modification du corpus.
- **Filtrage imposé serveur** : le niveau et l'audience sont dérivés du profil authentifié côté serveur, jamais fournis par le client. Un client ne peut PAS contourner le filtrage.
- `real_documents_allowed`, `qdrant_allowed`, `curated_ingestion_allowed` restent `false`.

## Conséquences

- L'API démarre uniquement si les deux verrous sont `true` (gating réel).
- Aucune route d'écriture n'est exposée.
- Le filtrage niveau/audience est une frontière de sécurité : contournement = fuite de contenu réservé.
