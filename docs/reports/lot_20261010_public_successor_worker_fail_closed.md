# Lot — refus Worker A du successeur public non qualifié

Date UTC : 2026-10-10. Base : `57314c34a96374fa8448ffa3c208a80b20d57b9a`.

Le lecteur canonique conserve pour chaque SHA de dérivé le SHA du PDF source et
celui du reçu de dérivation. La liaison à la préparation compare ces deux
identités à l'inventaire préparatoire **et** au registre d'artefacts scellé ;
elle compare aussi la population exacte et les placements. Un inventaire
recalculé après substitution d'un seul de ces champs est refusé.

Le chargeur vérifie le couple média/inventaire avant toute branche de lecture :
texte exige `NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1`, PDF exige
`MULTILEVEL_CANDIDATE_INVENTORY_V1`. Un essai sur les 377 placements textuels
préparatoires, renommés V1 avec nouveaux SHA d'inventaire et de manifeste, est
refusé. Le lecteur historique PDF/V1 reste accepté pour les releases
historiques.

`release_mode=public_successor` exige des artefacts textuels et demeure en
refus terminal avant le manifeste de transfert et toute écriture Worker A,
même lorsque la préparation est vérifiée et que les statuts déclarés sont
`PROMOTABLE`, `REVIEWED` et `PRODUCTION_ACTIVATION_ALLOWED`. Le code ne dispose
pas encore d'un vérificateur externe qui déréférence les 21 autorités finales,
reviews exact-HEAD, autorisations et transfert observé. La seule présence de
leurs SHA ne saurait ouvrir l'ingestion. La garde d'activation se fonde sur
`release_mode`, indépendamment de l'ancien indicateur booléen.

Les tests du store et de l'attribution texte utilisent désormais des faits
unitaires explicites : leur ancien fixture texte/V1 de rehearsal ne prouve pas
la qualification d'une release complète et le chargeur le rejette. Les tests
de sabotage relisent la vraie préparation versionnée ; aucun staging ni
production n'a été modifié.
