# Ce que le reseal v3 exige réellement — et pourquoi je ne l'ai pas exécuté

## L'autorisation était donnée, les moyens ne suffisaient pas

Le propriétaire a autorisé le reseal et validé `production-profile-gate-2026-2027-v3`
sous réserve de re-préflight. Le re-préflight passe : l'identité est libre parmi
les dix recensées, les trois contenus à exclure sont exactement ceux visés, tous
ont leur PII claire, et aucun contenu en attente de décision personnelle n'est
touché.

Ce qui manque n'est pas l'autorisation. C'est la possibilité de produire une
release **vérifiable**.

## L'étendue réelle

Les trois contenus n'occupent pas trois places, mais **cinq** : deux d'entre eux
appartiennent à deux collections chacun. Ils sont nommés dans trois fichiers de
sujets, et dans cinq fichiers de preuve de la release — inventaire de candidats,
delta de catalogue, preuve d'actualité, preuve PII, preuve de préflight.

La release racine lie onze sujets par leur empreinte, et dix-neuf autorités par
la leur. Retirer cinq entrées oblige à recalculer les comptes attendus de trois
sujets, l'empreinte de chacun de ces fichiers, les comptes de la racine, puis à
resceller dix-neuf autorités.

## Pourquoi ne pas l'éditer à la main

Les fichiers de preuve ne sont pas des listes : ce sont des **mesures**. La
preuve d'actualité dit ce qui a été constaté, la preuve PII ce qui a été scanné,
la preuve de préflight ce qui a été vérifié. Les éditer produirait des preuves
qui ne correspondent plus à ce qui a été mesuré — une release scellée sur des
empreintes que son propre constructeur ne reproduirait pas.

Le dépôt traite cela comme une falsification d'autorité, et il a raison : une
release qu'on peut corriger à la main n'est plus une preuve de ce qui a été
servi.

## Ce qu'un reseal correct demande

Le constructeur de release sait produire ces fichiers. Il exige le miroir des
PDF — présent — et les instantanés du modèle d'embedding et du reranker, que la
release nomme. Le refaire tourner régénérerait les preuves de façon cohérente.

C'est une exécution longue, sur un modèle d'embedding réel, et dont le résultat
doit être comparé empreinte par empreinte à la release actuelle pour prouver que
**seuls** les cinq retraits ont changé. Je n'ai pas conduit cette vérification,
et je ne livre pas une release de production que je ne peux pas prouver.

## Ce qui est acquis

Le préflight est opérationnel et refuse ce qu'il doit refuser : une identité
déjà prise, un périmètre qui déborde, une intersection avec la PII. Il a d'ailleurs
révélé que `…-v2` était prise, ce qu'une intuition de numérotation aurait manqué.

L'étendue exacte de l'opération est chiffrée ci-dessus. Le reseal peut être
conduit ; il demande un lot qui lui soit consacré, avec le temps de vérifier que
la release produite ne diffère de l'actuelle que par ce qu'on a voulu retirer.
