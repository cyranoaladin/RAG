# Couverture réelle — Lot 11 (recomptée sur fichiers staging)

## Fichiers en staging

**44 fichiers JSON** réellement déposés dans `data/staging/agents/terminale/`.

## Couverture par matière (5 notions max par matière)

| Matière | Notions trouvées | Notions non trouvées | Fichiers staging |
|---|---|---|---|
| mathematiques | 5/5 (100%) | 0 | 14 (multi-source: wikipedia+wikiversity+sous-pages) |
| nsi | 5/5 (100%) | 0 | 10 |
| philosophie | 4/5 (80%) | 1 (devoir) | 8 |
| histoire_geo | 2/5 (40%) | 3 | 4 |
| grand_oral | 2/5 (40%) | 3 | 4 |
| orientation | 0/5 (0%) | 5 | 0 |

## Comparaison avant/après

| Métrique | Lot 10.1 (devinette) | Lot 11 (article table) | Lot 11.2 (recompté) |
|---|---|---|---|
| Notions trouvées | 2/12 (17%) | 26/38 (68%) | **26/38 (68%) — confirmé** |
| Fichiers staging | non compté | écrasement possible | **44 fichiers uniques** |

Le 68% est réel après correction du faux compte (filenames uniques par source_label).

## Notions non couvertes (terminale, pilote 5/matière)

- **orientation** : inscription_cyclades, pieces_justificatives, choix_modalite, calendrier_epreuves, rattrapages (spécifique système français, pas sur Wikipedia)
- **grand_oral** : choix_questions, argumentation, liaison_connaissances (trop spécifique examen français)
- **histoire_geo** : guerre_froide, construction_europeenne, mondialisation (pages Wikipedia existent mais pas dans la table article)
- **philosophie** : devoir (la page Wikipedia est trop courte / renvoie vers une désambiguïsation)
