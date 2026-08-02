# LOT41S CI Provenance Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Garantir que les six checks protégés d'une PR proviennent uniquement de l'événement `pull_request`, sans ambiguïté avec un run `push` ou un autre workflow.

**Architecture:** Le workflow CI canonique accepte exactement `push` sur `main` et `pull_request` vers `main`. Le test fail-safe existant porte le contrat exact des déclencheurs et ajoute un contrôle global qui recense les noms GitHub effectifs des jobs dans tous les workflows ; les documents LOT37R et LOT41S distinguent explicitement le SHA certifié avant fusion du SHA de squash revalidé après fusion.

**Tech Stack:** GitHub Actions YAML, Bash strict, Python 3.11 + PyYAML, Git/GitHub CLI.

---

## Chunk 1: Contrat, correction et preuves LOT41S

### Task 1: Verrouiller la topologie et l'unicité des contextes en TDD

**Files:**
- Modify: `scripts/tests/test-ci-local-failsafe.sh:928-1094`
- Modify: `scripts/tests/test-ci-local-failsafe.sh:1216-1277`
- Test: `scripts/tests/test-ci-local-failsafe.sh`

- [ ] **Step 1: Remplacer le contrôle permissif des déclencheurs par un contrat exact**

Dans le validateur Python embarqué de `validate_yaml_cockpit_job`, normaliser la
clé YAML `on`, puis exiger :

```python
expected_triggers = {
    "push": {"branches": ["main"]},
    "pull_request": {"branches": ["main"]},
}
if triggers != expected_triggers:
    errors.append(
        "on doit contenir exactement push.branches=[main] et "
        "pull_request.branches=[main]"
    )
```

Conserver le commentaire expliquant que `pull_request.branches` filtre la base
de la PR. Supprimer les anciennes attentes `lot-*` et `lot-*/**`.

- [ ] **Step 2: Ajouter un validateur global des noms protégés**

Ajouter une fonction shell `validate_protected_context_provenance` qui reçoit un
répertoire de workflows et exécute Python/PyYAML. Elle parcourt uniquement les
fichiers réguliers `*.yml` et `*.yaml`, extrait chaque job, calcule son nom GitHub
effectif avec repli sur l'identifiant et exige exactement une occurrence de :

```python
PROTECTED_CONTEXTS = {
    "packages/contracts",
    "services/rag-pedago",
    "services/rag-engine",
    "services/cockpit",
    "governance locks guard",
    "repository controls",
}

effective_name = job.get("name", job_id)
```

Le validateur refuse un YAML illisible, une racine ou une section `jobs`
invalide, un contexte absent, dupliqué ou produit par un fichier autre que
`ci.yml`. Ajouter `assert_protected_context_provenance` pour comptabiliser le
résultat dans la suite shell.

- [ ] **Step 3: Ajouter les mutations sensibles**

Remplacer les deux mutations qui retiraient `lot-*` par cinq mutations :

1. réintroduire `lot-*` dans `push.branches` ;
2. retirer `main` de `push.branches` ;
3. retirer `main` de `pull_request.branches` ;
4. ajouter `workflow_dispatch` ;
5. créer dans un répertoire temporaire dédié une copie de `ci.yml` et un second
   workflow dont un job porte `name: "packages/contracts"`.

Chaque mutation doit être refusée par le validateur correspondant. Appeler le
contrôle global sur `.github/workflows/` dans le cas canonique.

- [ ] **Step 4: Exécuter le test RED**

Run:

```bash
YAML_PYTHON_BIN=python NEXUS_CI_LOCAL_RUNNING=1 \
  bash scripts/tests/test-ci-local-failsafe.sh
```

Expected: `FAIL` pour le workflow canonique, car `push.branches` contient encore
les branches de lot ; code de sortie non nul. Les nouvelles mutations doivent
être sensibles et ne pas échouer pour une erreur de syntaxe du test.

### Task 2: Corriger le workflow avec le changement minimal

**Files:**
- Modify: `.github/workflows/ci.yml:3-7`
- Test: `scripts/tests/test-ci-local-failsafe.sh`
- Test: `scripts/tests/test-ci-local-topology.sh`
- Test: `scripts/tests/test-main-protection-policy.py`

- [ ] **Step 1: Restreindre les déclencheurs**

Appliquer exactement :

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

Ne modifier aucun job, nom de contexte ou paramètre de protection de branche.

- [ ] **Step 2: Exécuter le test GREEN et les contrôles connexes**

Run:

```bash
YAML_PYTHON_BIN=python NEXUS_CI_LOCAL_RUNNING=1 \
  bash scripts/tests/test-ci-local-failsafe.sh
bash scripts/tests/test-ci-local-topology.sh
python scripts/tests/test-main-protection-policy.py
```

Expected: toutes les suites sortent avec `0`, aucun échec ; le test fail-safe
compte les nouveaux contrôles et mutations.

- [ ] **Step 3: Vérifier le readback de protection sans mutation distante**

Run:

```bash
python scripts/github/main_protection.py \
  --repository cyranoaladin/RAG --check
```

Expected: `OK: main protection matches policy for cyranoaladin/RAG`.

- [ ] **Step 4: Committer le cycle TDD**

```bash
git add .github/workflows/ci.yml scripts/tests/test-ci-local-failsafe.sh
git commit -m "ci: distingue les checks de pull request"
```

### Task 3: Corriger les instructions historiques et consigner LOT41S

**Files:**
- Modify: `docs/superpowers/plans/2026-07-31-lot-37r-source-truth-reconciliation.md:731`
- Modify: `docs/superpowers/plans/2026-07-31-lot-37r-source-truth-reconciliation.md:834-856`
- Create: `docs/reports/lot_41s_ci_provenance.md`

- [ ] **Step 1: Ajouter un erratum explicite au plan LOT37R**

Préciser près de la preuve PR que l'artefact certifie uniquement le `headSha`
qu'il contient. Remplacer l'instruction qui commettait ensuite une preuve
présentée comme finale par une règle de preuve parent-SHA assumée : les checks du
commit documentaire final restent des preuves GitHub externes, consultées après
push, et ne sont pas revendiquées par l'artefact déjà committé.

Ajouter que depuis LOT41S aucun run `push` de branche de lot ne peut publier les
six contextes protégés ; le run `push` simultané mentionné dans le plan était une
limitation historique.

- [ ] **Step 2: Créer le rapport LOT41S**

Le rapport en français doit contenir :

- baseline `6e4e241d6ca0c5a0151b500a3d9eb18527283235` et branche du lot ;
- reproduction distante sur `8cafdc652060973f5bf738777486e5192afb82e0`,
  avec runs `30734892670` (`push`) et `30734894002` (`pull_request`) ;
- cause racine, décision et exclusions ;
- résultat RED puis GREEN et nombres de tests observés ;
- readback live de protection ;
- rappel que LOT41T traite séparément les preuves de gouvernance ;
- verdict global exact `GO_LIVE: NO_GO`.

Ne pas annoncer de réussite GitHub du head final avant son observation.

- [ ] **Step 3: Vérifier la documentation**

Run:

```bash
git diff --check
if rg -n 'TODO|TBD|/home/|BEGIN .*PRIVATE KEY|gh[pousr]_' \
  docs/reports/lot_41s_ci_provenance.md; then
  exit 1
fi
if git diff --unified=0 main -- \
  docs/superpowers/plans/2026-07-31-lot-37r-source-truth-reconciliation.md \
  | rg '^\+.*(TODO|TBD|/home/|BEGIN .*PRIVATE KEY|gh[pousr]_)'; then
  exit 1
fi
```

Expected: les deux contrôles sortent avec `0`. Le second contrôle inspecte
uniquement les lignes ajoutées, car le plan LOT37R historique contient déjà les
littéraux `TODO` et `TBD` dans une consigne de validation.

- [ ] **Step 4: Committer la documentation**

```bash
git add \
  docs/superpowers/plans/2026-07-31-lot-37r-source-truth-reconciliation.md \
  docs/reports/lot_41s_ci_provenance.md
git commit -m "docs: consigne la provenance CI LOT41S"
```

### Task 4: Vérifier, publier et fusionner LOT41S

**Files:**
- Verify: all files in `origin/main...HEAD`
- External state: branch `lot-41s-ci-provenance`, LOT41S PR, GitHub checks, PR #79 review threads

- [ ] **Step 1: Exécuter la vérification locale complète**

Run:

```bash
bash scripts/ci-local.sh
git diff origin/main...HEAD --check
gitleaks git --log-opts='origin/main..HEAD' --redact --no-banner --exit-code 1
git status --short --branch
```

Expected: CI locale `13 passed, 0 failed`, diff propre, aucun secret et worktree
propre.

- [ ] **Step 2: Faire relire le diff complet**

Invoquer `superpowers:requesting-code-review` sur `origin/main...HEAD`. Corriger
chaque finding P0/P1/P2 par un nouveau cycle TDD et relancer les contrôles
affectés ainsi que la CI locale complète.

- [ ] **Step 3: Pousser et ouvrir la PR**

```bash
git push -u origin lot-41s-ci-provenance
PR_URL="$(gh pr create \
  --base main \
  --head lot-41s-ci-provenance \
  --title "CI — désambiguïser la provenance des checks LOT41S" \
  --body $'## Objet\n\nGarantit que les checks pré-fusion proviennent uniquement de pull_request et corrige les instructions de preuve LOT37R.\n\n## Validation\n\nVoir docs/reports/lot_41s_ci_provenance.md.\n\nGO_LIVE: NO_GO')"
gh pr view "$PR_URL" --json number,url,state,isDraft,headRefOid,baseRefName
```

Expected: PR non brouillon vers `main`, tête égale au SHA local, avec le rapport
et le verdict `GO_LIVE: NO_GO`.

- [ ] **Step 4: Vérifier la provenance distante au head exact**

Attendre les checks, puis exécuter :

```bash
HEAD_SHA="$(git rev-parse HEAD)"
PR_RUN_IDS="$(gh run list \
  --commit "$HEAD_SHA" \
  --workflow ci.yml \
  --event pull_request \
  --limit 20 \
  --json databaseId,headSha,status,conclusion \
  --jq ".[] | select(.headSha == \"$HEAD_SHA\") | .databaseId")"
test -n "$PR_RUN_IDS"
test "$(grep -c . <<<"$PR_RUN_IDS")" -eq 1
PR_RUN_ID="$PR_RUN_IDS"
test "$(gh run list \
  --commit "$HEAD_SHA" \
  --workflow ci.yml \
  --event push \
  --limit 20 \
  --json databaseId \
  --jq 'length')" -eq 0
RUN_JSON="$(gh run view "$PR_RUN_ID" \
  --json event,headSha,conclusion,url,jobs)"
RUN_JSON="$RUN_JSON" HEAD_SHA="$HEAD_SHA" python - <<'PY'
import json
import os
from collections import Counter

required = {
    "packages/contracts",
    "services/rag-pedago",
    "services/rag-engine",
    "services/cockpit",
    "governance locks guard",
    "repository controls",
}
run = json.loads(os.environ["RUN_JSON"])
if run["event"] != "pull_request":
    raise SystemExit(f"wrong event: {run['event']}")
if run["headSha"] != os.environ["HEAD_SHA"]:
    raise SystemExit(f"wrong head: {run['headSha']}")
if run["conclusion"] != "success":
    raise SystemExit(f"wrong conclusion: {run['conclusion']}")
selected = [job for job in run["jobs"] if job["name"] in required]
counts = Counter(job["name"] for job in selected)
if counts != Counter({name: 1 for name in required}):
    raise SystemExit(f"wrong protected contexts: {counts}")
if any(job["conclusion"] != "success" for job in selected):
    raise SystemExit(f"failed protected context: {selected}")
PY
```

Expected: un seul run CI réussi d'événement `pull_request`, aucun run CI
`push` pour le head de branche, et chacun des six contextes exactement une fois
avec `success`.

- [ ] **Step 5: Attendre et traiter toutes les revues du head courant**

Run:

```bash
gh pr checks "$PR_URL" --watch --fail-fast
gh pr comment "$PR_URL" --body '@codex review'
```

Après la fin de Codex, charger l'état thread-aware :

```bash
HEAD_SHA="$(git rev-parse HEAD)"
PR_NUMBER="$(gh pr view "$PR_URL" --json number --jq .number)"
COMMENTS_JSON="$(gh api graphql \
  -F owner=cyranoaladin \
  -F repo=RAG \
  -F number="$PR_NUMBER" \
  -f query='query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){comments(last:100){nodes{author{login} body}} reviewThreads(first:100){nodes{isResolved}}}}}')"
COMMENTS_JSON="$COMMENTS_JSON" HEAD_PREFIX="${HEAD_SHA:0:10}" python - <<'PY'
import json
import os

payload = json.loads(os.environ["COMMENTS_JSON"])
pr = payload["data"]["repository"]["pullRequest"]
unresolved = [
    thread
    for thread in pr["reviewThreads"]["nodes"]
    if not thread["isResolved"]
]
if unresolved:
    raise SystemExit(f"unresolved review threads: {unresolved}")
codex_ok = any(
    (comment.get("author") or {}).get("login")
    in {"chatgpt-codex-connector", "chatgpt-codex-connector[bot]"}
    and os.environ["HEAD_PREFIX"] in comment.get("body", "")
    and "Didn't find any major issues" in comment.get("body", "")
    for comment in pr["comments"]["nodes"]
)
if not codex_ok:
    raise SystemExit("missing successful Codex review for exact head")
PY
```

Expected: tous les checks configurés, dont Cubic et GitGuardian, sont terminés
avec succès ; aucun fil n'est ouvert ; Codex a relu le head exact sans finding
majeur. Si une revue entraîne un changement, recommencer le cycle TDD, la CI
locale complète, le push, les checks, `@codex review` et toutes les preuves sur
le nouveau `HEAD_SHA` avant de poursuivre.

- [ ] **Step 6: Fusionner sans bypass**

Run:

```bash
HEAD_SHA="$(git rev-parse HEAD)"
test "$(gh pr view "$PR_URL" --json headRefOid --jq .headRefOid)" = "$HEAD_SHA"
gh pr merge "$PR_URL" \
  --squash \
  --match-head-commit "$HEAD_SHA" \
  --subject "ci: désambiguïse la provenance des checks LOT41S"
test "$(gh pr view "$PR_URL" --json state --jq .state)" = "MERGED"
git push origin --delete lot-41s-ci-provenance
```

Expected: fusion par le chemin protégé, sans `--admin`. La branche distante est
supprimée seulement après le readback `MERGED`. La branche locale reste attachée
au worktree LOT41S jusqu'au nettoyage séparé de fin de lot ; la commande de
fusion ne tente donc jamais de checkout implicite de `main`, déjà utilisée dans
le worktree principal.

- [ ] **Step 7: Revalider le run push du SHA de squash**

Mettre le worktree `main` à jour et identifier le run exact :

```bash
MAIN_WORKTREE="$(git worktree list --porcelain | awk '
  /^worktree / {path=substr($0, 10)}
  /^branch refs\/heads\/main$/ {print path; exit}
')"
test -n "$MAIN_WORKTREE"
git -C "$MAIN_WORKTREE" pull --ff-only origin main
MERGE_SHA="$(git -C "$MAIN_WORKTREE" rev-parse HEAD)"
test "$MERGE_SHA" = "$(git ls-remote origin refs/heads/main | awk '{print $1}')"
MAIN_RUN_IDS=""
for _ in {1..60}; do
  MAIN_RUN_IDS="$(gh run list \
    --commit "$MERGE_SHA" \
    --workflow ci.yml \
    --event push \
    --limit 20 \
    --json databaseId,headSha \
    --jq ".[] | select(.headSha == \"$MERGE_SHA\") | .databaseId")"
  [ -n "$MAIN_RUN_IDS" ] && break
  sleep 10
done
test -n "$MAIN_RUN_IDS"
test "$(grep -c . <<<"$MAIN_RUN_IDS")" -eq 1
MAIN_RUN_ID="$MAIN_RUN_IDS"
gh run watch "$MAIN_RUN_ID" --exit-status
MAIN_RUN_JSON="$(gh run view "$MAIN_RUN_ID" \
  --json event,headSha,conclusion,url,jobs)"
MAIN_RUN_JSON="$MAIN_RUN_JSON" MERGE_SHA="$MERGE_SHA" python - <<'PY'
import json
import os
from collections import Counter

required = {
    "packages/contracts",
    "services/rag-pedago",
    "services/rag-engine",
    "services/cockpit",
    "governance locks guard",
    "repository controls",
}
run = json.loads(os.environ["MAIN_RUN_JSON"])
if (run["event"], run["headSha"], run["conclusion"]) != (
    "push",
    os.environ["MERGE_SHA"],
    "success",
):
    raise SystemExit(f"wrong main run: {run}")
selected = [job for job in run["jobs"] if job["name"] in required]
counts = Counter(job["name"] for job in selected)
if counts != Counter({name: 1 for name in required}):
    raise SystemExit(f"wrong protected contexts: {counts}")
if any(job["conclusion"] != "success" for job in selected):
    raise SystemExit(f"failed protected context: {selected}")
PY
test -z "$(git ls-remote --heads origin refs/heads/lot-41s-ci-provenance)"
git -C "$MAIN_WORKTREE" status --short --branch
```

Expected: un run `push` unique et réussi sur le SHA de squash, les six contextes
une fois chacun avec `success`, `origin/main` comme unique branche distante et
le worktree `main` propre et synchronisé.

- [ ] **Step 8: Répondre et résoudre les deux fils de la PR #79**

Après la revalidation de `main`, répondre dans les fils exacts puis les résoudre :

```bash
PR_NUMBER="$(gh pr view "$PR_URL" --json number --jq .number)"
gh api --method POST \
  repos/cyranoaladin/RAG/pulls/79/comments/3692602704/replies \
  -f body="Corrigé par la PR #$PR_NUMBER fusionnée sur main. Les branches de lot ne déclenchent plus de run push ; le head pré-fusion ne publie donc les six contextes protégés que via pull_request. Le test de dépôt verrouille aussi leur unicité entre workflows."
gh api --method POST \
  repos/cyranoaladin/RAG/pulls/79/comments/3692602711/replies \
  -f body="Clarifié par la PR #$PR_NUMBER fusionnée sur main. L'artefact versionné certifie exclusivement le headSha qu'il contient ; les checks du commit documentaire ultérieur restent une preuve GitHub externe et ne sont plus revendiqués par cet artefact parent-SHA."
for thread_id in \
  PRRT_kwDOTEIbbs6VgR0l \
  PRRT_kwDOTEIbbs6VgR0q; do
  RESOLVED="$(gh api graphql \
    -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' \
    -f id="$thread_id" \
    --jq '.data.resolveReviewThread.thread.isResolved')"
  test "$RESOLVED" = "true"
done
THREADS_JSON="$(gh api graphql \
  -F owner=cyranoaladin \
  -F repo=RAG \
  -F number=79 \
  -f query='query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){reviewThreads(first:100){nodes{isResolved}}}}}')"
jq -e \
  '.data.repository.pullRequest.reviewThreads.nodes | all(.isResolved)' \
  <<<"$THREADS_JSON"
```

Expected: deux réponses inline créées et les deux mutations retournent `true`.
Le readback GraphQL final retourne également `true`, donc zéro fil ouvert.
