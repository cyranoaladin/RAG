# LOT41V Trusted Human Review Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Imposer et prouver une approbation GitHub indépendante sur le head exact d'une PR avant toute future autorisation LOT41A.

**Architecture:** Un vérificateur Python pur calcule un challenge canonique et évalue les métadonnées GitHub. Un adaptateur GitHub séparé collecte les données et publie un statut, depuis un workflow privilégié présent uniquement sur `main` et n'exécutant jamais le code de la PR. La protection versionnée ajoute ce statut, une review Code Owner et l'approbation du dernier push après fusion du workflow.

**Tech Stack:** Python 3.11+ standard library, GitHub Actions, `gh api`, JSON strict, `unittest`, Bash CI, CODEOWNERS.

---

## Chunk 1: Autorité locale et politique cible

### Task 1: Établir le reviewer GitHub autorisé

**Files:**
- No repository files changed in this task.

- [ ] **Step 1: Relire le rôle courant sans mutation**

Run:

```bash
gh api repos/cyranoaladin/RAG/collaborators/abenrhouma/permission \
  --jq '{user:.user.login,permission,role_name}'
```

Expected: `user=abenrhouma`, rôle courant `read`.

- [ ] **Step 2: Promouvoir le reviewer avec l'autorisation déjà reçue**

Run:

```bash
gh api --method PUT repos/cyranoaladin/RAG/collaborators/abenrhouma \
  -f permission=push
```

Expected: HTTP 204 ou invitation GitHub explicite. Ne jamais accepter
l'invitation à la place de `abenrhouma` si GitHub en crée une.

- [ ] **Step 3: Relire le rôle effectif**

Run:

```bash
gh api repos/cyranoaladin/RAG/collaborators/abenrhouma/permission \
  --jq '{user:.user.login,permission,role_name}'
```

Expected: `permission=push` et `role_name=write`. Si une invitation reste en
attente, arrêter avant toute activation de protection et demander à
`abenrhouma` de l'accepter.

### Task 2: Rendre la politique et CODEOWNERS stricts

**Files:**
- Create: `.github/CODEOWNERS`
- Modify: `scripts/github/main-protection-policy.json`
- Modify: `scripts/tests/test-main-protection-policy.py`
- Modify: `scripts/tests/test-ci-local-failsafe.sh`

- [ ] **Step 1: Écrire les tests rouges de politique**

Dans `expected_policy()`, attendre :

```python
CONTEXTS = [
    "packages/contracts",
    "services/rag-pedago",
    "services/rag-engine",
    "services/cockpit",
    "governance locks guard",
    "repository controls",
    "trusted-human-review",
]

"required_pull_request_reviews": {
    "dismiss_stale_reviews": True,
    "require_code_owner_reviews": True,
    "required_approving_review_count": 1,
    "require_last_push_approval": True,
}
```

Ajouter un test qui lit `.github/CODEOWNERS` et exige exactement :

```text
* @abenrhouma
```

Dans le test fail-safe, distinguer les six contextes produits par `ci.yml` du
contexte externe `trusted-human-review`; refuser qu'un job de PR puisse usurper
ce dernier.

- [ ] **Step 2: Vérifier RED**

Run:

```bash
python scripts/tests/test-main-protection-policy.py
bash scripts/tests/test-ci-local-failsafe.sh
```

Expected: échec sur les valeurs historiques `0/false` et l'absence de
CODEOWNERS/contexte externe.

- [ ] **Step 3: Implémenter la politique minimale**

Créer `.github/CODEOWNERS` :

```text
* @abenrhouma
```

Modifier `main-protection-policy.json` avec les quatre valeurs de review
strictes et ajouter `trusted-human-review` une seule fois aux contextes.

Adapter le test fail-safe avec deux constantes explicites :

```python
WORKFLOW_CONTEXTS = (
    "packages/contracts",
    "services/rag-pedago",
    "services/rag-engine",
    "services/cockpit",
    "governance locks guard",
    "repository controls",
)
EXTERNAL_CONTEXTS = ("trusted-human-review",)
```

Le contrôle de provenance continue d'exiger chaque `WORKFLOW_CONTEXTS`
exactement une fois dans le workflow `pull_request`; il exige en plus que le
contexte externe n'apparaisse comme nom d'aucun job de PR.

- [ ] **Step 4: Vérifier GREEN**

Run:

```bash
python scripts/tests/test-main-protection-policy.py
bash scripts/tests/test-ci-local-failsafe.sh
git diff --check
```

Expected: tous les tests passent.

- [ ] **Step 5: Commit**

```bash
git add .github/CODEOWNERS \
  scripts/github/main-protection-policy.json \
  scripts/tests/test-main-protection-policy.py \
  scripts/tests/test-ci-local-failsafe.sh
git commit -m "ci: exige une revue humaine indépendante"
```

## Chunk 2: Challenge et décision pure

### Task 3: Construire le challenge canonique

**Files:**
- Create: `scripts/github/trusted-reviewers.json`
- Create: `scripts/github/trusted_human_review.py`
- Create: `scripts/tests/test-trusted-human-review.py`

- [ ] **Step 1: Écrire les tests rouges du contrat de configuration**

Le fichier de reviewers attendu est :

```json
{
  "protocol": "NEXUS-TRUSTED-REVIEW-V1",
  "repository": "cyranoaladin/RAG",
  "base_ref": "main",
  "reviewers": ["abenrhouma"]
}
```

Tester le refus des clés inconnues, doublons, reviewer vide, dépôt différent et
protocole inconnu.

- [ ] **Step 2: Écrire le test rouge du digest**

Le test construit :

```python
payload = {
    "repository": "cyranoaladin/RAG",
    "pull_request": 89,
    "base_ref": "main",
    "base_sha": "a" * 40,
    "head_sha": "b" * 40,
    "author": "cyranoaladin",
    "reviewer": "abenrhouma",
    "protocol": "NEXUS-TRUSTED-REVIEW-V1",
}
```

Il calcule indépendamment :

```python
encoded = json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
expected = "NEXUS-TRUSTED-REVIEW-V1:" + sha256(encoded).hexdigest()
```

Puis exige que `build_challenge(payload)` retourne exactement `expected`.

- [ ] **Step 3: Vérifier RED**

Run:

```bash
python scripts/tests/test-trusted-human-review.py
```

Expected: import ou fonctions absentes.

- [ ] **Step 4: Implémenter le chargeur et le challenge**

Dans `trusted_human_review.py`, définir des validateurs stricts sans dépendance
externe :

```python
PROTOCOL = "NEXUS-TRUSTED-REVIEW-V1"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")

def canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

def build_challenge(payload: Mapping[str, object]) -> str:
    validated = validate_challenge_payload(payload)
    return f"{PROTOCOL}:{sha256(canonical_json(validated)).hexdigest()}"
```

Les mappings doivent avoir exactement les clés attendues et les SHA doivent
être hexadécimaux minuscules de 40 caractères.

- [ ] **Step 5: Vérifier GREEN**

Run:

```bash
python scripts/tests/test-trusted-human-review.py
```

Expected: tests de configuration et challenge verts.

- [ ] **Step 6: Commit**

```bash
git add scripts/github/trusted-reviewers.json \
  scripts/github/trusted_human_review.py \
  scripts/tests/test-trusted-human-review.py
git commit -m "ci: définit le challenge de revue fiable"
```

### Task 4: Évaluer les reviews sans accès réseau

**Files:**
- Modify: `scripts/github/trusted_human_review.py`
- Modify: `scripts/tests/test-trusted-human-review.py`

- [ ] **Step 1: Ajouter les tests rouges du verdict**

Créer des factories de PR, permission et reviews dans le test. Couvrir une
réussite et chaque refus séparément :

```python
decision = evaluate_trusted_review(
    pull_request=valid_pull_request(),
    reviews=[approved_review(body=expected_challenge)],
    permissions={
        "abenrhouma": {"permission": "push", "role_name": "write"}
    },
    config=load_config(CONFIG_PATH),
)
self.assertTrue(decision.approved)
self.assertEqual(decision.reviewer, "abenrhouma")
self.assertEqual(decision.head_sha, "b" * 40)
```

Cas de refus obligatoires : brouillon, PR fermée, base autre que `main`, head de
fork, auteur identique au reviewer, permission `read`, ancien commit, challenge
absent/altéré, review malformée, approbation ensuite révoquée ou remplacée par
`CHANGES_REQUESTED`, identifiants dupliqués et liste tronquée.

- [ ] **Step 2: Vérifier RED**

Run:

```bash
python scripts/tests/test-trusted-human-review.py
```

Expected: `evaluate_trusted_review` absente.

- [ ] **Step 3: Implémenter la décision fail-closed**

Créer une dataclass immuable :

```python
@dataclass(frozen=True)
class TrustedReviewDecision:
    approved: bool
    reason: str
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    reviewer: str | None = None
    review_id: int | None = None
    submitted_at: str | None = None
    challenge: str | None = None
```

La fonction trie les reviews par `(submitted_at, id)`, ne considère que les
reviewers configurés, exige une review `APPROVED` sur `commit_id == head_sha`
et une ligne du corps exactement égale au challenge. Toute review décisive
ultérieure `CHANGES_REQUESTED` ou `DISMISSED` du même reviewer refuse.

- [ ] **Step 4: Vérifier GREEN et refactorer**

Run:

```bash
python scripts/tests/test-trusted-human-review.py
python -m py_compile scripts/github/trusted_human_review.py
```

Expected: tous les cas verts, aucune sortie parasite.

- [ ] **Step 5: Commit**

```bash
git add scripts/github/trusted_human_review.py \
  scripts/tests/test-trusted-human-review.py
git commit -m "ci: vérifie les approbations du head exact"
```

## Chunk 3: Adaptateur GitHub et workflow privilégié

### Task 5: Collecter et publier par API GitHub

**Files:**
- Create: `scripts/github/trusted_human_review_github.py`
- Create: `scripts/tests/test-trusted-human-review-github.py`

- [ ] **Step 1: Écrire les tests rouges de l'adaptateur**

Utiliser un `RecordingRunner` injecté, sur le modèle de
`test-main-protection-policy.py`. Vérifier les appels sans shell :

```text
GET repos/cyranoaladin/RAG/pulls/89
GET repos/cyranoaladin/RAG/pulls/89/reviews?per_page=100
GET repos/cyranoaladin/RAG/collaborators/abenrhouma/permission
POST repos/cyranoaladin/RAG/statuses/<head>
GET/POST/PATCH repos/cyranoaladin/RAG/issues/89/comments
```

Tester : pagination complète, limite de pages, timeout, JSON malformé, course de
head, statut `pending` avant toute première lecture de PR, `success` seulement
après décision pure, `failure` sur tout refus ou erreur de lecture et commentaire
géré par marqueur HTML unique.

- [ ] **Step 2: Vérifier RED**

Run:

```bash
python scripts/tests/test-trusted-human-review-github.py
```

Expected: module absent.

- [ ] **Step 3: Implémenter l'adaptateur borné**

Définir :

```python
STATUS_CONTEXT = "trusted-human-review"
COMMENT_MARKER = "<!-- nexus:trusted-human-review:v1 -->"
GH_API_TIMEOUT_SECONDS = 30
MAX_REVIEW_PAGES = 20
```

Le runner reçoit uniquement des listes d'arguments `gh api`, utilise
`subprocess.run(..., shell=False, timeout=30)` et ne journalise jamais de token.
Le mode `--check` est read-only et imprime le verdict normalisé. Le mode
`--publish` place le statut et met à jour le commentaire géré.

Une course entre l'event et le readback live ne peut jamais produire `success` :
`--expected-head` doit correspondre au head relu avant publication.

- [ ] **Step 4: Vérifier GREEN**

Run:

```bash
python scripts/tests/test-trusted-human-review-github.py
python -m py_compile scripts/github/trusted_human_review_github.py
```

Expected: tous les tests verts.

- [ ] **Step 5: Commit**

```bash
git add scripts/github/trusted_human_review_github.py \
  scripts/tests/test-trusted-human-review-github.py
git commit -m "ci: publie le verdict de revue GitHub"
```

### Task 6: Installer le workflow de base sans exécuter la PR

**Files:**
- Create: `.github/workflows/trusted-human-review.yml`
- Create: `scripts/tests/test-trusted-human-review-workflow.py`

- [ ] **Step 1: Écrire les tests rouges du workflow**

Parser le YAML avec `yaml.safe_load` et exiger :

```yaml
on:
  pull_request_target:
    types: [opened, reopened, synchronize, ready_for_review, edited]
  issue_comment:
    types: [created]
permissions:
  contents: read
  pull-requests: read
  issues: write
  statuses: write
```

Le test refuse `pull_request`, `pull_request_review`, `push`, `secrets.*`,
`checkout` du head, toute référence à
`github.event.pull_request.head.ref` dans `actions/checkout`, et tout `run`
construit à partir du titre, corps, branche ou auteur de la PR. Le trigger
`issue_comment` n'accepte que la commande littérale
`/nexus-trusted-review` sur une PR.

- [ ] **Step 2: Vérifier RED**

Run:

```bash
python scripts/tests/test-trusted-human-review-workflow.py
```

Expected: workflow absent.

- [ ] **Step 3: Créer le workflow minimal**

Le job unique :

1. checkout explicitement `refs/heads/main`, `persist-credentials: false` ;
2. setup Python 3.11 ;
3. calcule le numéro de PR depuis un champ numérique d'événement ;
4. pour `issue_comment`, relit le head par API après validation du numéro ;
5. appelle l'adaptateur avec `GH_TOKEN: ${{ github.token }}` et
   `--expected-head` issu de l'événement ou du readback ;
6. utilise une concurrence par numéro de PR avec `cancel-in-progress: true`.

Aucun code, fichier ou action provenant du head n'est utilisé.
`pull_request_review` est exclu car son merge ref pourrait charger un YAML
proposé par la PR ; après une review, le recalcul sûr est déclenché par le
commentaire littéral. `workflow_dispatch` est également exclu car son appelant
peut choisir le `ref` exécuté.

- [ ] **Step 4: Vérifier GREEN**

Run:

```bash
python scripts/tests/test-trusted-human-review-workflow.py
bash scripts/tests/test-ci-local-failsafe.sh
```

Expected: workflow accepté et contexte externe non usurpé.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/trusted-human-review.yml \
  scripts/tests/test-trusted-human-review-workflow.py
git commit -m "ci: installe la revue humaine privilégiée"
```

## Chunk 4: CI, documentation et livraison

### Task 7: Rendre les nouveaux tests obligatoires

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci-local.sh`
- Modify: `scripts/tests/test-ci-local-topology.sh`
- Modify: `scripts/tests/test-ci-local-failsafe.sh`

- [ ] **Step 1: Écrire les assertions rouges de topologie**

Exiger dans `repository controls` les commandes exactes :

```text
python scripts/tests/test-trusted-human-review.py
python scripts/tests/test-trusted-human-review-github.py
python scripts/tests/test-trusted-human-review-workflow.py
```

Exiger les trois mêmes cibles dans `ci-local.sh` et vérifier que le workflow
privilégié ne produit aucun des six noms de jobs CI.

- [ ] **Step 2: Vérifier RED**

Run:

```bash
bash scripts/tests/test-ci-local-topology.sh
bash scripts/tests/test-ci-local-failsafe.sh
```

Expected: commandes obligatoires absentes.

- [ ] **Step 3: Ajouter les commandes CI**

Ajouter les trois tests au job `repository-controls` et trois `run_target`
distincts dans `ci-local.sh`, sans `||`, `continue-on-error` ni fallback.

- [ ] **Step 4: Vérifier GREEN**

Run:

```bash
bash scripts/tests/test-ci-local-topology.sh
YAML_PYTHON_BIN=python bash scripts/tests/test-ci-local-failsafe.sh
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml scripts/ci-local.sh \
  scripts/tests/test-ci-local-topology.sh \
  scripts/tests/test-ci-local-failsafe.sh
git commit -m "ci: rend la preuve humaine obligatoire"
```

### Task 8: Documenter la frontière et le verdict

**Files:**
- Create: `docs/adr/ADR-0025-autorite-revue-humaine-github.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/reports/lot_41v_trusted_human_review.md`

- [ ] **Step 1: Rédiger l'ADR**

Documenter : décision, contexte, alternatives rejetées, sécurité de
`pull_request_target`, absence d'exécution du head, challenge, révocation,
transition en deux temps et dépendance humaine irréductible.

- [ ] **Step 2: Mettre à jour la roadmap**

Ajouter ADR-0025 et préciser que LOT41V installe l'autorité GitHub mais ne
constitue ni LOT41A ni LOT42.

- [ ] **Step 3: Créer le rapport de lot**

Le rapport contient : objectifs, fichiers, cycles RED/GREEN, résultats ciblés,
SHA de base, rôle de `abenrhouma`, limites, procédure d'application live et
verdict explicite :

```text
LOT41V: READY_FOR_HUMAN_REVIEW
GO_LIVE: NO_GO
```

- [ ] **Step 4: Vérifier la documentation**

Run:

```bash
git diff --check
bash scripts/check-repository-hygiene.sh
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/ADR-0025-autorite-revue-humaine-github.md \
  docs/ROADMAP.md docs/reports/lot_41v_trusted_human_review.md
git commit -m "docs: consigne l'autorité GitHub LOT41V"
```

### Task 9: Vérification exhaustive du head

**Files:**
- Modify: `docs/reports/lot_41v_trusted_human_review.md` only if results need recording.

- [ ] **Step 1: Exécuter tous les tests ciblés**

```bash
python scripts/tests/test-main-protection-policy.py
python scripts/tests/test-trusted-human-review.py
python scripts/tests/test-trusted-human-review-github.py
python scripts/tests/test-trusted-human-review-workflow.py
bash scripts/tests/test-ci-local-topology.sh
YAML_PYTHON_BIN=python bash scripts/tests/test-ci-local-failsafe.sh
```

Expected: tous verts.

- [ ] **Step 2: Exécuter la CI locale exhaustive**

Run:

```bash
bash scripts/ci-local.sh
```

Expected: toutes les cibles réussissent, y compris PostgreSQL réel et deux
builds Cockpit.

- [ ] **Step 3: Rechercher les secrets et les défauts de diff**

Run:

```bash
gitleaks git --log-opts="origin/main..HEAD" --redact --no-banner
git diff --check origin/main...HEAD
git status --short --branch
```

Expected: aucun secret, diff propre, seulement les changements LOT41V.

- [ ] **Step 4: Consigner les résultats sans prétendre certifier son propre commit**

Mettre à jour le rapport avec les commandes, résultats et SHA réellement
testé. Expliquer que le commit documentaire suivant exige un nouveau contrôle
ciblé et que la preuve GitHub finale porte sur le head distant exact.

- [ ] **Step 5: Commit**

```bash
git add docs/reports/lot_41v_trusted_human_review.md
git commit -m "docs: consigne les preuves finales LOT41V"
```

## Chunk 5: GitHub, approbation et activation

### Task 10: Publier la PR et demander la décision indépendante

**Files:**
- No additional repository files unless review reveals a defect.

- [ ] **Step 1: Pousser la branche exacte**

```bash
git push -u origin lot-41v-trusted-human-review
```

- [ ] **Step 2: Créer la PR**

Créer une PR vers `main` avec le verdict `GO_LIVE: NO_GO`, les tests, la
chronologie d'activation et l'acte humain attendu.

- [ ] **Step 3: Demander formellement la review**

```bash
gh pr edit <PR> --add-reviewer abenrhouma
```

Calculer le challenge exact du head distant avec l'adaptateur en mode read-only
et le publier dans un commentaire. Demander à `abenrhouma` de soumettre une
review GitHub `APPROVED` dont une ligne est exactement ce challenge.

- [ ] **Step 4: Attendre sans imiter le reviewer**

Ne jamais approuver avec le compte propriétaire, modifier la review de
`abenrhouma` ni traiter un commentaire `LGTM` comme une approbation. Surveiller
jusqu'à une review formelle ou signaler l'attente.

- [ ] **Step 5: Vérifier le readback exact**

Après approbation :

```bash
python scripts/github/trusted_human_review_github.py \
  --repository cyranoaladin/RAG \
  --pull-request <PR> \
  --expected-head <HEAD> \
  --check
```

Expected: `approved=true`, reviewer `abenrhouma`, review commit et head égaux.

- [ ] **Step 6: Finaliser les revues automatisées**

Exiger les six checks, GitGuardian, Cubic et une revue Codex sur le head exact.
Répondre puis résoudre seulement les fils effectivement corrigés. Ne pousser
aucun commit après l'approbation sans demander une nouvelle approbation.

### Task 11: Fusionner puis appliquer la protection live

**Files:**
- No repository files changed.

- [ ] **Step 1: Fusionner sans bypass**

Fusionner la PR par squash uniquement lorsque le head, l'approbation et les
checks sont exacts et tous les fils résolus.

- [ ] **Step 2: Vérifier le run post-fusion**

Attendre le run `push` du commit de fusion exact et exiger les six jobs verts.

- [ ] **Step 3: Appliquer la politique cible avec confirmation liée au SHA**

```bash
merge_sha=$(gh pr view <PR> --json mergeCommit --jq .mergeCommit.oid)
NEXUS_CONFIRM_MAIN_PROTECTION="cyranoaladin/RAG@$merge_sha" \
  python scripts/github/main_protection.py \
    --repository cyranoaladin/RAG \
    --apply \
    --expected-main-sha "$merge_sha"
```

Expected: application puis readback exact dans la même commande.

- [ ] **Step 4: Relire indépendamment la protection**

```bash
python scripts/github/main_protection.py \
  --repository cyranoaladin/RAG \
  --check
```

Expected: politique exacte, sept contextes, une approbation, stale/code
owner/last push activés, aucun bypass.

- [ ] **Step 5: Prover le workflow sur une PR témoin non destructive**

LOT41A sera la première vraie PR protégée. Avant toute autorisation métier,
vérifier que son head reçoit `trusted-human-review=pending`, que seul le
challenge approuvé par `abenrhouma` le fait passer à `success`, et qu'un nouveau
push l'invalide.

- [ ] **Step 6: Handoff au lot suivant**

Conserver `GO_LIVE: NO_GO`. Démarrer LOT41A dans une nouvelle branche et un
nouveau worktree, sans réutiliser la branche LOT41V.
