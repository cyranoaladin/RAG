# Quel périmètre la fermeture de RAG_SEARCHABILITY vise-t-elle ?

Les valeurs font autorité dans `vectorization_target_scope_audit.json`.
**Aucune vectorisation n'a été lancée.**

## La contradiction qu'il fallait lever

Le rapport d'écart exigeait que le périmètre cible soit intégralement
interrogeable, en visant le corpus pédagogique du Drive. Le plan d'exécution,
lui, interdisait d'indexer les contenus que le gate de servabilité refuse.

Les deux ne pouvaient pas tenir ensemble : atteindre la cible aurait exigé
d'indexer des centaines de contenus refusés. La condition était donc
**inatteignable sans violer la règle qui l'accompagnait** — et une condition
qu'on ne peut satisfaire qu'en enfreignant sa voisine n'est pas une condition,
c'est une impasse.

## Le périmètre retenu

**L'ensemble servable candidat** : les contenus que le gate ne refuse pas.

Deux autres candidats ont été écartés :

- **le corpus brut du Drive** — il inclut les contenus refusés, pour la raison
  ci-dessus ;
- **l'ensemble promu de la release** — c'est un sous-ensemble arbitraire du
  servable. Un contenu servable non promu doit rester interrogeable en
  préparation, et la release changera au prochain rescellement. Indexer sur la
  release ferait dépendre la recherche d'une décision de publication.

## Ce qui ne sera jamais indexé

Les contenus refusés le sont pour quatre raisons distinctes, et **aucune** ne
les rend indexables : revue PII non tranchée, provenance absente,
non-indexabilité par rôle, archive déclarée par la source.

La garantie est structurelle, pas déclarative : le périmètre indexable est
défini comme *ce que le gate ne refuse pas*. L'intersection avec les refusés
est vide **par construction**, et non parce qu'on aurait pensé à les retirer.

Les contenus promus dont la PII n'est pas tranchée sont dans cet ensemble
exclu. Ils sont dans la release ; ils ne seront pas atteignables par une
requête tant que personne n'aura décidé.

## Pourquoi cela compte

Un index construit sur un contenu refusé serait une porte dérobée autour du
gate. Le gate déciderait qu'un document ne doit pas être servi, et la recherche
le servirait quand même — sans que rien ne le signale, puisque le refus vivrait
dans une matrice et l'index dans une base.

## Ce que cet audit ne fait pas

Il ne vectorise rien, ne déclare aucune condition tenue, et ne fait baisser
aucun compteur. `rag_searchability_blocker` reste vrai, et les huit conditions
de fermeture restent fausses.
