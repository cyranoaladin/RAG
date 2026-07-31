# LOT37R — Réconciliation de la source de vérité Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruire le plus petit LOT37R sûr depuis `main`, faire de `scripts/ci-local.sh` l’unique porte locale complète, retirer les artefacts suivis à la racine et laisser `main` protégée et auditable sans fusionner les PR 56 ou 77 surdimensionnées.

**Architecture:** L’orchestration CI reste unidirectionnelle : les audits spécialisés exécutent leurs contrôles ciblés, tandis que seuls les humains ou les workflows appellent la CI locale canonique. Un garde unique des fichiers suivis assure l’hygiène du dépôt en local et dans GitHub Actions. La protection GitHub est décrite par une politique versionnée, appliquée après l’apparition et la réussite des six checks exacts sur la PR de remplacement mais avant sa fusion, puis vérifiée par lecture de l’API. LOT37R ne modifie ni code service, ni dépendance, ni retrieval, ni verrou de gouvernance, ni corpus, ni runtime.

**Tech Stack:** Bash 4+, Git, worktrees Git, GitHub CLI (`gh`), API REST GitHub `2026-03-10`, GitHub Actions et bibliothèque standard Python 3.11 pour la validation JSON déterministe.

---

## Préconditions et exclusions

- La conception approuvée est `docs/superpowers/specs/2026-07-31-pilot-go-live-finalization-design.md`.
- L’exécution ne commence qu’après fusion de cette conception dans `origin/main` par PR.
- La branche d’implémentation est exactement `lot-37r-source-truth-reconciliation` et part de la `origin/main` alors courante.
- Les PR 56 et 77 servent uniquement de sources de preuve. Aucun de leurs commits n’est cherry-pické et aucune n’est fusionnée.
- Sont explicitement exclus de la PR 77 : le `Makefile` racine, `scripts/full-regression.sh`, l’E2E de production, la configuration pytest racine, les fixtures/marqueurs bloquant le réseau, les mises à niveau de dépendances et tout changement source sous `services/` ou `packages/`.
- Aucun stash n’est appliqué ni supprimé. Les stashes sont inventoriés par commit immuable uniquement ; leur contenu est reporté au lot propriétaire.
- Aucun verrou de gouvernance ne change de valeur dans ce lot.
- Aucun push direct n’est effectué vers `main`.

# Chunk 1 — CI locale canonique et hygiène du dépôt

## Tâche 1 : créer la branche de livraison LOT37R isolée

**Fichiers :**
- Vérifier : `docs/superpowers/specs/2026-07-31-pilot-go-live-finalization-design.md`
- Vérifier : `.github/workflows/ci.yml`
- Vérifier : `scripts/ci-local.sh`
- Vérifier : `scripts/audit/rag-pr-audit.sh`

- [ ] Récupérer l’état distant sans modifier de branche :

  ```bash
  git fetch --prune origin
  git status --short --branch
  git rev-parse origin/main
  ```

  Attendu : le worktree courant est propre ; `origin/main` se résout en un SHA.

- [ ] Prouver la présence de la conception approuvée sur `main` distante :

  ```bash
  DESIGN_SHA="$(git log -n 1 --format=%H origin/main -- docs/superpowers/specs/2026-07-31-pilot-go-live-finalization-design.md)"
  test -n "$DESIGN_SHA"
  git show "origin/main:docs/superpowers/specs/2026-07-31-pilot-go-live-finalization-design.md" \
    | grep -F "Statut : validé par le commanditaire"
  ```

  Attendu : les deux commandes sortent avec `0` et affichent la ligne de statut. Sinon, s’arrêter : la PR de conception doit d’abord être fusionnée.

- [ ] Confirmer que les deux PR supersédées ne sont pas fusionnées et relever leurs têtes immuables :

  ```bash
  gh pr view 56 --json number,state,isDraft,headRefOid,mergeStateStatus,url
  gh pr view 77 --json number,state,isDraft,headRefOid,mergeStateStatus,url
  ```

  Attendu : les deux PR indiquent `state: OPEN` et `isDraft: true`. Tout état fusionné arrête ce plan pour réaudit.

- [ ] Créer un worktree voisin depuis `main` distante :

  ```bash
  git worktree add ../RAG-lot37r -b lot-37r-source-truth-reconciliation origin/main
  cd ../RAG-lot37r
  git status --short --branch
  ```

  Attendu : branche propre `lot-37r-source-truth-reconciliation` basée sur le SHA `origin/main` sélectionné.

- [ ] Relever la baseline immuable sans écrire de preuve générée dans Git :

  ```bash
  git rev-parse HEAD
  git ls-files ':(top,glob)MANIFEST_LOT*.md' ':(top,glob)*.tar.gz'
  gh pr diff 56 --name-only
  gh pr diff 77 --name-only
  git stash list --format='%gd%x09%H%x09%gs'
  ```

  Attendu : les deux manifests suivis à la racine sont visibles ; les listes de fichiers des PR et les commits des stashes sont disponibles pour le rapport LOT37R. Ne pas afficher le contenu des stashes.

## Tâche 2 : rompre le graphe d’appel CI récursif

**Fichiers :**
- Créer : `scripts/tests/test-ci-local-topology.sh`
- Modifier : `scripts/ci-local.sh`
- Modifier : `scripts/audit/rag-pr-audit.sh`
- Modifier : `scripts/tests/test-ci-local-failsafe.sh`

- [ ] Ajouter `scripts/tests/test-ci-local-topology.sh` avec ces assertions à responsabilité unique :

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
  TMP_ROOT="$(mktemp -d)"
  trap 'rm -rf "$TMP_ROOT"' EXIT

  mkdir -p "$TMP_ROOT/repo/scripts"
  awk '
      /^SCRIPT_DIR=/ && !inserted {
          print "echo \"FAIL: re-entry guard was bypassed\" >&2"
          print "exit 86"
          inserted = 1
      }
      { print }
      END { if (!inserted) exit 1 }
  ' "$REPO_ROOT/scripts/ci-local.sh" > "$TMP_ROOT/repo/scripts/ci-local.sh"

  set +e
  OUTPUT="$({
      NEXUS_CI_LOCAL_RUNNING=1 \
          bash "$TMP_ROOT/repo/scripts/ci-local.sh"
  } 2>&1)"
  STATUS=$?
  set -e

  if [ "$STATUS" -ne 2 ]; then
      echo "FAIL: expected re-entry exit 2, got $STATUS" >&2
      echo "$OUTPUT" >&2
      exit 1
  fi
  grep -Fq "ERROR: ci-local.sh refuse une réentrance" <<<"$OUTPUT"
  if grep -Fq "FAIL: re-entry guard was bypassed" <<<"$OUTPUT"; then
      echo "FAIL: re-entry was rejected after the safe stop point" >&2
      exit 1
  fi

  if grep -Eq '(^|[[:space:]/])ci-local\.sh([[:space:]]|$)' \
      "$REPO_ROOT/scripts/audit/rag-pr-audit.sh"; then
      echo "FAIL: rag-pr-audit.sh invokes ci-local.sh" >&2
      exit 1
  fi
  if grep -Eq '(^|[[:space:]/])rag-pr-audit\.sh([[:space:]]|$)' \
      "$REPO_ROOT/scripts/ci-local.sh"; then
      echo "FAIL: ci-local.sh invokes rag-pr-audit.sh" >&2
      exit 1
  fi

  echo "PASS: CI topology is acyclic and re-entry fails closed"
  ```

- [ ] Rendre le nouveau test exécutable et le lancer avant l’implémentation :

  ```bash
  chmod +x scripts/tests/test-ci-local-topology.sh
  bash scripts/tests/test-ci-local-topology.sh
  ```

  Attendu : `FAIL: expected re-entry exit 2` ou `FAIL: rag-pr-audit.sh invokes ci-local.sh` ; la sortie est non nulle.

- [ ] Ajouter ce garde immédiatement après `set -uo pipefail` dans `scripts/ci-local.sh`, avant toute résolution d’outil ou suppression d’environnement virtuel :

  ```bash
  if [ "${NEXUS_CI_LOCAL_RUNNING:-0}" = "1" ]; then
      echo "ERROR: ci-local.sh refuse une réentrance" >&2
      exit 2
  fi
  export NEXUS_CI_LOCAL_RUNNING=1
  ```

- [ ] Retirer uniquement le bloc suivant de `scripts/audit/rag-pr-audit.sh` :

  ```bash
  echo ""
  echo "--- ci-local ---"
  bash scripts/ci-local.sh
  ```

  Conserver sans changement tous les contrôles ciblés qui le précèdent et le suivent.

- [ ] Dans `scripts/tests/test-ci-local-failsafe.sh`, neutraliser le marqueur uniquement pour les deux exécutions filles intentionnelles d’une copie de `ci-local.sh` :

  ```bash
  SOURCE_FAILURE_OUTPUT=$(
      env NEXUS_CI_LOCAL_RUNNING=0 \
          bash "$SOURCE_FAILURE_ROOT/scripts/ci-local.sh" 2>&1
  )
  ```

  and:

  ```bash
  NODE_FAILURE_OUTPUT=$(
      PATH="$NODE_FAILURE_ROOT/bin:/usr/bin:/bin" \
      NEXUS_CI_LOCAL_RUNNING=0 \
          bash "$NODE_FAILURE_ROOT/scripts/ci-local.sh" 2>&1
  )
  ```

  Ne jamais neutraliser ce marqueur dans le code de production. Ces deux sous-processus testent volontairement le démarrage et doivent s’exclure explicitement.

- [ ] Exécuter la vérification ciblée rouge-vers-vert :

  ```bash
  bash scripts/tests/test-ci-local-topology.sh
  bash scripts/tests/test-ci-local-failsafe.sh
  NEXUS_CI_LOCAL_RUNNING=1 bash scripts/tests/test-ci-local-failsafe.sh
  bash -n scripts/ci-local.sh scripts/audit/rag-pr-audit.sh scripts/tests/test-ci-local-topology.sh
  git diff --check
  ```

  Attendu : la topologie affiche `PASS` ; les deux appels failsafe produisent le même résumé entièrement vert ; les contrôles de syntaxe et de diff sortent avec `0`.

- [ ] Committer séparément la correction de topologie :

  ```bash
  git add \
    scripts/ci-local.sh \
    scripts/audit/rag-pr-audit.sh \
    scripts/tests/test-ci-local-topology.sh \
    scripts/tests/test-ci-local-failsafe.sh
  git commit -m "ci: bloque la réentrance locale"
  ```

  Attendu : un commit scopé contenant exactement les quatre fichiers listés.

## Tâche 3 : faire de l’hygiène des fichiers racine suivis une porte partagée

**Fichiers :**
- Créer : `scripts/check-repository-hygiene.sh`
- Créer : `scripts/tests/test-repository-hygiene.sh`
- Modifier : `scripts/ci-local.sh`
- Modifier : `.github/workflows/ci.yml`
- Déplacer : `MANIFEST_LOT28.md` → `docs/reports/MANIFEST_LOT28.md`
- Déplacer : `MANIFEST_LOT29.md` → `docs/reports/MANIFEST_LOT29.md`

- [ ] Ajouter `scripts/tests/test-repository-hygiene.sh` avant que le garde n’existe :

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
  GUARD="$REPO_ROOT/scripts/check-repository-hygiene.sh"
  TMP_ROOT="$(mktemp -d)"
  trap 'rm -rf "$TMP_ROOT"' EXIT

  BASE_REPO="$TMP_ROOT/base"
  TEST_REPO="$TMP_ROOT/worktree"
  mkdir -p "$BASE_REPO/scripts"
  cp "$GUARD" "$BASE_REPO/scripts/check-repository-hygiene.sh"
  git -C "$BASE_REPO" init -q
  git -C "$BASE_REPO" config user.name "LOT37R test"
  git -C "$BASE_REPO" config user.email "lot37r@example.invalid"
  git -C "$BASE_REPO" add scripts/check-repository-hygiene.sh
  git -C "$BASE_REPO" commit -qm "test: initialise hygiene fixture"
  git -C "$BASE_REPO" worktree add -qb hygiene-worktree "$TEST_REPO"
  mkdir -p "$TEST_REPO/docs/reports"
  test -f "$TEST_REPO/.git"

  bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO"

  echo manifest > "$TEST_REPO/MANIFEST_LOT99.md"
  git -C "$TEST_REPO" add MANIFEST_LOT99.md
  set +e
  MANIFEST_OUTPUT="$(bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO" 2>&1)"
  MANIFEST_STATUS=$?
  set -e
  test "$MANIFEST_STATUS" -ne 0
  grep -Fq "MANIFEST_LOT99.md" <<<"$MANIFEST_OUTPUT"

  git -C "$TEST_REPO" mv MANIFEST_LOT99.md docs/reports/MANIFEST_LOT99.md
  bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO"

  echo archive > "$TEST_REPO/runtime.tar.gz"
  git -C "$TEST_REPO" add runtime.tar.gz
  set +e
  ARCHIVE_OUTPUT="$(bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO" 2>&1)"
  ARCHIVE_STATUS=$?
  set -e
  test "$ARCHIVE_STATUS" -ne 0
  grep -Fq "runtime.tar.gz" <<<"$ARCHIVE_OUTPUT"

  git -C "$TEST_REPO" rm -q --cached runtime.tar.gz
  bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO"

  echo "PASS: repository hygiene inspects tracked root files only"
  ```

- [ ] Rendre le test exécutable et prouver qu’il est rouge car le garde est absent :

  ```bash
  chmod +x scripts/tests/test-repository-hygiene.sh
  bash scripts/tests/test-repository-hygiene.sh
  ```

  Attendu : `cp` signale l’absence de `scripts/check-repository-hygiene.sh` ; la sortie est non nulle.

- [ ] Ajouter le garde à responsabilité unique `scripts/check-repository-hygiene.sh` :

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  REPO_ROOT="${1:-$(git rev-parse --show-toplevel)}"
  if ! git -C "$REPO_ROOT" rev-parse --is-inside-work-tree \
      >/dev/null 2>&1; then
      echo "ERROR: repository root is not a Git worktree: $REPO_ROOT" >&2
      exit 2
  fi

  TRACKED_LIST="$(mktemp)"
  trap 'rm -f "$TRACKED_LIST"' EXIT
  if ! git -C "$REPO_ROOT" ls-files -z -- \
          ':(top,glob)MANIFEST_LOT*.md' \
          ':(top,glob)*.tar' \
          ':(top,glob)*.tar.gz' \
          ':(top,glob)*.tgz' \
          ':(top,glob)*.zip' > "$TRACKED_LIST"; then
      echo "ERROR: unable to inspect tracked repository files" >&2
      exit 2
  fi
  mapfile -d '' -t OFFENDERS < "$TRACKED_LIST"

  if [ "${#OFFENDERS[@]}" -ne 0 ]; then
      echo "ERROR: tracked delivery artifacts are forbidden at repository root:" >&2
      printf '  %s\n' "${OFFENDERS[@]}" >&2
      exit 1
  fi

  echo "PASS: tracked repository root is clean"
  ```

- [ ] Rendre le garde exécutable, lancer le test comportemental isolé, puis prouver que le dépôt courant est rouge pour les manifests connus :

  ```bash
  chmod +x scripts/check-repository-hygiene.sh
  bash scripts/tests/test-repository-hygiene.sh
  set +e
  ROOT_OUTPUT="$(bash scripts/check-repository-hygiene.sh 2>&1)"
  ROOT_STATUS=$?
  set -e
  printf '%s\n' "$ROOT_OUTPUT"
  test "$ROOT_STATUS" -eq 1
  grep -Fq "MANIFEST_LOT28.md" <<<"$ROOT_OUTPUT"
  grep -Fq "MANIFEST_LOT29.md" <<<"$ROOT_OUTPUT"
  ```

  Attendu : le test comportemental passe ; le garde sur la vraie racine échoue avec les deux chemins exacts.

- [ ] Préserver l’historique lors du déplacement des deux manifests :

  ```bash
  git mv MANIFEST_LOT28.md docs/reports/MANIFEST_LOT28.md
  git mv MANIFEST_LOT29.md docs/reports/MANIFEST_LOT29.md
  git status --short -- \
    MANIFEST_LOT28.md MANIFEST_LOT29.md \
    docs/reports/MANIFEST_LOT28.md docs/reports/MANIFEST_LOT29.md
  bash scripts/check-repository-hygiene.sh
  ```

  Attendu : `git status --short` présente deux entrées `R` de la racine vers `docs/reports/` ; le garde affiche `PASS`.

- [ ] Ajouter le garde et les deux régressions comportementales à `scripts/ci-local.sh` immédiatement avant `governance-locks` :

  ```bash
  # --- repository hygiene ---
  run_target "repository-hygiene" bash scripts/check-repository-hygiene.sh

  # --- repository hygiene tests ---
  run_target "repository-hygiene-tests" bash scripts/tests/test-repository-hygiene.sh

  # --- CI topology tests ---
  run_target "ci-topology-tests" bash scripts/tests/test-ci-local-topology.sh
  ```

- [ ] Ajouter ce job indépendant à `.github/workflows/ci.yml` avant `governance-locks` :

  ```yaml
  repository-controls:
    name: "repository controls"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bash scripts/check-repository-hygiene.sh
      - run: bash scripts/tests/test-repository-hygiene.sh
      - run: bash scripts/tests/test-ci-local-topology.sh
      - run: NEXUS_CI_LOCAL_RUNNING=1 bash scripts/tests/test-ci-local-failsafe.sh
  ```

  Le nom du job est unique parmi les workflows et devient le check obligatoire du chunk 2.

- [ ] Exécuter la suite ciblée :

  ```bash
  bash scripts/tests/test-repository-hygiene.sh
  bash scripts/check-repository-hygiene.sh
  bash scripts/tests/test-ci-local-topology.sh
  bash scripts/tests/test-ci-local-failsafe.sh
  NEXUS_CI_LOCAL_RUNNING=1 bash scripts/tests/test-ci-local-failsafe.sh
  bash scripts/check-governance-locks.sh
  bash scripts/tests/test-governance-locks.sh
  bash -n scripts/check-repository-hygiene.sh scripts/tests/test-repository-hygiene.sh scripts/ci-local.sh
  git diff --check
  ```

  Attendu : chaque commande sort avec `0` ; le test failsafe existant conserve son résumé entièrement vert ; les verrous de gouvernance restent inchangés.

- [ ] Committer l’hygiène du dépôt séparément :

  ```bash
  git add \
    .github/workflows/ci.yml \
    scripts/ci-local.sh \
    scripts/check-repository-hygiene.sh \
    scripts/tests/test-repository-hygiene.sh \
    docs/reports/MANIFEST_LOT28.md \
    docs/reports/MANIFEST_LOT29.md
  git commit -m "ci: impose l’hygiène du dépôt"
  ```

  Attendu : un commit scopé ; `git show --stat --oneline HEAD` présente uniquement le garde, son test, les deux appelants et les deux renommages.

# Chunk 2 — `main` protégée, preuves et clôture des PR supersédées

## Tâche 4 : versionner et tester la politique exacte de protection de `main`

**Fichiers :**
- Créer : `scripts/github/main-protection-policy.json`
- Créer : `scripts/github/main_protection.py`
- Créer : `scripts/tests/test-main-protection-policy.py`
- Modifier : `scripts/ci-local.sh`
- Modifier : `.github/workflows/ci.yml`

- [ ] Ajouter `scripts/tests/test-main-protection-policy.py` avec des cas `unittest` qui importent `scripts/github/main_protection.py` par chemin et vérifient tous les points suivants :

  1. `load_policy()` retourne exactement les six contextes ci-dessous, sans doublon.
  2. `strict`, `enforce_admins`, `required_linear_history` et `required_conversation_resolution` valent `true`.
  3. `allow_force_pushes`, `allow_deletions` et `lock_branch` valent `false`.
  4. `required_pull_request_reviews.required_approving_review_count` vaut `0`, `require_code_owner_reviews` vaut `false` et `require_last_push_approval` vaut `false`.
  5. `normalize_remote()` convertit les enveloppes GitHub `{ "enabled": boolean }` vers la forme exacte de la politique et trie les contextes.
  6. `verify_policy()` réussit pour des JSON sémantiquement égaux mais réordonnés, et lève `PolicyDrift` si un contexte manque ou si le force-push est actif.
  7. `apply_policy()` n’appelle aucun runner mutant quand le SHA `main` distant diffère de `--expected-main-sha`.
  8. `apply_policy()` appelle un seul `PUT` après correspondance du SHA et du jeton de confirmation, puis vérifie par relecture.
  9. Chaque appel `gh api` porte l’en-tête `X-GitHub-Api-Version: 2026-03-10`.

  Les six contextes obligatoires exacts sont :

  ```python
  REQUIRED_CONTEXTS = {
      "packages/contracts",
      "services/rag-pedago",
      "services/rag-engine",
      "services/cockpit",
      "governance locks guard",
      "repository controls",
  }
  ```

- [ ] Lancer le nouveau test avant de créer l’implémentation de la politique :

  ```bash
  python3.11 scripts/tests/test-main-protection-policy.py
  ```

  Attendu : l’import échoue car `scripts/github/main_protection.py` n’existe pas ; la sortie est non nulle.

- [ ] Ajouter `scripts/github/main-protection-policy.json` avec cette charge utile exacte :

  ```json
  {
    "required_status_checks": {
      "strict": true,
      "contexts": [
        "packages/contracts",
        "services/rag-pedago",
        "services/rag-engine",
        "services/cockpit",
        "governance locks guard",
        "repository controls"
      ]
    },
    "enforce_admins": true,
    "required_pull_request_reviews": {
      "dismiss_stale_reviews": false,
      "require_code_owner_reviews": false,
      "required_approving_review_count": 0,
      "require_last_push_approval": false
    },
    "restrictions": null,
    "required_linear_history": true,
    "allow_force_pushes": false,
    "allow_deletions": false,
    "block_creations": false,
    "required_conversation_resolution": true,
    "lock_branch": false,
    "allow_fork_syncing": false
  }
  ```

  L’absence d’approbation générale obligatoire est volontaire : le dépôt ne possède actuellement qu’un collaborateur et une revue obligatoire bloquerait toutes les PR. Les PR restent obligatoires, les administrateurs ne contournent pas les checks et les PR d’autorisation humaine explicites du go-live restent des portes de décision séparées.

- [ ] Implémenter `scripts/github/main_protection.py` avec les responsabilités publiques exactes suivantes :

  ```python
  GITHUB_API_VERSION = "2026-03-10"


  class PolicyDrift(RuntimeError):
      """La politique active diffère de la politique versionnée."""


  def load_policy(path: Path) -> dict[str, object]:
      """Charge le JSON et refuse clés inconnues ou contextes dupliqués."""


  def normalize_policy(policy: dict[str, object]) -> dict[str, object]:
      """Retourne les champs gouvernés et trie les contextes obligatoires."""


  def normalize_remote(remote: dict[str, object]) -> dict[str, object]:
      """Convertit la réponse GitHub vers la forme normalisée."""


  def verify_policy(policy: dict[str, object], remote: dict[str, object]) -> None:
      """Lève PolicyDrift avec un diff JSON déterministe en cas d’écart."""


  def apply_policy(
      repository: str,
      expected_main_sha: str,
      confirmation: str,
      policy_path: Path,
      runner: Callable[..., dict[str, object] | str],
  ) -> None:
      """Vérifie SHA et confirmation, effectue un PUT, puis relit."""
  ```

  La CLI ne doit accepter que ces modes :

  ```text
  --repository OWNER/REPO --check
  --repository OWNER/REPO --apply --expected-main-sha SHA
  ```

  `--check` exécute uniquement `GET repos/{repository}/branches/main/protection`. `--apply` lit d’abord `GET repos/{repository}/git/ref/heads/main`, exige `NEXUS_CONFIRM_MAIN_PROTECTION={repository}@{expected_main_sha}`, envoie `scripts/github/main-protection-policy.json` via `gh api --method PUT`, puis relit et vérifie la politique active. Chaque appel ajoute `-H "X-GitHub-Api-Version: 2026-03-10"`, version documentée et testée. Un `404`, une réponse mal formée, un SHA différent, une confirmation absente ou une dérive sémantique produit une sortie non nulle sans message de succès. Ne jamais accepter le dépôt ou la branche depuis le JSON de politique.

- [ ] Exécuter les contrôles unitaires, syntaxiques et live en lecture seule :

  ```bash
  python3.11 scripts/tests/test-main-protection-policy.py
  python3.11 -m py_compile scripts/github/main_protection.py scripts/tests/test-main-protection-policy.py
  set +e
  PROTECTION_OUTPUT="$({
    python3.11 scripts/github/main_protection.py \
      --repository cyranoaladin/RAG --check
  } 2>&1)"
  PROTECTION_STATUS=$?
  set -e
  printf '%s\n' "$PROTECTION_OUTPUT"
  test "$PROTECTION_STATUS" -ne 0
  grep -Fq "main is not protected" <<<"$PROTECTION_OUTPUT"
  ```

  Attendu : les tests unitaires passent ; le contrôle live reste en lecture seule et confirme l’absence initiale auditée de protection.

- [ ] Raccorder le test de politique à la porte locale canonique immédiatement après `ci-topology-tests` :

  ```bash
  # --- main protection policy tests ---
  run_target "main-protection-policy-tests" \
    "$PYTHON_BIN" scripts/tests/test-main-protection-policy.py
  ```

- [ ] Ajouter la même régression persistante au job GitHub `repository-controls` existant :

  ```yaml
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python scripts/tests/test-main-protection-policy.py
  ```

- [ ] Prouver que les deux appelants contiennent la commande exacte et relancer le test de politique :

  ```bash
  rg -n 'test-main-protection-policy\.py' scripts/ci-local.sh .github/workflows/ci.yml
  python3.11 scripts/tests/test-main-protection-policy.py
  ```

  Attendu : un appel dans chaque appelant et un résultat unitaire vert.

- [ ] Committer le code de politique séparément :

  ```bash
  git add \
    .github/workflows/ci.yml \
    scripts/ci-local.sh \
    scripts/github/main-protection-policy.json \
    scripts/github/main_protection.py \
    scripts/tests/test-main-protection-policy.py
  git commit -m "ci: versionne la protection de main"
  ```

  Attendu : un commit contenant la politique, son gestionnaire, ses tests et les deux appelants canoniques.

## Tâche 5 : produire les preuves locales et ouvrir la PR de remplacement

**Fichiers :**
- Créer hors Git : répertoire de preuves temporaire retourné par `mktemp -d`
- Vérifier : tous les fichiers modifiés par les tâches 2 à 4

- [ ] Vérifier que LOT37R n’a pas franchi sa frontière de périmètre :

  ```bash
  git diff --name-only origin/main...HEAD
  test -z "$(git diff --name-only origin/main...HEAD -- services packages)"
  git diff --exit-code origin/main...HEAD -- \
    services/rag-pedago/configs/pedago_interface_contract.yml \
    services/rag-pedago/configs/transition_authorization.yml \
    scripts/governance-locks.baseline
  ```

  Attendu : aucun chemin sous `services/` ou `packages/` ; tous les fichiers de gouvernance sont identiques octet par octet à `origin/main`.

- [ ] Exécuter la porte locale canonique complète et conserver les preuves hors du worktree :

  ```bash
  EVIDENCE_DIR="$(mktemp -d /tmp/nexus-lot37r-evidence.XXXXXX)"
  touch "$EVIDENCE_DIR/.nexus-lot37r-evidence"
  EVIDENCE_POINTER="$(git rev-parse --git-path LOT37R_EVIDENCE_DIR)"
  printf '%s\n' "$EVIDENCE_DIR" > "$EVIDENCE_POINTER"
  CI_SOURCE_SHA="$(git rev-parse HEAD)"
  set -o pipefail
  bash scripts/ci-local.sh 2>&1 | tee "$EVIDENCE_DIR/ci-local.log"
  sha256sum "$EVIDENCE_DIR/ci-local.log" | tee "$EVIDENCE_DIR/ci-local.sha256"
  grep -F "Total: 13 passed, 0 failed" "$EVIDENCE_DIR/ci-local.log"
  ```

  Attendu : les treize cibles canoniques passent, dont le garde sur la vraie racine, les deux régressions comportementales et le test de politique. Si le nombre change pour une raison revue, actualiser ce plan et le rapport avant de poursuivre ; ne jamais affaiblir l’assertion ad hoc.

- [ ] Exécuter les derniers contrôles locaux du dépôt au `CI_SOURCE_SHA` :

  ```bash
  git diff --check origin/main...HEAD
  bash scripts/check-governance-locks.sh
  git status --short --branch
  ```

  Attendu : aucune erreur d’espace, gouvernance verte et branche propre.

- [ ] Pousser uniquement la branche LOT37R et créer son unique PR brouillon :

  ```bash
  git push -u origin lot-37r-source-truth-reconciliation
  PR_URL="$(gh pr create \
    --draft \
    --base main \
    --head lot-37r-source-truth-reconciliation \
    --title "ci: réconcilie la source de vérité" \
    --body $'## Objet\n\nRemplace les PR brouillon #56 et #77 par le LOT37R minimal décrit dans la conception de go-live.\n\n## Limites\n\nAucun code service, dépendance, verrou de gouvernance, corpus ou runtime n’est modifié.\n\n## Validation\n\nLa preuve détaillée sera ajoutée au rapport LOT37R avant passage en ready.')"
  printf '%s\n' "$PR_URL"
  ```

  Attendu : une unique PR brouillon ciblant `main` ; aucune autre branche n’est poussée.

- [ ] Attendre les checks initiaux de la PR afin que le nouveau contexte existe sur GitHub :

  ```bash
  EVIDENCE_POINTER="$(git rev-parse --git-path LOT37R_EVIDENCE_DIR)"
  EVIDENCE_DIR="$(realpath -e "$(<"$EVIDENCE_POINTER")")"
  test "$(dirname "$EVIDENCE_DIR")" = "/tmp"
  [[ "$(basename "$EVIDENCE_DIR")" =~ ^nexus-lot37r-evidence\.[A-Za-z0-9]{6}$ ]]
  test -f "$EVIDENCE_DIR/.nexus-lot37r-evidence"
  PR_URL="$(gh pr view --json url --jq .url)"
  PR_HEAD_SHA="$(gh pr view "$PR_URL" --json headRefOid --jq .headRefOid)"
  gh pr checks "$PR_URL" --watch --fail-fast
  PR_RUN_ID=""
  for attempt in $(seq 1 30); do
    PR_RUN_ID="$(gh run list \
      --workflow .github/workflows/ci.yml \
      --branch lot-37r-source-truth-reconciliation \
      --event pull_request \
      --limit 20 \
      --json databaseId,headSha,conclusion \
      --jq ".[] | select(.headSha == \"$PR_HEAD_SHA\" and .conclusion == \"success\") | .databaseId" \
      | head -n 1)"
    [ -n "$PR_RUN_ID" ] && break
    sleep 2
  done
  test -n "$PR_RUN_ID"
  gh run view "$PR_RUN_ID" --json event,headSha,conclusion,url,jobs \
    --jq '{event,headSha,conclusion,url,jobs:[.jobs[]|{name,conclusion}]}' \
    > "$EVIDENCE_DIR/pr-checks-raw.json"
  python3.11 - "$EVIDENCE_DIR/pr-checks-raw.json" \
      > "$EVIDENCE_DIR/pr-required-checks.json" <<'PY'
  import json
  import sys
  from collections import Counter

  required = {
      "packages/contracts",
      "services/rag-pedago",
      "services/rag-engine",
      "services/cockpit",
      "governance locks guard",
      "repository controls",
  }
  with open(sys.argv[1], encoding="utf-8") as stream:
      source = json.load(stream)
  if source["event"] != "pull_request" or source["conclusion"] != "success":
      raise SystemExit(f"wrong workflow run: {source}")
  selected = [item for item in source["jobs"] if item["name"] in required]
  counts = Counter(item["name"] for item in selected)
  if set(counts) != required or any(count != 1 for count in counts.values()):
      raise SystemExit(f"required check set mismatch: {counts}")
  if any(item["conclusion"] != "success" for item in selected):
      raise SystemExit(f"required check not successful: {selected}")
  normalized = {
      "headSha": source["headSha"],
      "event": source["event"],
      "runUrl": source["url"],
      "checks": sorted(
          ({"name": item["name"], "conclusion": "SUCCESS"} for item in selected),
          key=lambda item: item["name"],
      ),
  }
  print(json.dumps(normalized, ensure_ascii=False, indent=2))
  PY
  sha256sum "$EVIDENCE_DIR/pr-required-checks.json"
  ```

  Attendu : l’artefact normalisé provient d’un run unique `pull_request` attaché au SHA de tête, et contient exactement une fois chacun des six contextes avec `SUCCESS`. Le run `push` simultané et GitGuardian sont volontairement exclus de l’ensemble obligatoire versionné.

## Tâche 6 : appliquer la protection de branche et rédiger le rapport LOT37R

**Fichiers :**
- Créer : `docs/reports/lot_37r_source_truth_reconciliation.md`
- Créer : `docs/reports/evidence/lot_37r/ci-local-summary.txt`
- Créer : `docs/reports/evidence/lot_37r/pr-required-checks.json`
- Créer : `docs/reports/evidence/lot_37r/main-protection-readback.json`
- Lire : `docs/reports/lot_0_dettes.md`
- Lire : preuves CI locales temporaires de la tâche 5

- [ ] Appliquer la politique revue au SHA encore courant de `main` distante :

  ```bash
  EVIDENCE_POINTER="$(git rev-parse --git-path LOT37R_EVIDENCE_DIR)"
  EVIDENCE_DIR="$(realpath -e "$(<"$EVIDENCE_POINTER")")"
  test "$(dirname "$EVIDENCE_DIR")" = "/tmp"
  [[ "$(basename "$EVIDENCE_DIR")" =~ ^nexus-lot37r-evidence\.[A-Za-z0-9]{6}$ ]]
  test -d "$EVIDENCE_DIR"
  test -f "$EVIDENCE_DIR/.nexus-lot37r-evidence"
  EXPECTED_MAIN_SHA="$(gh api \
    -H "X-GitHub-Api-Version: 2026-03-10" \
    repos/cyranoaladin/RAG/git/ref/heads/main \
    --jq .object.sha)"
  test "$EXPECTED_MAIN_SHA" = "$(git rev-parse origin/main)"
  NEXUS_CONFIRM_MAIN_PROTECTION="cyranoaladin/RAG@$EXPECTED_MAIN_SHA" \
    python3.11 scripts/github/main_protection.py \
      --repository cyranoaladin/RAG \
      --apply \
      --expected-main-sha "$EXPECTED_MAIN_SHA" \
    | tee "$EVIDENCE_DIR/main-protection-apply.log"
  python3.11 scripts/github/main_protection.py \
    --repository cyranoaladin/RAG --check \
    | tee "$EVIDENCE_DIR/main-protection-check.log"
  sha256sum \
    "$EVIDENCE_DIR/main-protection-apply.log" \
    "$EVIDENCE_DIR/main-protection-check.log"
  ```

  Attendu : application et relecture affichent le même verdict de succès ; `main` distante impose checks stricts, PR avec zéro approbation générale, application aux administrateurs, résolution des conversations, historique linéaire, sans force-push ni suppression.

- [ ] Interroger directement la politique active et vérifier ses champs critiques de sécurité :

  ```bash
  gh api \
    -H "X-GitHub-Api-Version: 2026-03-10" \
    repos/cyranoaladin/RAG/branches/main/protection \
    --jq '{strict:.required_status_checks.strict,contexts:.required_status_checks.contexts,admins:.enforce_admins.enabled,reviews:.required_pull_request_reviews.required_approving_review_count,linear:.required_linear_history.enabled,force:.allow_force_pushes.enabled,deletions:.allow_deletions.enabled,conversations:.required_conversation_resolution.enabled}'
  ```

  Attendu : `strict/admins/linear/conversations=true`, `reviews=0`, `force/deletions=false` et exactement six contextes obligatoires.

- [ ] Avec `apply_patch`, créer les trois fichiers de preuve expurgés et durables depuis les artefacts temporaires :

  - `ci-local-summary.txt` contient l’heure UTC d’observation, `CI_SOURCE_SHA`, treize lignes de cible `PASS`, `Total: 13 passed, 0 failed` et le SHA-256 du log local brut ; aucun chemin d’exécutable ni log d’installation de paquet.
  - `pr-required-checks.json` contient le `headSha` normalisé et les six checks réussis du fichier temporaire homonyme, avec l’heure UTC d’observation.
  - `main-protection-readback.json` contient uniquement les champs gouvernés normalisés retournés par `main_protection.py --check`, le SHA `main` protégé et l’heure UTC d’observation.

  Relancer les normaliseurs et comparer chaque valeur copiée ; ne jamais éditer manuellement un verdict.

- [ ] Créer `docs/reports/lot_37r_source_truth_reconciliation.md` en français, sans `TODO`, `TBD`, `pending` ni champ vide, avec ces sections exactes :

  1. `Verdict` — `LOT37R_READY_FOR_MERGE`, explicitement distinct du `GO_LIVE` global qui reste `NO_GO` jusqu’à LOT47.
  2. `Périmètre` — SHA baseline `origin/main`, `CI_SOURCE_SHA`, SHA de conception, branche, URL de PR, date UTC et exclusions explicites.
  3. `Réconciliation PR 56/77` — pour chaque PR : SHA de tête, état brouillon/ouvert, nombre de fichiers, conclusions des checks, idées réutilisables, changements exclus et décision `SUPERSEDED_AFTER_LOT37R_MERGE`.
  4. `Inventaire des stashes` — chaque entrée de `git stash list` par commit immuable, branche source, lot propriétaire si inférable et disposition `NOT_DELIVERED` ; aucun contenu de stash.
  5. `Dettes` — une ligne par titre non résolu ou historique de `docs/reports/lot_0_dettes.md`, classée exactement `bloquante_pilote`, `non_bloquante_avec_preuve` ou `hors_perimetre`, avec statut de résolution séparé, preuve sur `main` courante et lot de destination. Aucune assertion ancienne n’est acceptée sans revérification.
  6. `Topologie CI` — prouver que `rag-pr-audit.sh` n’appelle plus la CI canonique, que le marqueur échoue avant setup et que tous les tests comportementaux sont raccordés en local et à distance.
  7. `Protection de main` — SHA-256 de la politique, champs relus en live, SHA-256 du log d’application, raison de l’absence d’approbation générale obligatoire et rappel que LOT41A, LOT43A et la production publique restent des portes humaines.
  8. `Matrice de preuve` — table `critère → propriétaire → commande/procédure → environnement → artefact → SHA-256 → verdict` couvrant les treize cibles locales et six checks distants obligatoires.
  9. `Décision de livraison` — squash merge uniquement après checks finaux et revue indépendante ; fermeture et suppression des branches PR 56/77 uniquement après fusion du remplacement.

- [ ] Renseigner les preuves dynamiques avec des commandes en lecture seule, puis inspecter manuellement le rapport :

  ```bash
  EVIDENCE_POINTER="$(git rev-parse --git-path LOT37R_EVIDENCE_DIR)"
  EVIDENCE_DIR="$(realpath -e "$(<"$EVIDENCE_POINTER")")"
  test "$(dirname "$EVIDENCE_DIR")" = "/tmp"
  [[ "$(basename "$EVIDENCE_DIR")" =~ ^nexus-lot37r-evidence\.[A-Za-z0-9]{6}$ ]]
  test -f "$EVIDENCE_DIR/.nexus-lot37r-evidence"
  PR_URL="$(gh pr view --json url --jq .url)"
  gh pr view "$PR_URL" --json number,url,headRefOid,state,isDraft,files,statusCheckRollup
  gh pr view 56 --json number,url,headRefOid,state,isDraft,files,statusCheckRollup
  gh pr view 77 --json number,url,headRefOid,state,isDraft,files,statusCheckRollup
  git stash list --format='%gd%x09%H%x09%gs'
  sha256sum \
    scripts/ci-local.sh \
    scripts/audit/rag-pr-audit.sh \
    scripts/github/main-protection-policy.json \
    docs/reports/evidence/lot_37r/ci-local-summary.txt \
    docs/reports/evidence/lot_37r/pr-required-checks.json \
    docs/reports/evidence/lot_37r/main-protection-readback.json \
    "$EVIDENCE_DIR/ci-local.log" \
    "$EVIDENCE_DIR/main-protection-apply.log" \
    "$EVIDENCE_DIR/main-protection-check.log"
  rg -n 'TODO|TBD|pending|/home/|alaeddine|BEGIN .*PRIVATE KEY|gh[pousr]_' \
    docs/reports/lot_37r_source_truth_reconciliation.md \
    docs/reports/evidence/lot_37r/
  ```

  Attendu : les cinq premières commandes fournissent toutes les valeurs du rapport ; le dernier `rg` sort avec `1` sans correspondance. Consigner uniquement digests et synthèses, jamais les preuves brutes d’environnement ni les identifiants.

- [ ] Committer le rapport achevé :

  ```bash
  git add \
    docs/reports/lot_37r_source_truth_reconciliation.md \
    docs/reports/evidence/lot_37r/ci-local-summary.txt \
    docs/reports/evidence/lot_37r/pr-required-checks.json \
    docs/reports/evidence/lot_37r/main-protection-readback.json
  git commit -m "docs: consigne la réconciliation LOT37R"
  git push
  ```

  Attendu : un commit documentaire uniquement ; la branche reste l’unique tête de la PR de remplacement.

## Tâche 7 : revoir, fusionner, clore les travaux supersédés et vérifier `main`

**Fichiers :**
- Vérifier : diff LOT37R complet et rapport
- État externe : PR de remplacement, `main` protégée, PR 56 et PR 77

- [ ] Invoquer `superpowers:requesting-code-review` sur `origin/main...HEAD` ; résoudre chaque constat bloquant dans un nouveau commit scopé, relancer les tests ciblés concernés puis `bash scripts/ci-local.sh`, et actualiser le rapport si une preuve change.

  Si la revue entraîne un changement, conserver le même répertoire temporaire validé, remplacer `ci-local.log` par la nouvelle exécution complète, relever le nouveau SHA source, recalculer le SHA-256, régénérer avec `apply_patch` `ci-local-summary.txt` et toutes les lignes affectées du rapport, puis committer séparément cette actualisation avant le push final. Une preuve portant sur l’ancien SHA ne peut pas être réutilisée.

- [ ] Pousser les éventuelles corrections revues et attendre la tête finale de la PR de remplacement :

  ```bash
  PR_URL="$(gh pr view --json url --jq .url)"
  FINAL_HEAD_SHA="$(git rev-parse HEAD)"
  git push
  gh pr checks "$PR_URL" --watch --fail-fast
  test "$(gh pr view "$PR_URL" --json headRefOid --jq .headRefOid)" = "$FINAL_HEAD_SHA"
  python3.11 scripts/github/main_protection.py \
    --repository cyranoaladin/RAG --check
  git status --short --branch
  ```

  Attendu : tous les checks appartiennent à `FINAL_HEAD_SHA`, la protection active correspond à la politique et le worktree est propre.

- [ ] Passer la PR en ready et la fusionner sans contourner la protection :

  ```bash
  PR_URL="$(gh pr view --json url --jq .url)"
  FINAL_HEAD_SHA="$(git rev-parse HEAD)"
  gh pr ready "$PR_URL"
  gh pr merge "$PR_URL" \
    --squash \
    --match-head-commit "$FINAL_HEAD_SHA" \
    --subject "ci: réconcilie la source de vérité"
  ```

  Attendu : GitHub effectue le squash merge par le chemin de PR protégé. Ne jamais utiliser `--admin`.

- [ ] Récupérer la vérité fusionnée et attendre son workflow `main` :

  ```bash
  PR_URL="$(gh pr view --json url --jq .url)"
  git fetch --prune origin
  MERGED_MAIN_SHA="$(git rev-parse origin/main)"
  test "$MERGED_MAIN_SHA" = "$(gh pr view "$PR_URL" --json mergeCommit --jq .mergeCommit.oid)"
  MAIN_RUN_ID=""
  for attempt in $(seq 1 30); do
    MAIN_RUN_ID="$(gh run list \
      --workflow .github/workflows/ci.yml \
      --branch main \
      --event push \
      --limit 20 \
      --json databaseId,headSha \
      --jq ".[] | select(.headSha == \"$MERGED_MAIN_SHA\") | .databaseId" \
      | head -n 1)"
    [ -n "$MAIN_RUN_ID" ] && break
    sleep 2
  done
  test -n "$MAIN_RUN_ID"
  gh run watch "$MAIN_RUN_ID" --exit-status
  git push origin --delete lot-37r-source-truth-reconciliation
  test -z "$(git ls-remote --heads origin refs/heads/lot-37r-source-truth-reconciliation)"
  ```

  Attendu : le SHA exact de fusion possède un workflow `main` vert, puis la branche distante fusionnée est supprimée explicitement.

- [ ] Seulement alors, fermer et supprimer les branches des deux PR supersédées en conservant le lien de remplacement dans l’historique GitHub :

  ```bash
  PR_URL="$(gh pr view --json url --jq .url)"
  REPORT_URL="https://github.com/cyranoaladin/RAG/blob/main/docs/reports/lot_37r_source_truth_reconciliation.md"
  PR56_HEAD="$(gh pr view 56 --json headRefOid --jq .headRefOid)"
  PR77_HEAD="$(gh pr view 77 --json headRefOid --jq .headRefOid)"
  test "$(gh pr view 56 --json headRefName --jq .headRefName)" = \
    "codex/post-go-live-p3-zero-debt-hardening"
  test "$(gh pr view 77 --json headRefName --jq .headRefName)" = \
    "lot-37-ci-bloquante"
  test "$(gh pr view 56 --json headRepositoryOwner --jq .headRepositoryOwner.login)" = \
    "cyranoaladin"
  test "$(gh pr view 77 --json headRepositoryOwner --jq .headRepositoryOwner.login)" = \
    "cyranoaladin"
  grep -Fq "$PR56_HEAD" docs/reports/lot_37r_source_truth_reconciliation.md
  grep -Fq "$PR77_HEAD" docs/reports/lot_37r_source_truth_reconciliation.md
  test "$(gh pr list --state open \
    --head codex/post-go-live-p3-zero-debt-hardening \
    --json number --jq 'map(.number) == [56]')" = "true"
  test "$(gh pr list --state open \
    --head lot-37-ci-bloquante \
    --json number --jq 'map(.number) == [77]')" = "true"
  gh pr close 56 --delete-branch \
    --comment "Remplacée sans fusion par $PR_URL. Décision et périmètre conservés dans $REPORT_URL."
  gh pr close 77 --delete-branch \
    --comment "Remplacée sans fusion par $PR_URL. Décision et périmètre conservés dans $REPORT_URL."
  ```

  Attendu : les deux PR sont fermées, leurs branches de tête supprimées et leurs pages immuables conservent le commentaire de disposition.

- [ ] Effectuer l’audit final en lecture seule de la source de vérité :

  ```bash
  PR_URL="$(gh pr view --json url --jq .url)"
  MERGED_MAIN_SHA="$(git rev-parse origin/main)"
  MAIN_RUN_ID="$(gh run list \
    --workflow .github/workflows/ci.yml \
    --branch main \
    --event push \
    --limit 20 \
    --json databaseId,headSha \
    --jq ".[] | select(.headSha == \"$MERGED_MAIN_SHA\") | .databaseId" \
    | head -n 1)"
  test -n "$MAIN_RUN_ID"
  test "$(gh pr view 56 --json state --jq .state)" = "CLOSED"
  test "$(gh pr view 77 --json state --jq .state)" = "CLOSED"
  test "$(gh pr view "$PR_URL" --json state --jq .state)" = "MERGED"
  python3.11 scripts/github/main_protection.py \
    --repository cyranoaladin/RAG --check
  git ls-tree -r --name-only origin/main \
    | grep -E '^MANIFEST_LOT[0-9]+\.md$' \
    && exit 1 || true
  git ls-tree -r --name-only origin/main \
    | grep -F 'docs/reports/lot_37r_source_truth_reconciliation.md'
  gh run view "$MAIN_RUN_ID" --json headSha,conclusion,url
  ```

  Attendu : remplacement fusionné, anciennes PR fermées, protection exacte, aucun manifest racine, rapport présent et conclusion Actions `success` sur le SHA exact de `main`.

- [ ] Retirer le worktree et la branche locale LOT37R achevés uniquement après avoir prouvé que leur arbre égale celui de `main` fusionnée :

  ```bash
  EVIDENCE_POINTER="$(git rev-parse --git-path LOT37R_EVIDENCE_DIR)"
  EVIDENCE_DIR="$(realpath -e "$(<"$EVIDENCE_POINTER")")"
  test "$(dirname "$EVIDENCE_DIR")" = "/tmp"
  [[ "$(basename "$EVIDENCE_DIR")" =~ ^nexus-lot37r-evidence\.[A-Za-z0-9]{6}$ ]]
  test -d "$EVIDENCE_DIR"
  test -f "$EVIDENCE_DIR/.nexus-lot37r-evidence"
  LOT37R_TREE="$(git rev-parse HEAD^{tree})"
  MAIN_TREE="$(git rev-parse origin/main^{tree})"
  test "$LOT37R_TREE" = "$MAIN_TREE"
  rm -r -- "$EVIDENCE_DIR"
  rm -f -- "$EVIDENCE_POINTER"
  cd ../RAG
  git worktree remove ../RAG-lot37r
  git branch -D lot-37r-source-truth-reconciliation
  git status --short --branch
  ```

  Attendu : les preuves brutes temporaires ne sont supprimées qu’après versionnement et fusion de leurs artefacts expurgés ; le worktree achevé exact et sa branche locale sont retirés ; le worktree principal reste propre. Les stashes restent intacts et explicitement `NOT_DELIVERED` pour les lots ultérieurs.

  Les logs GitHub Actions restent attachés aux runs immuables de la PR et de `main`. Les logs CI locaux de LOT37R sont des artefacts de travail, pas des preuves brutes de l’environnement cible au sens de la conception ; leur synthèse expurgée et son digest sont versionnés avant suppression. Les preuves brutes de validation/production des lots 42 à 47 suivront, elles, la rétention chiffrée définie par la conception.
