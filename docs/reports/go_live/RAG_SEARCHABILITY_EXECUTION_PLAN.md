# Rendre le corpus interrogeable — plan, non exécuté

Les valeurs font autorité dans `rag_searchability_execution_plan.json`.
Statut : `PLANNED_NOT_EXECUTED`. **Aucune vectorisation n'a été lancée dans ce
lot.**

## Le point de départ

Le texte canonique de tous les PDF pédagogiques est présent en préparation.
Aucun vecteur ne le référence. Le corpus est donc qualifié, gouverné, promu —
et inatteignable par la moindre requête.

## Quatre phases, et pourquoi elles ne se confondent pas

**A — vectorisation en préparation.** Uniquement la base de préparation. Les
contenus que le gate de servabilité refuse **ne sont pas vectorisés** : ni les
contenus promus refusés, ni ceux bloqués par la PII. Vectoriser un contenu
refusé le rendrait atteignable par une requête alors qu'une autorité le refuse
— l'index deviendrait une porte dérobée autour du gate.

**B — validation du retrieval.** Top-k, citations, filtres de portée, latence,
rollback. Chacun est une mesure, pas une déclaration. La latence se mesure sur
le corpus entier : un échantillon ne dit rien de ce que vivra un utilisateur.

**C — autorisation de déploiement.** Non demandée. Fermer le blocage de
recherche prouve que le corpus est interrogeable **en préparation** ; cela
n'autorise pas à le servir. Les deux sont des décisions distinctes, et les
confondre ferait d'une validation technique une mise en production.

**D — bascule de production.** Non demandée, et postérieure à C.

## Les huit conditions

Toutes sont fausses aujourd'hui. Chacune porte son action et sa preuve dans le
JSON. Deux méritent une insistance :

- **couverture du périmètre cible** — une couverture partielle ne compte pas.
  Indexer une fraction du corpus donnerait un RAG qui répond, mal, sur ce qu'il
  a ;
- **rollback éprouvé** — exécuté et vérifié, pas seulement documenté.

## Ce que fermer ce blocage ne fait pas

Il ne ferme ni la revue PII, ni l'incohérence de release, ni les bloqueurs de
qualification, ni les PR bloquantes. Il n'autorise aucun déploiement, et
`GO_LIVE_READY` reste faux.

C'est une condition nécessaire de plus, pas la dernière.
