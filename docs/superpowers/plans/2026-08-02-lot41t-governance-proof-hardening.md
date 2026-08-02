# LOT41T Governance Proof Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development
> (if subagents available) or superpowers:executing-plans to implement this plan.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fermer les autorisations auto-déclarées des LOT38/39bis, restaurer un
état golden honnêtement en attente, corriger la métrique taxonomique et le CLI,
puis consigner et publier les preuves du lot sans lever de verrou.

**Architecture:** Les validateurs locaux continuent à vérifier la structure et
l'intégrité des revendications, mais aucune revendication stockée dans le dépôt
ne peut produire une autorisation. `evaluate_authorization()` ajoute des motifs
de confiance manquante ; l'audit golden classe une revendication complète mais
non authentifiée comme `PENDING`. Les adaptateurs GitHub/ledger et la signature
Ed25519 restent une frontière LOT41A/LOT42 explicitement documentée.

**Tech Stack:** Python 3.11, Pydantic 2, PyYAML, pytest, Ruff, mypy, scripts
shell de gouvernance et GitHub CLI pour la livraison.

**Spec:**
`docs/superpowers/specs/2026-08-02-lot41t-governance-proof-hardening-design.md`

---

## Cartographie des fichiers

| Fichier | Responsabilité |
| --- | --- |
| `services/rag-pedago/rag_pedago/governance/pilot_validation.py` | Refus explicite des preuves GitHub et de publication locales |
| `services/rag-pedago/tests/unit/test_pilot_validation_authorization.py` | Réfutations YAML, mémoire, package et opérations sans package |
| `services/rag-pedago/rag_pedago/governance/pilot_golden.py` | Une revendication locale complète reste `PENDING` |
| `services/rag-pedago/configs/pilot_golden_human_review.yml` | État canonique `pending` sans identité auto-déclarée |
| `services/rag-pedago/tests/unit/test_pilot_golden_spec.py` | Forge complète, canonique pending et CLI direct |
| `services/rag-pedago/tests/golden_queries/README.md` | Sémantique non autoritaire de l'audit offline |
| `services/rag-pedago/scripts/pilot_golden_spec_audit.py` | Transmission de `sys.argv[1:]` |
| `services/rag-pedago/scripts/pilot_validation_policy_audit.py` | Libellé exact de cardinalité taxonomique |
| `services/rag-pedago/tests/unit/test_pilot_validation_policy_audit.py` | Non-régression du libellé sans fausse couverture |
| `docs/reports/evidence/lot_39bis/golden_human_review_packet.md` | Bandeau d'erratum visible dans la trace historique |
| `docs/reports/lot_38_governance_transition.md` | Erratum sur les preuves auto-déclarées |
| `docs/reports/lot_39bis_golden_suite.md` | Erratum sur la prétendue approbation PR #82 |
| `docs/reports/lot_41t_governance_proof_hardening.md` | Rapport, preuves fraîches et verdict du lot |

## Task 0 — Préparer l'environnement isolé

- [ ] **Step 1: Découvrir un Python supporté et installer le service**

Le worktree n'hérite pas du `.venv` ignoré du checkout principal. Depuis
`services/rag-pedago`, créer son environnement propre sans versionner de chemin
machine-local :

```bash
TASK_PY_SYS="$(command -v python3.12 || command -v python3.11)"
test -n "$TASK_PY_SYS"
make PY_SYS="$TASK_PY_SYS" install
.venv/bin/python --version
.venv/bin/python -c 'import pydantic, pytest, yaml'
```

Expected: Python >= 3.11 et imports réussis. Le `.venv` reste ignoré.

Créer aussi un shim CI temporaire non versionné, car `ci-local.sh` cherche
`python3.11` avant `python3.12` et le premier binaire du `PATH` hôte est
défaillant :

```bash
TASK_CI_BIN="$(mktemp -d)"
ln -s "$TASK_PY_SYS" "$TASK_CI_BIN/python3.11"
"$TASK_CI_BIN/python3.11" -m venv "$TASK_CI_BIN/venv-probe"
"$TASK_CI_BIN/venv-probe/bin/python" --version
```

Expected: création du venv de contrôle réussie. Recréer ce shim par la même
procédure pour chaque CI complète ; ne jamais versionner son chemin.

- [ ] **Step 2: Verrouiller les prérequis de CI racine**

Depuis la racine du worktree :

```bash
set -e
test -s "${NVM_DIR:?}/nvm.sh"
. "$NVM_DIR/nvm.sh"
nvm use 22
node --version
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 22) ? 0 : 1)'
bash --version | head -1
```

Expected: Node >= 22.22.0 et shell disponible.

## Task 1 — Fermer le garde de transition

**Files:**
- Modify: `services/rag-pedago/tests/unit/test_pilot_validation_authorization.py`
- Modify: `services/rag-pedago/rag_pedago/governance/pilot_validation.py`

- [ ] **Step 1: Écrire les tests rouges d'absence d'autorité**

Remplacer les quatre attentes positives historiques par des attentes de refus
et ajouter des tests explicites qui couvrent :

- le fixture YAML cohérent et son digest recalculé ;
- les mêmes modèles chargés puis fournis directement en mémoire ;
- une opération sans package ;
- le package historique `passed/passed/reviewed` ;
- un contenu opaque contenant un autre tenant/collection avec SHA recalculé.

Une approbation locale cohérente doit contenir
`approval.trusted_channel_unavailable`. Une publication avec package local doit
contenir `package.scope_attestation_unavailable` et
`package.trusted_attestations_unavailable`. Conserver les assertions existantes
sur chaque incohérence spécifique ; adapter uniquement les tuples exacts qui
reçoivent les nouveaux motifs globaux.

- [ ] **Step 2: Vérifier le rouge**

Run:

```bash
cd services/rag-pedago
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/unit/test_pilot_validation_authorization.py
```

Expected: FAIL uniquement sur les nouveaux refus de canal et d'attestations.

- [ ] **Step 3: Implémenter le refus minimal**

Après les contrôles de cohérence de `GitHubApprovalEvidence`, ajouter toujours
`approval.trusted_channel_unavailable` pour une preuve locale valide. Dans la
branche `publish_reviewed_chunks`, ajouter les deux motifs package pour tout
`PublicationPackage` local valide. Les contrôles historiques de digest, chemin,
quarantaine, révocation et publisher restent diagnostiques ; les chaînes
`quality/gate/review` ne doivent jamais neutraliser les motifs globaux.

Ne pas ajouter de paramètre de confiance injectable, de réseau, de clé, de
contrat cross-service ou d'appelant runtime.

- [ ] **Step 4: Vérifier le vert et la qualité**

Run:

```bash
cd services/rag-pedago
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/unit/test_pilot_validation_authorization.py
.venv/bin/ruff check rag_pedago/governance/pilot_validation.py \
  tests/unit/test_pilot_validation_authorization.py
.venv/bin/mypy rag_pedago/governance/pilot_validation.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/rag-pedago/rag_pedago/governance/pilot_validation.py \
  services/rag-pedago/tests/unit/test_pilot_validation_authorization.py
git commit -m "rag-pedago: fermer les preuves de transition locales"
```

## Task 2 — Reclasser la revue golden en attente

**Files:**
- Modify: `services/rag-pedago/tests/unit/test_pilot_golden_spec.py`
- Modify: `services/rag-pedago/rag_pedago/governance/pilot_golden.py`
- Modify: `services/rag-pedago/configs/pilot_golden_human_review.yml`
- Modify: `services/rag-pedago/scripts/pilot_golden_spec_audit.py`
- Modify: `services/rag-pedago/tests/golden_queries/README.md`
- Modify: `docs/reports/evidence/lot_39bis/golden_human_review_packet.md`

- [ ] **Step 1: Écrire les tests rouges du verdict non authentifié**

Exiger que :

- le canonique rende `SPECIFICATION_VALID`, `LOCK_VALID`, 255 et
  `HUMAN_REVIEW_PENDING`, sans raison d'intégrité ;
- un manifeste `approved` et un paquet complet fabriqués ensemble rendent
  `HUMAN_REVIEW_PENDING` avec
  `human_review.trusted_channel_unavailable` ;
- une revendication `approved` incomplète reste `HUMAN_REVIEW_INVALID` ;
- aucune branche de test ne peut obtenir `HUMAN_REVIEW_APPROVED` ;
- `main([])` rende `3` pour le canonique pending ;
- une exécution subprocess
  `python scripts/pilot_golden_spec_audit.py unexpected` rende `2`, écrive
  `unexpected_argument` sur stderr et n'imprime aucun verdict d'audit.

- [ ] **Step 2: Vérifier le rouge**

Run:

```bash
cd services/rag-pedago
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/unit/test_pilot_golden_spec.py
```

Expected: FAIL sur le canonique encore approuvé, la forge encore approuvée et
l'argument direct encore ignoré.

- [ ] **Step 3: Rendre l'audit offline explicitement non autoritaire**

Dans `_human_review_verdict`, conserver la validation exhaustive d'une
revendication `approved`. Si elle est complète, ajouter
`human_review.trusted_channel_unavailable` puis rendre
`HUMAN_REVIEW_PENDING`. Si elle est incohérente, garder
`HUMAN_REVIEW_INVALID`. Retirer `HUMAN_REVIEW_APPROVED` du `Literal` de
`PilotGoldenAuditResult` et du type de retour de `_human_review_verdict` afin
que l'invariant soit visible statiquement.

Remettre le manifeste canonique à `pending`, compte `0`, booléens `false` et
tous les champs d'identité/preuve/date à `null`. Ajouter en tête du paquet
historique un bandeau daté :

`REVENDICATION HISTORIQUE NON AUTHENTIFIÉE — NE VAUT PAS APPROBATION`.

Le bandeau renvoie vers LOT41T et précise que l'ancien commentaire PR #82 ne
liait ni le digest, ni le paquet, ni le head final. Ne pas supprimer les 255
cases historiques.

Dans le CLI, remplacer l'appel final par `main(sys.argv[1:])`.

Corriger aussi `tests/golden_queries/README.md` : un SHA-256 y est décrit comme
preuve d'intégrité seulement ; l'audit offline ne peut rendre que `PENDING` ou
`INVALID` et une future approbation dépend du readback indépendant LOT41A.

- [ ] **Step 4: Vérifier le vert et les codes CLI**

Run:

```bash
cd services/rag-pedago
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/unit/test_pilot_golden_spec.py
set +e
.venv/bin/python scripts/pilot_golden_spec_audit.py unexpected
status=$?
set -e
test "$status" -eq 2
.venv/bin/ruff check rag_pedago/governance/pilot_golden.py \
  scripts/pilot_golden_spec_audit.py tests/unit/test_pilot_golden_spec.py
.venv/bin/mypy rag_pedago/governance/pilot_golden.py \
  scripts/pilot_golden_spec_audit.py
```

Expected: tests/Ruff/mypy PASS ; invocation inattendue code `2`. L'invocation
canonique rend volontairement `3` avec `HUMAN_REVIEW_PENDING` et ne doit pas
être présentée comme un échec d'intégrité.

- [ ] **Step 5: Commit**

```bash
git add services/rag-pedago/rag_pedago/governance/pilot_golden.py \
  services/rag-pedago/configs/pilot_golden_human_review.yml \
  services/rag-pedago/scripts/pilot_golden_spec_audit.py \
  services/rag-pedago/tests/unit/test_pilot_golden_spec.py \
  services/rag-pedago/tests/golden_queries/README.md \
  docs/reports/evidence/lot_39bis/golden_human_review_packet.md
git commit -m "rag-pedago: reclasser la revue golden non authentifiée"
```

## Task 3 — Corriger la métrique et les déclarations historiques

**Files:**
- Modify: `services/rag-pedago/tests/unit/test_pilot_validation_policy_audit.py`
- Modify: `services/rag-pedago/scripts/pilot_validation_policy_audit.py`
- Modify: `docs/reports/lot_38_governance_transition.md`
- Modify: `docs/reports/lot_39bis_golden_suite.md`

- [ ] **Step 1: Écrire le test rouge de sémantique métrique**

Le rapport attendu doit contenir exactement
`Cardinalité du scope taxonomique: 39 notions` et ne doit contenir aucune ligne
commençant par `Couverture:`. Conserver toutes les autres assertions de l'audit.

- [ ] **Step 2: Vérifier le rouge puis corriger le libellé**

Run:

```bash
cd services/rag-pedago
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/unit/test_pilot_validation_policy_audit.py
```

Expected avant correction: FAIL sur le libellé. Modifier une seule ligne dans
`pilot_validation_policy_audit.py`, puis réexécuter jusqu'au vert.

- [ ] **Step 3: Ajouter les errata sans effacer l'historique**

Ajouter en tête de chacun des rapports un bloc daté `Erratum LOT41T` :

- LOT38 : les tests historiques validaient la cohérence interne, pas une
  autorité GitHub, le scope du package ni des attestations indépendantes ;
- LOT39bis : le commentaire PR #82 précédait les octets approuvés, ne portait
  aucun challenge et n'était pas une review formelle ; le verdict humain
  courant est `PENDING` et le paquet n'est qu'une trace.

Calculer le nouveau SHA-256 du paquet historique et le citer comme digest de la
trace corrigée, sans l'appeler signature ou preuve d'approbation. Ne modifier
aucun ancien résultat de test ou SHA de tête ; l'erratum prime explicitement
sur les déclarations historiques concernées.

- [ ] **Step 4: Vérifier les audits ciblés**

Run:

```bash
cd services/rag-pedago
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  tests/unit/test_pilot_validation_policy_audit.py \
  tests/unit/test_pilot_golden_spec.py
make PY=.venv/bin/python pilot-validation-policy-audit
set +e
.venv/bin/python scripts/pilot_golden_spec_audit.py
status=$?
set -e
test "$status" -eq 3
```

Expected: tests PASS ; validation `DORMANT`, cardinalité exacte et `NO_GO` avec
code `0` ; golden techniquement valide, humain `PENDING`, lock valide et code
`3`.

- [ ] **Step 5: Commit**

```bash
git add services/rag-pedago/scripts/pilot_validation_policy_audit.py \
  services/rag-pedago/tests/unit/test_pilot_validation_policy_audit.py \
  docs/reports/lot_38_governance_transition.md \
  docs/reports/lot_39bis_golden_suite.md
git commit -m "rag-pedago: corriger les preuves historiques du pilote"
```

## Task 4 — Vérification complète et rapport LOT41T

**Files:**
- Create: `docs/reports/lot_41t_governance_proof_hardening.md`

- [ ] **Step 1: Vérifier le diff et l'absence d'activation**

Run depuis la racine :

```bash
git diff --check origin/main...HEAD
git diff --exit-code origin/main...HEAD -- \
  services/rag-pedago/configs/pedago_interface_contract.yml \
  scripts/governance-locks.baseline \
  scripts/check-governance-locks.sh
bash scripts/check-governance-locks.sh
if rg -n 'validation_.*_allowed: true|real_documents_allowed: true|ui_runtime_allowed: true|answer_generation_allowed: true|curated_ingestion_allowed: true' \
    services/rag-pedago/configs/pilot_validation_policy.yml \
    services/rag-pedago/configs/pedago_interface_contract.yml; then
  echo "activation interdite détectée" >&2
  exit 1
fi
```

Expected: diff propre, garde `18/18`, aucun verrou activé. Le fixture
`activation.valid.yml` reste un fixture historique et n'est pas une
configuration canonique.

- [ ] **Step 2: Exécuter la qualité service complète**

Run:

```bash
cd services/rag-pedago
make lint
make typecheck
make test
```

Expected: PASS.

- [ ] **Step 3: Exécuter la CI locale racine fraîche**

Depuis la racine du worktree, après avoir revérifié Python supporté et Node
>= 22.22.0 :

```bash
set -e
cd "$(git rev-parse --show-toplevel)"
test -s "${NVM_DIR:?}/nvm.sh"
. "$NVM_DIR/nvm.sh"
nvm use 22
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 22) ? 0 : 1)'
TASK_PY_SYS="$(command -v python3.12 || command -v python3.11)"
TASK_CI_BIN="$(mktemp -d)"
ln -s "$TASK_PY_SYS" "$TASK_CI_BIN/python3.11"
"$TASK_CI_BIN/python3.11" -m venv "$TASK_CI_BIN/venv-probe"
PATH="$TASK_CI_BIN:$PATH" bash scripts/ci-local.sh
```

Expected: dernier bloc racine exactement `13 passed, 0 failed`. Conserver le
journal brut hors Git et calculer son SHA-256.

- [ ] **Step 4: Prouver localement le faux positif GitGuardian**

Run depuis la racine :

```bash
AUTHORIZATION_SHA="$(sha256sum services/rag-pedago/tests/fixtures/pilot_validation/authorization.valid.yml | awk '{print $1}')"
FLAGGED_VALUE="$(awk '$1 == "authorization_digest:" {print $2}' services/rag-pedago/tests/fixtures/pilot_validation/github_approval.valid.yml)"
test "$AUTHORIZATION_SHA" = "$FLAGGED_VALUE"
command -v gitleaks
gitleaks git --log-opts='origin/main..HEAD' --redact --no-banner --exit-code 1
```

Expected: égalité exacte des digests et aucun secret détecté. Conserver la
version de gitleaks et le résultat dans le rapport ; ne pas créer d'allowlist.

- [ ] **Step 5: Écrire et committer le rapport de lot**

Consigner base, `ciSourceSha` (le parent source exact sur lequel cette première
CI a tourné), commandes, résultats, digest du journal, absence de changement
des verrous, six findings corrigés, faux positif GitGuardian et limite du
dashboard. Dire explicitement que cette CI parent-SHA ne certifie pas encore le
commit documentaire du rapport. Le verdict reste
`LOT41T_LOCAL_CI_GREEN_AWAITING_FINAL_HEAD_PROOF`; le verdict global reste
`GO_LIVE: NO_GO` car LOT41A/LOT42 et les lots suivants ne sont pas réalisés.

```bash
git add docs/reports/lot_41t_governance_proof_hardening.md
git commit -m "docs: consigner le durcissement des preuves LOT41T"
```

- [ ] **Step 6: Revue indépendante du diff complet commité**

Faire relire `origin/main...HEAD`, rapport inclus, pour conformité à la spec,
sécurité, exactitude des tests et documentation. Corriger tout finding, mettre
à jour le rapport si nécessaire, committer, puis recommencer la revue sur la
nouvelle tête jusqu'à `APPROVE`.

- [ ] **Step 7: Certifier le HEAD final exact sans nouvelle modification**

Capturer la tête finale, relancer la CI complète et conserver le journal hors
Git. Cette exécution ne doit être suivie d'aucune modification avant le push :

```bash
set -e
FINAL_HEAD_SHA="$(git rev-parse HEAD)"
cd "$(git rev-parse --show-toplevel)"
test -s "${NVM_DIR:?}/nvm.sh"
. "$NVM_DIR/nvm.sh"
nvm use 22
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 22) ? 0 : 1)'
TASK_PY_SYS="$(command -v python3.12 || command -v python3.11)"
TASK_CI_BIN="$(mktemp -d)"
ln -s "$TASK_PY_SYS" "$TASK_CI_BIN/python3.11"
"$TASK_CI_BIN/python3.11" -m venv "$TASK_CI_BIN/venv-probe"
PATH="$TASK_CI_BIN:$PATH" bash scripts/ci-local.sh
test "$(git rev-parse HEAD)" = "$FINAL_HEAD_SHA"
test -z "$(git status --porcelain)"
```

Expected: `13 passed, 0 failed` sur `FINAL_HEAD_SHA`. Cette preuve finale est
jointe à la description/commentaire PR hors dépôt ; les checks
`pull_request` du même SHA constituent la preuve durable de livraison.

## Task 5 — Publier, fusionner et fermer les anciens fils

- [ ] **Step 1: Capturer la tête, pousser et ouvrir la PR**

Capturer `HEAD_SHA=$(git rev-parse HEAD)`, pousser explicitement
`lot-41t-governance-proof`, ouvrir une PR vers `main`, puis demander les revues
automatiques. La description relie les PR #81/#82, précise le refus
fail-closed, l'état golden pending, la CI finale de `HEAD_SHA` et
`GO_LIVE: NO_GO`.

- [ ] **Step 2: Vérifier la tête PR exacte**

Exiger sur un run unique `pull_request` attaché au head exact les six contextes
obligatoires, chacun exactement une fois et `SUCCESS`. Vérifier séparément
GitGuardian, Cubic et Codex. La review Codex doit déclarer explicitement
`Reviewed commit: HEAD_SHA`. Inventorier les threads de la PR LOT41T et exiger
zéro fil non résolu avant fusion. Tout finding actionnable relance le cycle TDD,
produit un nouveau `HEAD_SHA` et invalide toutes les preuves antérieures.

- [ ] **Step 3: Squash-merge et vérifier `main`**

Fusionner seulement après tous les checks verts avec
`gh pr merge --squash --match-head-commit "$HEAD_SHA"`, sans `--admin` et sans
`--delete-branch` depuis le worktree lié. Relire la PR et exiger `state=MERGED`,
capturer le SHA squash, mettre à jour le checkout principal en fast-forward et
vérifier le run `push` attaché à ce SHA exact. Supprimer ensuite explicitement
la branche distante exacte avec
`git push origin --delete lot-41t-governance-proof`, puis le worktree LOT41T et
la branche locale `lot-41t-governance-proof` seulement ; ne supprimer aucune
autre branche pour fabriquer artificiellement un inventaire limité à `main`.

- [ ] **Step 4: Répondre et résoudre les six fils**

Avant toute mutation, inventorier et faire correspondre les six IDs de threads
GraphQL et les six IDs de commentaires inline : quatre sur PR #81, deux sur PR
#82. Répondre via l'endpoint de réponse inline exact avec la PR LOT41T, le SHA
squash, le comportement corrigé et les tests pertinents. Résoudre ensuite
chaque thread par son ID GraphQL et relire exactement six
`isResolved: true`.

- [ ] **Step 5: Documenter GitGuardian sans faux pouvoir**

Ajouter à la PR #81 un commentaire séparé citant l'égalité de digest, la
version/commande gitleaks et son résultat vert. Ne pas prétendre classer
l'incident : demander au propriétaire du dashboard de choisir
`Ignore / false positive` si l'alerte y reste ouverte.

- [ ] **Step 6: Audit final de source de vérité**

Relire branches, worktrees, PRs ouvertes, checks, protection de `main`, état
GitGuardian et rapports. Préserver le worktree utilisateur LOT36. Rendre un
verdict global factuel : LOT41T terminé ne vaut pas go-live tant que les lots
d'autorité, corpus, évaluation, déploiement et canary restent incomplets.
