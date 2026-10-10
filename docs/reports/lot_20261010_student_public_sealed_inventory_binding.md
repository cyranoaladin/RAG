# Lot — liaison acyclique de l'inventaire étudiant scellé

Base : PR #313, commit `56d5d672ddb7a34dd031d521ed17c12018c9824c`.
Aucune écriture staging ou production.

Le lecteur texte conservait les jointures des 377 placements, mais écartait
`release_id`, `release_manifest_sha256`, `artifact_registry_sha256`, le SHA du
manifeste des dérivés et les SHA des inventaires V4/V5. Un inventaire d'une
autre autorité pouvait ainsi passer après rescellement de son propre SHA ; le
nom de collection était aussi perdu dans la jointure vers le subject.

Le schéma final `public_successor` exige désormais 21 autorités, dont deux
ancrages nouveaux : le SHA du manifeste préparatoire et le SHA de son index.
Worker A doit relire les octets exacts des trois pièces sous
`source_preparation/` : manifeste, index et inventaire préparatoire. L'index
nomme le manifeste, l'inventaire et le registre d'artefacts ; il nomme aussi le
candidat #312, distinct du préparatoire. L'inventaire final nomme le manifeste
préparatoire, son propre registre d'artefacts et sa propre release. Ses SHA
V4/V5 et son manifeste de dérivés doivent correspondre au préparatoire ; ses
placements doivent former un sous-ensemble exact, collection comprise. Le
subject est confronté à cette même collection. Aucune comparaison du SHA du
manifeste final avec son propre inventaire n'est faite : cela créerait un cycle.

Le paquet préparatoire actuel reste `candidate/NOT_PROMOTABLE` et n'est pas une
release finale. Les trois pièces ne sont pas encore embarquées dans un paquet
final, et le validateur externe de revues, autorisations et transfert manque.
Le lecteur et `release-chain` refusent donc toujours la promotion ; aucun
statut activable n'est inféré des nouveaux digests.

Contrôles ciblés : substitution de `release_id`, registre d'artefacts,
manifeste dérivé, inventaires V4/V5, collection, ancrage d'index absent,
et entrée texte sans pièces préparatoires. Les tests V1/PDF demeurent verts.
