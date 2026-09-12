# Vectorisation en préparation — préflight, non exécuté

Les valeurs font autorité dans `vectorization_phase_a_preflight.json`.
Statut : `PREFLIGHT_ONLY_NOT_EXECUTED`.

## L'ensemble d'entrée

**L'ensemble servable candidat** : les contenus que le gate ne refuse pas. Son
empreinte est consignée, de sorte qu'une exécution ultérieure puisse prouver
qu'elle a bien porté sur cet ensemble et pas sur un autre.

Deux cibles sont écartées, et pour des raisons différentes : le corpus brut
inclut les contenus refusés ; la release promue est un sous-ensemble arbitraire
du servable, et indexer sur elle ferait dépendre la recherche d'une décision de
publication.

## Les exclusions sont prouvées vides

Aucun contenu refusé n'entre dans l'ensemble d'entrée — ni ceux dont la PII
n'est pas tranchée, ni ceux que la source déclare archivés, ni ceux sans
provenance, ni ceux non indexables par rôle, ni ceux qui sont promus tout en
étant refusés.

Ce n'est pas le résultat d'un filtrage ajouté : l'ensemble est **défini** comme
le complément des refusés. Les intersections sont vides par construction, ce
qui vaut mieux qu'un filtre qu'on pourrait oublier de rebrancher.

## Le modèle

Le manifeste de release épingle un modèle et une **révision**. La révision
présente localement est celle-là exactement. Vérifier ce point n'est pas une
formalité : un modèle voisin produirait des vecteurs de même dimension, dans un
espace différent, et la recherche renverrait des résultats plausibles et faux.

## Ce qui manque, et pourquoi je m'arrête là

Une seule condition n'est pas tenue : **la base de vectorisation dédiée n'est
pas provisionnée.**

C'est un refus délibéré, pas un oubli. La base de préparation actuelle porte le
texte canonique qui rend la revue PII réamorçable — le seul moyen de rejouer
cent quarante-neuf décisions humaines, dont vingt-trois sur des contenus déjà
promus. Y installer une extension et y écrire des vecteurs mettrait ce moyen en
risque pour un gain de commodité.

L'extension vectorielle est disponible sur le poste ; elle n'est pas installée
dans cette base, et ce lot ne l'y installe pas.

## La cible recommandée

Une base **dédiée et jetable**, restaurable depuis la sauvegarde vérifiée, avec
les vecteurs dans un schéma qui ne touche aucune table de revue. Le rollback
est alors trivial : supprimer la base suffit, et rien de ce qui compte n'a
bougé.

## Ce que la phase A ne fera pas, même exécutée

Aucune production, aucune bascule, aucune écriture dans la base de revue, aucun
contenu refusé, aucun contenu dont la PII n'est pas tranchée.

Et elle ne fermera pas le blocage de recherche à elle seule : des vecteurs sans
retrieval validé ne servent personne. Les conditions de top-k, citations,
filtres de portée, latence et rollback restent entières.
