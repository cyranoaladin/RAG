# LOT 27 P3 — alignement du contrat d'embedding v2

## Constat

L'audit de reprise a constaté un contrat incohérent : la table v2
`rag_chunks.vector` est déclarée en `vector(1024)`, tandis que le compose actif
annonçait `EMBED_DIM=768` et `nomic-embed-text:v1.5`. Le runtime Ollama
observé produisait donc des vecteurs 768d. Le code des routes v2, le catalogue
et le schéma SQL documentent déjà `intfloat/multilingual-e5-large` en 1024d.

Cette divergence interdit une migration directe de Chroma legacy (768d) vers
pgvector v2 (1024d) : aucun padding ni tronquage ne préserve la sémantique des
embeddings.

## Décision canonique

Le contrat v2 est figé sur :

- modèle : `intfloat/multilingual-e5-large` ;
- dimension déclarée et native : `1024` ;
- colonne pgvector : `vector(1024)`.

Le compose v2 des services API et worker reprend ces deux valeurs. Le code
refuse un modèle différent, une dimension déclarée différente, une dimension
native différente ou une dimension pgvector différente. Il n'existe aucun
fallback vers un modèle 768d, aucun padding et aucun tronquage.

## Contrôles ajoutés

- validation commune du modèle, de la dimension native et du schéma pgvector
  avant toute requête ou écriture vectorielle v2 ;
- chargement local-only du modèle : une image où le modèle 1024d n'est pas
  pré-provisionné refuse l'opération au lieu de télécharger ou de changer de
  modèle ;
- champs non sensibles dans `/health` : modèle, dimension déclarée, dimension
  runtime lorsqu'elle est chargée, dimension pgvector et état du contrat ;
- script read-only `scripts/e2e/smoke-embedding-contract.sh` pour contrôler
  l'image et la base avant réingestion ;
- tests de contrat contre tout retour à `EMBED_DIM=768` ou au modèle nomic.

## Périmètre et non-impact

Cette PR ne modifie ni base de données, ni Nginx, ni données, ni règle
d'ingestion, ni collections. Elle ne déclenche aucune ingestion, migration,
restauration ou action de production. Les rapports d'audit de présence des
données (#64) et de mapping Chroma vers pgvector (#65) restent inchangés.

## Prérequis et déploiement futur

Avant une image UI/API future ou toute réingestion gouvernée, le modèle exact
doit être présent dans l'image ingestor et le smoke d'embedding doit réussir.
Si le modèle n'est pas présent, le déploiement/réingestion est bloqué. Après
validation de cette PR et des PR #63, #64 et #65 selon leur séquence approuvée,
le déploiement devra être atomique avec `RELEASE_READY`, sans changement de
schéma, puis les E2E durcis et les contrôles de données seront rejoués.

## Rollback

Le rollback est UI/API-only vers la release atomique précédente validée. Il ne
doit jamais modifier pgvector, Chroma ou les corpus. Tant que la réingestion
gouvernée n'est pas explicitement autorisée et revue, le go-live reste bloqué.
