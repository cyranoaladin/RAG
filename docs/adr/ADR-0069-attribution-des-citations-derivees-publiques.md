# ADR-0069 — Attribution des citations de dérivés textuels publics

- **Statut** : proposé.
- **Date** : 2026-10-10.
- **S'appuie sur** : ADR-0001, ADR-0013, ADR-0064 et ADR-0068.

## Contexte

La release publique successeur sert des passages textuels dérivés de PDF Éduscol, tandis que les PDF sources restent internes. La citation historique du contrat de retrieval ne porte que le libellé, l'URL, la page et la classe de droits. Elle ne suffit pas à restituer l'attribution exigée par l'autorité Éduscol–Etalab et la politique de dérivation. Les quatre valeurs d'attribution existent dans les reçus scellés des dérivés ; elles doivent être persistées et projetées depuis ces preuves, sans être reconstruites d'après le domaine ou le texte du résultat.

## Décision

`nexus-contracts` passe de 0.23.0 à 0.24.0 et ajoute à `Citation` quatre champs optionnels : `licensor`, `licence_id`, `source_updated_at` et `derivative_notice`. Leur présence est indivisible ; une citation qui n'en porte qu'une partie est invalide. Une citation portant cette attribution exige une page source. La date conserve la valeur ISO de la preuve, soit une date civile, soit un horodatage UTC complet ; aucune conversion silencieuse ne lui attribue une autre signification. La sérialisation d'une citation historique sans ces champs reste inchangée.

Le chemin API v2 transmet ces champs depuis la métadonnée gouvernée du hit à la citation contractuelle. Le BFF valide le schéma partagé, puis le Cockpit affiche le concédant, la licence, la date, la mention de dérivation et la page avec un lien vers l'URL source. L'affichage n'implique aucun lien de téléchargement du PDF local, rendu de page ou image. Les réponses internes historiques conservent leur forme.

La table des artefacts conserve aussi `is_text_derivative`, un marqueur non nul alimenté par le type du dérivé scellé. Une contrainte impose qu'il soit vrai si et seulement si les quatre champs d'attribution sont complets ; les artefacts historiques gardent `false` et des champs nuls. Les deux canaux de recherche transmettent ce marqueur. L'API refuse une discordance, une page absente ou la suppression de citation d'un dérivé. Une disparition simultanée des quatre champs ne transforme donc pas silencieusement le passage en résultat historique.

## Condition de mise en service

La migration et la projection PostgreSQL doivent stocker les quatre valeurs des dérivés depuis les reçus scellés. Le simple ajout de champs au modèle d'API ne constitue pas une preuve de cette persistance. Le test HTTP étudiant doit confirmer leur présence sur chaque passage public servi, ainsi que le refus d'une attribution partielle. Aucun libellé ou horodatage par défaut ne doit être inventé au moment du retrieval.
