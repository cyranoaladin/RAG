# LOT 27 P3 — durcissement de la gate E2E face aux 5xx UI

## Cause

Le runner E2E LOT 27 P3 classait certains 5xx émis par l'hôte UI RAG comme
non bloquants lorsqu'ils visaient des assets statiques ou des endpoints
`/_stcore/*`. Il filtrait aussi des erreurs console de chargement de bundle.

## Impact

Une exécution post-déploiement pouvait afficher `network_failures_blocking = 0`
alors que Nginx avait servi des réponses 502 pour `rag-ui`. Cette divergence
rendait la gate de go-live insuffisante.

## Correction

- Toute réponse HTTP `>= 500` reçue depuis l'hôte UI RAG est ajoutée à
  `networkFailuresBlocking`, avant toute exception Streamlit ou asset.
- Un échec de handshake WebSocket Streamlit signalant un 502 est également
  bloquant avant la classification `/_stcore/*` en bruit d'infrastructure.
- En mode `post-deploy`, `ChunkLoadError`, `status of 502` et les erreurs MIME
  de bundle sont bloquants.
- Le runner ne peut afficher `PASS` que si les quatre pages ont réussi et que
  les quatre captures attendues existent et sont non vides.
- Des tests de contrat vérifient l'ordre de classification et les filtres
  console.

## Statut de production

Cette PR ne déploie rien et ne modifie aucun runtime. La production reste
bloquée jusqu'à deux E2E post-déploiement propres consécutifs, avec zéro 5xx
sur l'hôte RAG et une observation stable.
