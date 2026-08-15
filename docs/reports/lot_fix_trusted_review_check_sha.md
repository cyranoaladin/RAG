# LOT — Correction du ciblage SHA du check-run `trusted-human-review.yml`

## 1. Verdict du lot

`.github/workflows/trusted-human-review.yml`, déclenché par la commande
`/nexus-trusted-review` (événement `issue_comment`), publiait son
check-run implicite (celui que GitHub Actions attache automatiquement à
chaque job) sur le **tip de `main` au moment du déclenchement**, jamais
sur le head réel de la PR commentée — un événement `issue_comment` n'a
pas de `head_sha` naturel côté GitHub, contrairement à
`pull_request_target`. Confirmé empiriquement deux fois cette session
(runs réels sur PR #104 et PR #106 : `gh api repos/.../check-runs/<id>`
montrait `head_sha` = le tip de `main` à cet instant, jamais le head de
la PR concernée).

**Non bloquant en pratique** : ce check n'a jamais figuré dans les
`required_status_checks` de la protection de branche `main`
(`packages/contracts`, `services/rag-pedago`, `services/rag-engine`,
`services/cockpit`, `governance locks guard`, `repository controls`
uniquement) — aucun merge n'a donc jamais été bloqué ou faussement
débloqué par ce défaut. Mais l'affichage GitHub restait trompeur :
`gh pr checks` montrait ce check comme « failed » sur le head réel même
après une approbation valide, obligeant à revérifier manuellement le
JSON de décision du run à chaque fois (fait systématiquement cette
session, jamais contourné).

`GO_LIVE_READY=false`. Aucune mutation live, aucun run réel déclenché
par ce lot.

## 2. Correction

1. `checks: write` ajouté aux permissions (nécessaire pour publier un
   check-run explicitement via l'API Checks).
2. L'étape unique d'origine (résolution + évaluation) est scindée en
   trois : `scope` (résout `PR_NUMBER`/`EXPECTED_HEAD`, publiés en
   sortie de step), `evaluate` (exécute le script Python existant,
   inchangé, avec `continue-on-error: true` pour ne jamais interrompre
   le job avant que le check-run correct ait pu être publié), et
   `Publish head-pinned check-run` (`if: always()`, publie un check-run
   **explicite**, nommé « Evaluate trusted human review (head-pinned) »,
   épinglé à `steps.scope.outputs.expected_head` — le vrai head résolu,
   jamais `github.sha`).
3. Une étape finale (`Fail the job if the review was not approved`) fait
   échouer le job réellement quand l'évaluation n'a pas approuvé — le
   `continue-on-error` de l'étape `evaluate` ne doit jamais laisser le
   job entier apparaître vert silencieusement.
4. Le check-run implicite (mal épinglé pour `issue_comment`) reste
   inchangé et continuera d'apparaître — inoffensif, non supprimable
   sans réécrire l'architecture du job, mais désormais explicitement
   documenté comme secondaire : le check-run à considérer est celui
   nommé « (head-pinned) ».

## 3. Limite de vérification connue — pas contournée

`pull_request_target`/`issue_comment` exécutent **toujours** la version
du fichier workflow présente sur la branche par défaut (`main`), jamais
celle de la PR qui déclenche l'événement — propriété de sécurité
GitHub, documentée, pas un défaut. **Ce correctif ne peut donc pas être
exercé en conditions réelles avant d'être mergé sur `main`** : aucune PR
ouverte contre ce fichier ne peut prouver son propre comportement en le
déclenchant elle-même. Vérification disponible ici : structurelle
(YAML valide, permissions, présence et enchaînement exact des steps) et
mutation-testée (le point de correction précis — `head_sha=
"$EXPECTED_HEAD"` — désactivé temporairement, test dédié rouge pour la
bonne raison, restauré, suite verte). Vérification en conditions
réelles : à faire une fois mergé, sur la prochaine PR réelle qui
déclenche `/nexus-trusted-review`.

## 4. Tests

`scripts/tests/test-trusted-human-review-workflow.py` — 9 tests, zéro
accès réseau :

```
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/trusted-human-review.yml'))"
YAML OK

$ python3 -m pytest scripts/tests/test-trusted-human-review-workflow.py -v
9 passed, 6 subtests passed
```

**Mutation-testing** : `head_sha="$EXPECTED_HEAD"` remplacé temporairement
par `head_sha="${{ github.sha }}"` (soit exactement le bug d'origine
réintroduit) →
`test_check_run_is_published_explicitly_pinned_to_the_resolved_head`
échoue pour la bonne raison (chaîne attendue absente). Restauré, suite
revérifiée verte (9 passed).

## 5. Ce que ce lot ne fait jamais

- Ne modifie pas `scripts/github/trusted_human_review_github.py` (la
  logique de décision elle-même, inchangée, déjà correcte).
- Ne supprime pas le check-run implicite existant (limitation de
  l'architecture GitHub Actions pour ce type de déclencheur, documentée
  plutôt que masquée).
- Ne modifie aucune protection de branche.
- N'accorde aucun droit d'écriture au-delà de `checks: write`, déjà
  minimal pour l'action requise.

## 6. Booléens finaux

```
TRUSTED_REVIEW_CHECK_RUN_SHA_TARGETING_FIXED=true
TRUSTED_REVIEW_STRUCTURAL_TESTS_ADDED=true
TRUSTED_REVIEW_MUTATION_TESTED=true
TRUSTED_REVIEW_REAL_RUN_VERIFICATION=pending_next_merge_to_main   # limitation §3, pas contournable
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
