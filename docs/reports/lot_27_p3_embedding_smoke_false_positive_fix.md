# LOT 27 P3 — Correction du faux positif du smoke embedding

## Cause

Le smoke lançait `docker exec` sans attacher l'entrée standard. Le heredoc
Python n'entrait donc pas dans le conteneur et la commande pouvait retourner
zéro sans exécuter le contrat embedding.

## Correction

Le script utilise désormais `docker exec -i` et le Python émet le marqueur
obligatoire `EMBEDDING_CONTRACT_PYTHON_HEREDOC_EXECUTED`. La sortie est
contrôlée après l'exécution ; l'absence du marqueur provoque un échec explicite
`EMBEDDING_CONTRACT_PYTHON_HEREDOC_NOT_EXECUTED`.

Si le modèle certifié est absent, le chargement fail-closed remonte
`EMBEDDING_MODEL_UNAVAILABLE`, équivalent au verrou
`MODEL_1024_NOT_PREPROVISIONED`. Si aucun DSN pgvector n'est disponible, le
smoke s'arrête sur `PGVECTOR_DSN_UNAVAILABLE`.

## Non-impact

- aucune intervention en production ;
- aucun déploiement ;
- aucune écriture DB ;
- aucune ingestion ;
- aucun téléchargement de modèle ;
- aucune modification du contrat embedding.

## Prochain verrou

Le modèle `intfloat/multilingual-e5-large` 1024d doit être pré-provisionné de
manière gouvernée avant de pouvoir exécuter le smoke complet.
