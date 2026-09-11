# Le défaut d'actualité, et ce que sa correction change

Les valeurs font autorité dans `currentness_archive_gate_impact.json`.

## Le défaut

La matrice de servabilité calculait une colonne `currentness` — archive
déclarée, actuel déclaré, transition, à vérifier — et son verdict ne la
consultait **jamais**. La cascade lisait le programme, la PII, l'indexabilité
et la provenance ; l'actualité n'y figurait pas.

Une dimension calculée mais non consommée est pire qu'une dimension absente :
elle donne l'apparence d'un contrôle. Un lecteur voyait une colonne
`ARCHIVE_DECLARED` et pouvait croire que quelque chose en tenait compte.

## Ce que cela produisait

Des contenus que **la source elle-même déclare archivés** ressortaient
candidats servables. Trois d'entre eux étaient déjà dans la release promue,
dont un rangé sous `90_ARCHIVE_CATALOGUE/` — le dossier d'archive du corpus.

La politique d'actualité l'interdit pourtant explicitement. Elle range
« ressusciter un document déclaré archive par la source » parmi ses effets
prohibés, et pose que le repli réseau ne renverse jamais une déclaration
positive d'archivage : ne pas pouvoir vérifier une URL n'annule pas ce que la
source a dit.

Le défaut n'était donc pas une politique manquante. La politique existait,
disait la bonne chose, et n'était appliquée nulle part.

## La correction

La politique produit désormais une disposition d'actualité, et **rien
d'autre**. La composition appartient au gate de servabilité, qui interroge les
autorités dans l'ordre et nomme celle qui refuse. Un verdict sans adresse
obligerait à deviner laquelle des six dimensions a parlé.

L'ordre est préservé tel qu'il avait été décidé avant ce lot : une
incompatibilité de programme prouvée prime sur toute autre dimension, la PII
vient ensuite, puis l'actualité. Ce lot n'a pas renversé cette hiérarchie — il
y a inséré l'actualité, qui en était absente.

## Pourquoi le drapeau ne peut plus mentir

`applied: true` n'est pas une déclaration. Le constructeur de la matrice
**charge** la politique et **refuse de se construire** si elle ne s'applique
pas. Remettre le drapeau à `false` casse la matrice — c'est le comportement
voulu : le drapeau et le comportement ne peuvent pas diverger.

C'est ce qui distingue cette application d'une bascule. Une bascule aurait fait
tomber un compteur sans qu'aucun document ne change de verdict.

## Ce qui reste à décider, et qui ne m'appartient pas

Trois contenus déjà promus sont désormais refusés par le gate d'actualité. Les
retirer de la release promue exigerait une **nouvelle identité de release**.

**Aucune release n'a été modifiée par ce lot.** Le rapport les nomme, avec leur
empreinte, leur chemin et leur verdict avant et après. La décision appartient
au propriétaire du corpus, pas au script qui a découvert l'écart.
