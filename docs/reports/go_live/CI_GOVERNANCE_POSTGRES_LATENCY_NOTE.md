# Dette CI : la latence du job `governance postgres`

Les valeurs font autorité dans `ci_governance_postgres_latency_note.json`.

## Ce qui a été observé

Ce job tourne habituellement en un peu moins de six minutes. Deux exécutions
s'en écartent nettement : l'une a atteint le timeout de 25 minutes du workflow
et a été **annulée** — pas mise en échec —, l'autre a mis presque douze minutes
et a réussi.

Toutes les autres exécutions mesurées sont groupées autour de la même durée.

## Ce que ce n'est pas

Ce n'est pas une régression fonctionnelle. Les deux anomalies portent sur des
lots qui ne touchent **aucun** fichier de `services/` ni de `packages/`, et le
même arbre passe en moins de six minutes ailleurs. Conclure à un défaut du code
enverrait chercher là où il n'y a rien.

Ce n'est pas non plus un job qui frôlerait son plafond : avec une durée
habituelle de six minutes pour un timeout de vingt-cinq, la marge est large.
Ce qui s'est produit est un écart, pas une dérive continue.

## Ce que c'est

Une dette à suivre. Un job dont la durée varie du simple au quadruple finira
par toucher son plafond, et l'annulation qui en résulte ressemble à un échec
sans en être un — ce qui coûte un diagnostic à chaque fois.

Aucun conteneur de test n'a survécu, y compris sur le run annulé : l'étape qui
le vérifie est passée.

## Ce qu'il ne faut pas en faire

Deux points ne font pas une tendance. Ajuster le timeout maintenant masquerait
le symptôme sans rien apprendre, et optimiser à l'aveugle supposerait de savoir
où va le temps — ce que personne n'a encore mesuré.

La note existe pour que la prochaine occurrence soit reconnue comme la
troisième, et non rediagnostiquée depuis zéro.

## Ce que cette note ne ferme pas

Rien. Elle ne correspond à aucun gate et ne fait baisser aucun compteur.
