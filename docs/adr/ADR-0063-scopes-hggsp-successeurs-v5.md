# ADR-0063 — Scopes HGGSP successeurs de la release V5

## Décision

La release `production-profile-gate-2026-2027-v5-hggsp` reçoit deux nouveaux
identifiants de retrieval, `prod_hggsp_premiere_specialite_v3` et
`prod_hggsp_terminale_specialite_v3`. Chacun lie le digest du subject de la
release successeur aux dimensions d'accès déjà gouvernées pour HGGSP par
ADR-0053. Le registre de noms
`packages/contracts/authorities/production-profile-scope-successors-hggsp-v5.yml`
lie ces identifiants au manifeste successeur et au registre mixte V4 + HGGSP.
Le registre de politique externe
`docs/governance/retrieval_scope_policy_registry_hggsp_v5.yml` lie les
digests du manifeste, des deux subjects, du programme et du registre mixte.
Ses dimensions d'accès sont vérifiées champ par champ contre le registre V4
épinglé. Le producteur canonique
`packages/contracts/scripts/build_retrieval_scope_artifacts.py` émet les
artefacts après croisement des placements, programmes et visibilités.
Le wrapper HGGSP recalcule aussi la preuve d'admissibilité de chacun des 74
placements des deux subjects scellés : tous doivent être `reviewed`, `active`
et `official_snapshot`, et leurs comptes doivent correspondre à l'évidence
versionnée du registre V5. Une divergence refuse l'émission.
Les scopes V4 `_v2` et leurs digests restent disponibles et inchangés.

Le contrat `nexus-contracts` passe de `0.21.0` à `0.22.0` : deux artefacts de
scope packagés sont ajoutés au registre explicite. Aucun droit ni dimension
de politique nouveau n'est introduit. Une identité ou une autorisation de
scope V4 `_v2` ne peut désigner l'un des nouveaux subjects.

## Conséquences

L'image de retrieval épinglée pour le complément HGGSP doit porter cette
version du contrat. L'émission et la vérification des deux scopes sont
déterministes à partir de la release scellée, des programmes, du registre
mixte et des politiques gouvernées. Leur enregistrement r4 attend une revue
humaine distincte, ouverte et approuvée à son HEAD exact.
