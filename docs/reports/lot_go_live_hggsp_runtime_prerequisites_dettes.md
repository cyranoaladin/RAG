# Dette préexistante — mypy complet de rag-engine

Le contrôle ciblé des quatre fichiers Python modifiés du lot passe :
`mypy --follow-imports=skip --ignore-missing-imports` ne relève aucun défaut.

Le contrôle complet `mypy src` relève 38 diagnostics dans le worktree du lot.
Pour vérifier leur antériorité, le même contrôle a été exécuté dans un
worktree détaché du commit parent exact
`26062eb1a1d7e8645a9a213fbf3de42ba88383fa`, avec les chemins de packages
correspondant à ce commit. Il y relève 40 diagnostics. Après normalisation
des seules positions de ligne, **aucun diagnostic du lot n’est nouveau** :
les 38 diagnostics du lot appartiennent tous au jeu du parent. Deux
diagnostics du parent n’apparaissent plus dans le lot.

Commande dans chacun des deux worktrees, depuis `services/rag-engine` :
`MYPYPATH=<racine>/packages/contracts/src:<racine>/packages/release-chain/src python -m mypy src`.
L’interpréteur utilise mypy 1.11.2. La comparaison conserve le fichier, le
message et le code d’erreur ; elle retire seulement le numéro de ligne, qui
peut se décaler entre deux arbres.

La dette reste à traiter dans un lot séparé ; ce lot ne masque pas les erreurs
avec un assouplissement de la configuration mypy du dépôt.

## Tests de readiness soumis à la capacité disque du poste

La suite `scripts/tests/` donne 551 réussites, 17 tests ignorés et quatre
échecs dans `test_go_live_readiness.py`. Ces quatre mêmes tests échouent au
commit parent exact ci-dessus avec le même motif `disk_policy_ok` : le disque
local dispose d’environ 26 Gio libres alors que le garde exige 40 Gio.
Le garde de production reste intact. Les tests du lot et les gardes de
gouvernance passent ; ce défaut du banc local n’est pas masqué ni contourné.
