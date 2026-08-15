# LOT — Workflow canonique de promotion (ADR-0036, dernier blocker de PR #100)

## 1. Verdict du lot

Ajoute `.github/workflows/promote.yml` : le workflow canonique de
promotion que `sign_production_readiness_manifest_cli.py` (PR #100)
attendait pour ses arguments `--workflow-path`/`--workflow-ref`/
`--run-id`/`--run-attempt`. Il **assemble des preuves, ne signe rien, ne
déploie rien** : quatre jobs séquencés (`identity` → `h2-evidence` +
`image-provenance` → `assemble`) qui vérifient en direct qu'une PR est
réellement fusionnée dans `main` avec arbre identique (ADR-0036 §2),
appellent `_produce-h2-evidence.yml` tel quel (jamais réimplémenté), et
revérifient indépendamment qu'un run `production-image-provenance.yml`
a réellement construit ce même `merge_sha`. Le résultat est un artefact
`NEXUS-PROMOTION-EVIDENCE-V1` téléversé, jamais une signature.

`CANONICAL_PROMOTION_WORKFLOW_BUILT=true`.
`PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE` reste une décision de PR
#100 (non modifiée par ce lot) — voir §6 pour le suivi exact requis.
`GO_LIVE_READY=false`. Aucune mutation live.

## 2. Audit ADR-0036 — ce qui a été décidé

`docs/adr/ADR-0036-chaine-de-promotion-gouvernee.md` (Accepté,
2026-08-13, PR #95) décide :

1. La chaîne canonique : `merge validé → workflow de promotion →
   vérification exacte → construction d'artefacts immuables → gate de
   production → signature du manifeste de readiness → approbation de
   l'Environment production → déploiement par compte restreint → health
   checks → preuve conservée`. Le script `deploy-prod.sh` manuel devient
   une procédure break-glass, plus le chemin normal.
2. Le SHA gouverné est le **commit de merge**, lié au HEAD de PR revu par
   une égalité d'arbre stricte (`PR_HEAD^{tree} == MERGE_SHA^{tree}`) —
   jamais une comparaison partielle.
3. Le manifeste de readiness (`NEXUS-PRODUCTION-READINESS-V1`,
   `packages/contracts`) est signé Ed25519, 26 champs obligatoires,
   `extra="forbid"`. Il lie repo/PR/quatre SHA/tag/environnement/sept
   digests de gouvernance/digests OCI de toutes les images/digest du
   Compose résolu/provenance d'émission (workflow, ref, run, tentative).
4. Séparation stricte des clés (readiness ≠ review-binding) — la clé
   privée readiness ne doit jamais être accessible à ce qui produit
   seulement des preuves.
5. Pas de `expires_at` sur le manifeste : le rejeu du même
   `merge_sha`/mêmes arbres/mêmes digests est un rollback légitime, pas
   une preuve à faire expirer.

## 3. Une tension apparente entre ADR-0036 §5 et la pratique déjà établie — résolue par la pratique, documentée ici

ADR-0036 §5 dit littéralement : « La clé privée ne vit que dans
l'Environment `production` ». Lu isolément, cela suggère une clé
secrète GitHub Actions, donc une signature **en CI**. Mais
`.github/workflows/production-image-provenance.yml` — un workflow de
cette même chaîne, déjà accepté et fonctionnel — dit explicitement dans
son propre en-tête :

> « Ne signe RIEN : la clé prod-readiness-v1-2026-08-13 reste offline,
> sous contrôle propriétaire (ADR-0036 §5/§10). Ce workflow ne produit
> que des faits vérifiables ; le signer les consomme séparément. »

Et `sign_production_readiness_manifest_cli.py` (PR #100, toutes ses
révisions) n'a jamais accepté de clé autrement que via
`--private-key-file`, un fichier local à l'opérateur — jamais une
variable d'environnement CI, jamais un secret GitHub. La pratique déjà
mergée est donc univoque : la clé reste offline. `promote.yml` suit
cette pratique — aucune clé, aucun secret, ne pourrait structurellement
y entrer (aucun `secrets.*` n'apparaît dans le fichier, vérifié par
`test_never_signs_and_never_touches_a_private_key`). **Ce document
signale, sans le corriger lui-même (hors périmètre, décision de
gouvernance)** : ADR-0036 §5 mériterait un amendement futur pour
clarifier explicitement que « vit dans l'Environment production »
signifie « le geste de signature est gardé par l'approbation de cet
Environment », pas « la clé y est stockée comme secret ».

## 4. Ce que ce workflow ne fait jamais — et pourquoi (frontière structurelle, pas une omission)

**Ne résout pas le Compose de production.** La résolution réelle
(`docker compose --env-file <.env réel> config`) exige le `.env` hôte de
production — jamais versionné, jamais un secret CI par construction
(mêmes secrets que la stack de production elle-même). Un `.env` factice
en CI produirait un `compose_digest` qui n'authentifie rien : une preuve
illusoire est pire qu'une preuve absente. C'est pourquoi
`sign_production_readiness_manifest_cli.py` (Section 11) résout et
hache le Compose **lui-même, hors ligne**, avec un accès réel à ce
fichier. `promote.yml` ne duplique donc jamais cette étape — vérifié par
`test_never_resolves_compose_or_touches_env_secrets`.

**Ne signe rien, ne déploie rien** — voir §3 et les tests dédiés
(`test_never_signs_and_never_touches_a_private_key`,
`test_never_deploys`).

**N'autorise aucun contenu pédagogique** — ADR-0001 ; ce workflow
n'atteste qu'une release technique.

## 5. GitHub Environment `production` — configuration réelle auditée, pas supposée

```
$ gh api repos/cyranoaladin/RAG/environments
{"total_count":0,"environments":[]}
```

**Aucun Environment GitHub n'existe sur ce dépôt aujourd'hui.** Ni
`_produce-h2-evidence.yml` (déjà mergé, référence `environment:
production` depuis PR #95) ni ce nouveau `promote.yml` ne bénéficient
donc, à ce jour, d'une réelle protection par approbateurs requis : la
clause `environment: production` déclare une intention YAML sans
application effective côté GitHub tant qu'un administrateur du dépôt ne
configure pas cet Environment (Settings → Environments → `production` →
Required reviewers). **Non corrigé ici** : c'est une action de niveau
administrateur du dépôt, hors périmètre d'une PR de code, explicitement
signalée plutôt que contournée en silence. `PRODUCTION_ENVIRONMENT_
PROTECTION_CONFIGURED=false`.

## 6. Suivi exact requis sur PR #100 une fois ce lot mergé

`sign_production_readiness_manifest_cli.py` doit alors :

1. Retirer `--workflow-path` comme entrée opérateur libre ; le pinner en
   constante `_CANONICAL_PROMOTION_WORKFLOW_PATH =
   ".github/workflows/promote.yml"` (même classe de correctif que
   `_TRUSTED_REPOSITORY`, déjà appliquée dans PR #100). `--workflow-path`
   peut au mieux rester une assertion redondante confrontée à cette
   constante, jamais l'autorité.
2. Passer `--workflow-ref refs/heads/main` (déjà correct dans PR #100 —
   confirmé en lisant `_verify_git_and_workflow_facts`, qui compare
   contre `f"refs/heads/{run.head_branch}"`, exactement ce que
   `promote.yml` enregistre via `github.ref`, jamais
   `github.workflow_ref`).
3. `--run-id`/`--run-attempt` doivent alors référencer le run
   `promote.yml` (job `assemble`), pas un autre job de la même run —
   `github.run_id`/`github.run_attempt` sont partagés par tous les jobs
   d'une même run, donc cela reste cohérent sans changement
   supplémentaire.
4. Les fichiers `--catalog-file`/`--h2b-report-file`/`--routing-file`/
   etc. exigés par PR #100 restent téléchargés séparément par
   l'opérateur depuis l'artefact `h2-evidence-<merge_sha>-<campaign_id>`
   que `_produce-h2-evidence.yml` téléverse déjà (inchangé par ce lot) —
   `promote.yml` ne les reproduit pas dans son propre artefact
   `promotion-evidence-*`, pour ne jamais faire diverger deux copies du
   même fichier source.

Seulement après ce câblage : `CANONICAL_PROMOTION_WORKFLOW_VERIFIED=true`
puis, si tout le reste de PR #100 est par ailleurs fermé,
`PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=true`.

## 7. Propriétés minimales — closes vs. non applicables

| Propriété exigée | État | Note |
|---|---|---|
| Chemin canonique versionné | ✅ | `.github/workflows/promote.yml`, constante à pinner côté PR #100 (§6) |
| Événement explicite, jamais push/PR | ✅ | `workflow_dispatch` uniquement |
| `ref=main` exact | ✅ | `if: github.ref == 'refs/heads/main'`, deux fois (condition de job + refus explicite en premier step) |
| `head_sha` exact enregistré | ✅ | `merge_sha`/`merge_tree_sha`/`pr_head_sha`/`pr_head_tree_sha` dans l'identité + le bundle |
| Run réellement réussi, vérifiable après coup | ✅ (structurel) | Ce workflow ne peut pas observer sa propre issue en cours d'exécution — comme `_produce-h2-evidence.yml`/`production-image-provenance.yml`, c'est le consommateur (le signer, via l'API GitHub) qui vérifie `status`/`conclusion` après coup |
| `run_attempt` exact, non ambigu | ✅ | Enregistré via `github.run_attempt` ; le job `image-provenance` applique lui-même ce contrôle exact (statut/conclusion/head_sha/tentative) pour le run qu'il vérifie |
| `permissions:` minimal | ✅ | `contents: read, actions: read, pull-requests: read` au niveau workflow ; testé qu'aucun job n'élève au-delà de `read` |
| Actions `uses:` épinglées par SHA | ✅ | `actions/checkout@11d5960a...`, `actions/upload-artifact@ea165f8d...` — mêmes SHA que les workflows sœurs |
| Pas de PAT personnel | ✅ | `${{ github.token }}` uniquement |
| Pas de secret long-vécu | ✅ | Aucun `secrets.*` dans le fichier |
| Clé privée jamais reçue | ✅ | §3 |
| Pas de promotion depuis un head de PR non fusionné | ✅ | `identity` refuse `merged != true` |
| Pas d'image à tag mutable | ✅ (délégué) | `image-provenance` revérifie le run de provenance ; le pinning par digest lui-même reste la responsabilité déjà testée de `deployment_image_inventory.py` (PR #102), non redupliquée ici |
| Artefacts immuables/versionnés | ✅ | `upload-artifact`, nom dérivé `promotion-evidence-<merge_sha>-<campaign_id>`, `retention-days: 90`, `if-no-files-found: error` |
| SHA/arbre source enregistrés | ✅ | §identité |
| Run de provenance d'image lié | ✅ | Job `image-provenance`, vérification live indépendante (status/conclusion/head_sha/run_attempt) |
| Preuve H2 liée | ✅ | Job `h2-evidence`, appel `uses:` du workflow réutilisable existant |
| Digest de Compose résolu lié | ❌ (structurel, §4) | Ne peut pas être vérifié en CI sans `.env` réel — reste la responsabilité de PR #100 §11, hors ligne |
| Identités autorisation/review-binding liées | ⚠️ (partiel) | La revue de confiance (`trusted-human-review.yml`) a gardé le merge de la PR elle-même (précondition de `identity`) ; ce workflow ne revérifie pas une seconde fois la review binding ADR-0035 indépendamment — elle est déjà vérifiée par `h2b_coverage_report.py` à l'intérieur de `_produce-h2-evidence.yml` (appelé tel quel) |
| Environment `production` avec approbateurs | ⚠️ (déclaré, non provisionné) | §5 |

## 8. Vérification empirique

```
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/promote.yml'))"
YAML OK

$ python3 -m pytest scripts/tests/test-promote-workflow.py -v
13 passed, 32 subtests passed

$ python3 -m pytest scripts/tests/test-trusted-human-review-workflow.py scripts/tests/test-promote-workflow.py -q
18 passed, 39 subtests passed

$ ruff check scripts/tests/test-promote-workflow.py
All checks passed!

$ gh api repos/cyranoaladin/RAG/environments
{"total_count":0,"environments":[]}
```

Pas de suite Docker/réseau réelle exercée : ce lot n'invoque jamais
`docker`, ne touche jamais un `.env` réel, ne contacte jamais l'API
GitHub en dehors des vérifications en lecture seule effectuées lors de
la rédaction de ce rapport (confirmation que `.github/workflows/
_produce-h2-evidence.yml`/`production-image-provenance.yml` existent
bien, et que le format `--workflow-ref` correspond à ce que PR #100
vérifie réellement — lu directement depuis la branche `ops/production-
readiness-signing-tool-20260813`, jamais deviné).

## 8bis. Second round — deux défauts réels trouvés par revue indépendante

1. **Le job `identity` portait un `if:` de job en plus du refus par
   étape.** `if: github.ref == 'refs/heads/main'` au niveau du job
   produit un statut `skipped` quand la condition est fausse — jamais
   `failure`. Un dispatch sur la mauvaise ref aurait donc laissé le run
   entier apparaître **vert** (avec un job « skipped »), pas rouge :
   l'étape de refus explicite (`exit 1`) n'aurait jamais eu l'occasion
   de s'exécuter, le job entier étant sauté avant elle. Corrigé en
   retirant le `if:` de job — seul le refus par étape, qui échoue
   réellement, porte désormais la garantie fail-closed. Nouveau test
   `test_identity_job_has_no_top_level_if_and_fails_closed_on_wrong_ref`,
   mutation-testé (réintroduire le `if:` de job fait échouer ce test et
   `test_expected_jobs_exist_with_correct_shape` pour la bonne raison ;
   restauré, suite verte).
2. **En cherchant ce même défaut ailleurs, le même bug a été trouvé dans
   `.github/workflows/production-image-provenance.yml` (PR #102, déjà
   mergé sur `main`)** : `if: github.ref == 'refs/heads/main'` au niveau
   du job, ligne 35. Non corrigé ici (fichier déjà mergé, hors périmètre
   de ce lot — nécessite son propre lot dédié, signalé séparément).
   Cela justifie directement le point suivant : ne jamais dépendre
   uniquement de la garantie fail-closed d'un workflow tiers déjà
   mergé tant qu'elle n'est pas elle-même prouvée.
3. **Défense en profondeur ajoutée au job `image-provenance`** :
   au-delà de `path`/`status`/`conclusion`/`head_sha`/`run_attempt`
   déjà vérifiés, ce job revérifie désormais indépendamment que le run
   cité est bien un `workflow_dispatch` (`run.event`) déclenché sur
   `main` (`run.head_branch`) — précisément parce que la garantie
   équivalente côté `production-image-provenance.yml` porte le même
   défaut que celui corrigé au point 1 ci-dessus, et ne peut donc pas
   être présumée fiable avant sa propre correction. Nouveau test
   `test_image_provenance_job_independently_verifies_event_and_branch`,
   mutation-testé (retrait des deux contrôles → 2 échecs pour la bonne
   raison ; restauré, suite verte).

```
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/promote.yml'))"
YAML OK

$ python3 -m pytest scripts/tests/test-promote-workflow.py -q
15 passed, 34 subtests passed

$ python3 -m ruff check scripts/tests/test-promote-workflow.py
All checks passed!
```

`CANONICAL_PROMOTION_WORKFLOW_VERIFIED` reste `false` : ce round ferme
deux défauts réels mais ne change rien à la séquence de dépendance déjà
documentée en §6 (attente de PR #109 + rebase avant tout audit final).

## 9. Ce que ce lot ne fait jamais

- Ne modifie pas `packages/contracts`.
- Ne modifie pas `sign_production_readiness_manifest_cli.py` — le
  câblage de pinning (§6) reste un suivi explicite sur PR #100, pas fait
  ici.
- Ne modifie pas `.github/workflows/_produce-h2-evidence.yml` (appelé
  tel quel, jamais réimplémenté — potentiellement corrigé par un autre
  lot en parallèle, sans impact sur celui-ci grâce à l'interface stable
  `workflow_call`).
- Ne provisionne aucun Environment GitHub (§5) — signalé, pas contourné.
- Ne signe rien, ne déploie rien, n'autorise aucun contenu.

## 10. Booléens finaux

```
CANONICAL_PROMOTION_WORKFLOW_BUILT=true
CANONICAL_PROMOTION_WORKFLOW_PATH=.github/workflows/promote.yml
PRIVATE_KEY_NEVER_ENTERS_WORKFLOW=true
COMPOSE_RESOLUTION_DELEGATED_TO_OFFLINE_SIGNER=true
IMAGE_PROVENANCE_INDEPENDENTLY_REVERIFIED=true
H2_EVIDENCE_REUSED_NOT_REIMPLEMENTED=true
PRODUCTION_ENVIRONMENT_PROTECTION_CONFIGURED=false
CANONICAL_PROMOTION_WORKFLOW_VERIFIED=false
PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=false
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
