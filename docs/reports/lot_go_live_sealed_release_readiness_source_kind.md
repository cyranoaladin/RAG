# Lot go-live — réconciliation de l'attribution des releases scellées V2

## Défaillance observée

Sur le staging V4/V5, la base contient les 315 artefacts publiés et le
validateur de démarrage signale `wrong_artifact_metadata` pour chacune des 11
collections. La comparaison des champs sur un artefact DGEMC montre que seul
`source_kind` diverge : le produit porte `sealed_release` alors que le
validateur attend le nom d'hôte de `source_url`. Le runtime refuse alors de
démarrer (`release database reconciliation unavailable`). Aucun manifeste ni
enregistrement produit n'est modifié par ce lot.

## Cause et correction

`derive_sealed_release_artifact_attribution` établit explicitement
`source_kind=sealed_release` : la release est acquise par transfert scellé et
n'a pas d'URL canonique de découverte. Cette valeur fait partie de
l'attribution durable relue et attestée avant publication ; Worker B publie
cette attribution sans la recalculer. `source_url` reste une URL de provenance,
dont l'hôte donne `source_label`, pas le mode d'acquisition.

`evaluate_release_snapshot` attend désormais `sealed_release` **uniquement**
pour `MULTILEVEL_AGGREGATE_RELEASE_V2`. Le comportement Wave 0 et multilevel V1
reste identique. Les comparaisons exactes de `source_label` avec l'hôte du
manifeste, de `source_uri` avec son URL, du SHA-256 de contenu, du type de
document, des droits et du statut officiel demeurent obligatoires. Une
substitution de `source_kind` par le domaine, qui passait avant, est refusée.

Il s'agit d'une correction de parité entre l'attribution déjà gouvernée et
le lecteur de readiness, sans modification du contrat `nexus-contracts`, des
verrous de gouvernance, du schéma, des manifestes ou des données.

## Vérification locale

- Deux tests de régression V2 ont échoué avant correction dans les deux sens
  (`sealed_release` refusé et domaine accepté), puis réussi après correction.
- La fixture V2 de partage d'artefact reflète maintenant l'attribution que
  le worker publie ; son test reste vert.
- `tests/test_release_readiness.py` : 192 réussites, 0 échec, avec les sources
  de ce worktree explicitement placées dans `PYTHONPATH`.
- `tests/test_h2f_artifact_attribution.py`,
  `tests/test_sealed_release_attribution.py` et
  `tests/test_publication_resume.py` : 55 réussites, 0 échec.
- Ruff sur les deux fichiers Python modifiés et `git diff --check` : verts.
- Venv isolé de ce worktree : les 16 tests ciblés de réconciliation et de
  dérive passent. Le reste de la suite a été exécuté avec les dépendances
  système et les sources du worktree épinglées par `PYTHONPATH` ; la CI de la
  PR reste le contrôle complet.

## Limite opérationnelle

Cette correction ne vaut pas qualification staging : après fusion, rebâtir
l'image API depuis le nouveau `main`, relire le staging en préflight, puis
rejouer la réconciliation HTTP réelle des 11 collections. Le validateur doit
encore refuser toute divergence d'un autre champ gouverné.
