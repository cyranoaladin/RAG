# L'écart entre un corpus gouverné et un RAG interrogeable

Les valeurs font autorité dans `rag_searchability_gap.json`.

## Ce qui existe

Le texte canonique de tous les PDF pédagogiques du Drive est présent dans la
base de préparation, avec ses chunks. Rien ne manque de ce côté : le corpus a
été collecté, extrait, découpé et conservé.

## Ce qui n'existe pas

**Aucun vecteur.** Pas une colonne de type vectoriel, pas l'extension dans le
schéma mesuré. Le texte est stocké ; il n'est indexé pour aucune recherche.

`rag_searchable` vaut donc faux, et la question de la production ne se pose
même pas : aucune base de production n'a été identifiée ni interrogée.

## Trois phrases qu'il serait faux de dire

- « le RAG est complètement ingéré » — le texte est stocké, pas indexé ;
- « le corpus est interrogeable » — aucun vecteur n'existe ;
- « le corpus est prêt à servir » — la servabilité est une qualification de
  gouvernance, pas une capacité de recherche.

La confusion la plus coûteuse est la première. « Tout est ingéré » se lit
spontanément comme « le RAG fonctionne », alors que les deux sont séparés par
une étape entière que personne n'a encore faite.

## Ce que ce rapport ne ferme pas

**Rien.** Aucun gate de readiness ne mesure aujourd'hui l'exploitabilité par
recherche. Ce document constate un écart ; il ne fait baisser aucun compteur et
n'en ferme aucun.

C'est d'ailleurs le point : fermer les blocages de gouvernance — PII, release,
qualification, PR — ne rendra toujours pas le corpus interrogeable. Un go-live
prononcé sur les seuls compteurs de gouvernance livrerait un RAG qui ne répond
à rien.

## Ce qui viendra ensuite

L'ingestion vectorielle complète en préparation, puis la validation du
retrieval : citations, top-k, filtres de scope, latence, rollback. Chacun de
ces points est une mesure, pas une déclaration.
