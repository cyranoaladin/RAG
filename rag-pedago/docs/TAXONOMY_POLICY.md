# Politique de taxonomie

Les taxonomies controlent le vocabulaire pedagogique utilise par le RAG :
niveaux, types documentaires, epreuves, statuts candidat, competences, notions
et sous-notions par matiere.

Elles servent a eviter les tags libres incoherents. Par exemple, `recurrence`,
`raisonnement_par_recurrence` et `suites recurrentes` peuvent designer des
objets proches, mais le systeme doit savoir quelle forme est autorisee pour les
filtres, l'evaluation et les rapports.

## Sources officielles et propositions

Une taxonomie issue d'un programme officiel ne doit pas etre modifiee a la main
sans validation. Les notions inconnues detectees plus tard par parsing,
classification ou LLM devront etre placees dans `taxonomy/proposals/`, puis
revues avant integration.

## Validation

Une taxonomie valide doit avoir :

- un identifiant stable ;
- une matiere ;
- un niveau ;
- une voie ;
- un statut d'enseignement ;
- une version de programme ;
- au moins un theme ;
- des notions non vides ;
- des competences controlees.

Le lot 2 fournit `schema.taxonomy.TaxonomySpec` pour valider ce noyau minimal.

## Consolidation terminale

Le lot 2.5 enrichit les taxonomies terminale specialite mathematiques et NSI
afin de couvrir les besoins prioritaires Nexus :

- mathematiques : suites, fonctions, exponentielle/logarithme, integration,
  equations differentielles, probabilites, geometrie dans l'espace et
  algorithmique ;
- NSI : structures de donnees, algorithmique, bases de donnees, architectures
  et programmation orientee objet.

Les identifiants de notions restent en ASCII stable (`fonction_exponentielle`,
`representations_parametriques`, `diviser_pour_regner`, etc.) pour pouvoir etre
utilises dans les payloads Qdrant, les rapports et les tests sans dependance a
une graphie humaine variable.

Les competences utilisees dans une taxonomie matiere doivent exister dans
`taxonomy/common/competences_transversales.yml`.
