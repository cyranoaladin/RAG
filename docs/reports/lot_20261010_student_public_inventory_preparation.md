# Lot — inventaire des dérivés étudiants et transfert privé à préparer

Base : `origin/main=fc6b7da6254eb67e7a2b26ec555b5edf17316a96`, tree
`93e9f382fb12bd49ee3489056e0536f4d66c1976`. Ce lot ne promeut pas la
candidate #312 et ne modifie ni staging ni production.

`scripts/go_live/prepare_student_public_candidate_inventory.py` relit le
registre, le manifeste agrégé et les onze sujets de la candidate #312 par
leurs SHA-256. Il lie également les 253 dérivés au manifeste approuvé #300 et
les 377 `source_placement_id` aux inventaires sources V4 non-HGGSP et V5
HGGSP, dont les manifests sont eux-mêmes liés à leurs registres de release.
Pour chaque jointure, le SHA du PDF d'origine, le titre, la matière, le niveau
et le scope sont vérifiés. L'URL de découverte provient du placement source ;
elle n'est pas déduite du lien direct au PDF. Le SHA du dérivé, son reçu et son
appartenance aux collections sont rapprochés du manifeste #300. Aucun chemin
PDF ne figure dans le nouvel inventaire.

Les sorties déterministes sont
`docs/reports/go_live/student_public_inventory_preparation_20261010/candidate_inventory.json`
et `private_transfer_allowlist.json`. La première porte 11 collections, 253
identités de dérivés et 377 placements. La seconde énumère exactement 253
fichiers `.txt` attendus avec leur SHA ; elle porte
`transfer_status=NOT_TRANSFERRED` et aucun digest observé. Elle n'est **pas**
un manifeste attestant le transfert des octets privés. Les empreintes des
sorties sont :

- `candidate_inventory.json` : `711379db9e8bc822a0295d17f77bced80a5cf1fbe527f30ac627fccdd59c139f` ;
- `private_transfer_allowlist.json` : `9346b81a078f69bdd6ca8ff183fdbfa2bde895c7765fa0009760abc34c3ac42e`.

Rejeu depuis un checkout propre du même commit source :

```bash
python scripts/go_live/prepare_student_public_candidate_inventory.py --repository-root .
python scripts/go_live/check_student_public_candidate_inventory.py --repository-root .
```

Le vérificateur relit les sources scellées et recompte les ensembles de SHA,
les paires `(collection, source_placement_id)`, les URL/titres et les fichiers
permis. Il refuse aussi un PDF, une clé de transfert observé, un champ ajouté,
une ligne éditée et un digest divergent. Les tests ciblés font échouer le
constructeur ou le vérificateur sur une source PDF substituée, un placement
inconnu ou dupliqué, un scope de collection modifié, une autorité V4 falsifiée,
une URL inventée et une allowlist transformée en fausse attestation.

Ce format est une **préparation**. Le lecteur V1 actuel de Worker A exige
encore un `physical_path` sous `01_EDUSCOL_OFFICIEL/` et le schéma historique
du PDF. Il ne doit pas consommer directement cet inventaire texte : un lecteur
du type `NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1`, la vraie
copie des 253 octets privés, puis un manifeste de transfert fondé sur des SHA
observés restent à implémenter avant publication. Aucun chemin historique
n'a été falsifié pour faire accepter un dérivé comme un PDF source.

Validation locale dans un venv propre de ce worktree : `8 passed` pour
`scripts/tests/test_student_public_candidate_inventory.py`, `ruff check` vert,
`git diff --check` vert. La commande du vérificateur retourne
`STUDENT_PUBLIC_CANDIDATE_INVENTORY_PASS=true`,
`PRIVATE_TRANSFER_STATUS=NOT_TRANSFERRED`,
`DERIVATIVE_ARTIFACTS=253` et `SOURCE_PLACEMENTS=377`.
