# Le constructeur ne sait pas exclure pour cause d'actualité

Les valeurs font autorité dans `reseal_builder_capability_report.json`.
**Aucune release n'a été produite.**

## Ce que le lot devait faire

Reconstruire la release sous une identité neuve en excluant les trois contenus
que la source déclare archivés, puis prouver par comparaison que seuls les
retraits voulus ont changé.

## Pourquoi il s'arrête

Le constructeur n'expose aucun moyen d'exclure un contenu pour raison
d'actualité. Son seul mécanisme d'exclusion passe par une décision **PII** —
une autorité qui n'est pas celle en cause, et à laquelle ce lot n'a pas le
droit de toucher.

Détourner la PII pour retirer un document archivé ferait décider l'actualité
par le gate PII. C'est exactement la confusion d'autorités que ce dépôt
combat : deux endroits qui décident finissent par ne pas décider pareil.

Aucune option n'accepte non plus une liste de contenus à retirer.

## Le même défaut, un étage plus haut

Le constructeur **produit** une preuve d'actualité — il note pour chaque
artefact s'il est courant ou à revoir — et aucune sélection ne la consulte. La
dimension est calculée, enregistrée, et jamais consommée.

C'est le défaut corrigé dans la matrice de servabilité, retrouvé intact dans le
constructeur de release. Là-bas, une colonne d'actualité que le verdict ne
lisait pas laissait passer quarante archives ; ici, une preuve d'actualité que
la sélection ne lit pas rend l'exclusion inexprimable.

## Ce qu'il ne fallait pas faire

Éditer les fichiers à la main. Les trois contenus occupent cinq places sur
trois sujets, et sont nommés dans cinq fichiers de preuve. Ces fichiers ne sont
pas des listes : ils enregistrent ce qui a été mesuré. Les modifier produirait
une release scellée sur des empreintes que son propre constructeur ne
reproduirait pas — une release qu'on ne pourrait plus vérifier, donc qui ne
prouverait plus rien.

## Ce qu'il faut

Une option gouvernée d'exclusion par disposition d'actualité, ou un filtre en
amont de la sélection, adossé au gate de servabilité qui possède déjà cette
décision.

Dans les deux cas : **une PR d'outillage, pas une release.**

## Ce que ce lot a corrigé en chemin

Le préflight recensait les identités de release par `git grep` sur tout le
dépôt. C'était une seconde autorité sur un concept qui en a déjà une — le
producteur de release refuse lui-même toute identité publiée ou inscrite au
registre.

Cette seconde autorité produisait deux faux positifs : elle comptait « prise »
une identité seulement **évoquée** dans un document, et elle s'invalidait
elle-même dès que son propre rapport nommait la proposition. Le préflight
délègue désormais.

Conséquence à signaler : `production-profile-gate-2026-2027-v2` n'est pas
publiée selon l'autorité canonique. Elle était comptée prise à cause de
mentions documentaires. L'identité retenue reste `…-v3`, conformément à la
décision du propriétaire.
