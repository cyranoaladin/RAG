# LOT 27 P3 — couverture métier du frontend d’ingestion

## Source de vérité

La seule source de vérité métier est `rag_collections.yml`, exposée à
l’interface par `/catalogue/v2`. La page Ingestion ne crée ni collection ni
liste métier parallèle : ses lignes et ses filtres sont calculés à partir de
la réponse de ce catalogue.

## Périmètre déclaré observé

Le catalogue déclare actuellement **35 collections**. Une ancienne mention de
38 collections est incohérente avec le catalogue actuel et ne doit pas être
utilisée comme métrique de couverture.

- Niveaux : 3e, Seconde, Première, Terminale et transversal/non applicable.
- Voies/parcours : commun, générale, STMG, transversal et candidats libres.
- Matières : mathématiques, français, histoire-géographie, NSI,
  physique-chimie, SVT, SES, philosophie, SNT, droit-économie, MSDGN,
  Grand Oral, examens, DNB et candidats libres.
- Statuts : tronc commun, spécialité, option, examen et remédiation.
- Domaines : education, exam et quarantine.

Les spécialités, options, examens transversaux, candidats libres et la
quarantaine restent visibles dans le catalogue d’ingestion, même lorsqu’ils
ne sont pas activables. La table affiche pour chaque collection son statut
d’instanciation, d’ingestion et de retrieval ainsi que la raison fournie par
le catalogue lorsqu’elle ne peut pas être sélectionnée.

## Limites de réalisation

Seules **3 instanciées** sont présentes, dont **2 retrievable** : NSI Première
et NSI Terminale constituent le retrieval effectif. Les 32 collections non
instanciées sont déclarées et visibles, mais ne deviennent pas sélectionnables
pour ingestion. Aucune auto-création n’est autorisée.

Les autres séries technologiques hors STMG sont hors scope v1, sauf décision
d’extension explicite. **LOT 28** reste obligatoire pour atteindre une
couverture pédagogique complète de toutes les matières, EDS et niveaux.
# Remédiation review inline

La colonne « Voie / parcours » privilégie désormais toute voie, path ou parcours
déclaré, y compris pour le domaine `exam`; « Transversal » ne sert qu'en absence
de parcours déclaré hors éducation.
