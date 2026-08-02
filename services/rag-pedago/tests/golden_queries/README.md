# Spécification golden du pilote LOT39bis

Ce répertoire porte les requêtes normatives du pilote `libre_terminale` pour les mathématiques et la NSI. LOT39bis décrit ce qui devra être évalué ultérieurement ; il ne contient aucun résultat de retrieval, aucune référence de document ou de chunk et aucune baseline réelle.

Chaque fichier matière utilise `schema_version: 1` et déclare exactement `subject`, `programme_version`, `collection` et `queries`. Une requête contient les champs stricts suivants :

- `id`, `category`, `notion`, `intent` et `text` ;
- `filters`, identiques au scope LOT38 et complets jusqu’à la matière et la collection ;
- `expected`, avec `outcome`, `official_program_reference`, `pedagogical_expectation`, `candidate_source_class` et `must_not_return`.

Les catégories admises sont `positive`, `no_source`, `confusion` et `adversarial`. `notion` vaut `null` uniquement pour `no_source`. Une requête positive attend `answer` et une liste `must_not_return` vide. Les cas `no_source` et `adversarial` attendent `refuse`; les cas `confusion` attendent `answer`; ces trois catégories portent au moins une exclusion explicite.

L’auditeur `pilot-golden-spec-audit` vérifie exhaustivement les 255 requêtes, les cardinalités, le scope, les taxonomies, les seuils, l’unicité, le contenu et l’absence récursive de champs prétendant connaître des résultats réels. Un SHA-256 prouve uniquement l’intégrité des octets contrôlés ; il ne prouve ni l’identité ni l’autorité de leur auteur. Cet audit offline ne peut donc rendre que `HUMAN_REVIEW_PENDING` ou `HUMAN_REVIEW_INVALID`. Une future approbation dépend d’un readback indépendant et authentifié fourni par LOT41A, hors de ce diagnostic local.
