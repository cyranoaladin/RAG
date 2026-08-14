# LOT H2-B — Outil de signature du ProductionReadinessManifest

## 1. Verdict du lot

**`PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=true`** (voir §6quinquies).
Les deux gaps qui bloquaient ce lot depuis son introduction — l'image
applicative sans chaîne de provenance vérifiable, et
`catalog`/`sealed_manifest`/`h2b_report` simplement hachés sans jamais
être resémantiquement revérifiés — sont fermés en consommant deux lots
désormais mergés sur `main` : PR #102 (provenance d'image, ADR-0036
phase B) et PR #104 (`NEXUS-H2-COVERAGE-EVIDENCE-V1` + registre de
révocation strict partagé, ADR-0042, accepté par PR #106). Neuf
garde-fous distincts sont réellement en place et mutation-testés :
review-binding vérifié (ADR-0035), `--output` ne peut plus aliaser une
entrée de signature, faits Git vérifiés en direct, provenance workflow
vérifiée de même, images de déploiement confrontées au Compose
réellement haché, images applicatives dérivées d'une provenance
vérifiée (jamais une saisie opérateur), rapport H2-B parsé et son gate
exigé passant, quatre liaisons croisées entre l'autorisation/l'autorité/
le catalogue/le manifeste scellé et la preuve H2, et registre de
révocation analysé par le parseur strict partagé. **Aucun manifeste de
production réel n'a été signé** — l'outil n'a pas encore été exercé
contre les vrais fichiers d'evidence de production (§7). `GO_LIVE_READY`
reste `false`. Aucune mutation live.

## 2. Ce que fait l'outil

`services/rag-engine/scripts/sign_production_readiness_manifest_cli.py`
assemble un `ProductionReadinessManifestV1` (26 champs, contrat réel de
`packages/contracts/src/nexus_contracts/production_readiness.py`) depuis
des arguments CLI explicites et typés, le signe Ed25519, puis **revérifie
immédiatement** la signature produite contre l'ancre publique avant
d'écrire quoi que ce soit sur disque.

## 3. Ce qu'il refuse structurellement

- **Aucun booléen libre.** Il n'existe pas de `--ready true`. Chaque fait
  est soit un chemin de fichier que l'outil relit et rehash lui-même
  (`review_binding_digest`, `authorization_digest`, `trust_anchor_digest`,
  `revocation_registry_digest`, `catalog_digest`, `sealed_manifest_digest`,
  `h2b_report_digest`, `compose_digest`), soit une valeur dont le format
  est strictement validé (SHA Git 40-hex, digest OCI `name@sha256:...`).
- **Image applicative jamais une saisie opérateur.** L'ancien
  `--application-image name=ref@sha256:...` est retiré (§6quinquies) :
  les digests `ingestor`/workers sont dérivés d'un run GitHub Actions de
  provenance réel et vérifié (`--provenance-run-id`/`--provenance-run-
  attempt`, ancré sur `merge_sha`), jamais affirmés.
- **Tree SHA jamais un argument opérateur.** `pr_head_tree_sha` et
  `merge_tree_sha` ne sont plus des `--flags` du tout (ils l'étaient dans la
  première version de ce lot, avec un bug réel — voir §6) : ils sont
  **dérivés** de la réponse de l'API GitHub réelle pour le commit
  correspondant, jamais affirmés.
- **Faits Git et de provenance workflow vérifiés en direct.** `pr_head_sha`/
  `merge_sha` sont confrontés à `repos/<repo>/pulls/<pr_number>` (PR
  réellement mergée, même `merge_commit_sha`, même `head.sha`, même
  repository des deux côtés — jamais un fork) ; `run_id`/`run_attempt`/
  `workflow_path`/`workflow_ref` sont confrontés à un run GitHub Actions
  réel de ce dépôt (§6quater).
- **Images de déploiement confrontées au Compose réellement haché.**
  `--application-image`/`--upstream-image` ne sont plus deux sources
  indépendantes de `--compose-file` : le même fichier compte ses services
  pilotés par `image:` (upstream) et par `build:` (application), et exige
  un ensemble de services identique, avec digest byte-identique côté
  upstream (§6quater).
- **Clé privée jamais journalisée, jamais en argument.** Lue depuis
  `--private-key-file` uniquement ; la variable est explicitement écrasée
  (`"0" * len(...)`) avant toute écriture disque.
- **Revérification obligatoire avant écriture.** Si la vérification contre
  l'ancre publique échoue (mauvaise clé, mauvais environnement), l'outil
  retourne 1 et **n'écrit aucun fichier de sortie** — prouvé par mutation
  (§6).

## 4. Ce que cet outil ne fait PAS (hors périmètre explicite)

- Ne construit ni ne pousse aucune image applicative — dérive seulement
  leurs digests d'un run de provenance déjà terminé (§6quinquies).
- Ne construit aucun des fichiers d'evidence qu'il consomme
  (`catalog.json`, `h2b_report.json`, etc.) — ceux-ci doivent exister au
  moment de l'appel, produits par leurs propres outils canoniques
  (`corpus_catalog_compiler.py`, `h2b_coverage_report.py`, ...).
  `catalog`/`sealed_manifest` restent des digests (leurs parseurs
  canoniques vivent dans `rag-pedago`, non importables ici, ADR-0001) ;
  `h2b_report` est désormais parsé et son verdict exigé (§6quinquies).
- N'active rien : signer un manifeste ne l'enregistre nulle part, ne
  démarre aucun worker.

## 5. Tests — résultats exacts

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests/test_sign_production_readiness_manifest_cli.py -v
49 passed in 0.48s

$ .venv/bin/python -m ruff check scripts/sign_production_readiness_manifest_cli.py \
    tests/test_sign_production_readiness_manifest_cli.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m mypy scripts/sign_production_readiness_manifest_cli.py
Success: no issues found in 1 source file

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source services/rag-engine/scripts/sign_production_readiness_manifest_cli.py --no-git
no leaks found
$ gitleaks detect --source services/rag-engine/tests/test_sign_production_readiness_manifest_cli.py --no-git
no leaks found
```

Couverture adversariale (49 tests, groupée) :

- **Manifeste et signature (base)** : manifeste complet valide + round-trip
  réel via `verify_production_readiness_manifest` ; permissions 0600 sur la
  sortie ; `pr_head_sha` mal formé refusé ; `pr_head_tree_sha` ≠
  `merge_tree_sha` refusé par le contrat (`_bindings_hold`, maintenant
  exercé via les réponses GitHub stubbées) ; tag d'image mutable refusé ;
  liste d'images vide refusée ; doublon de nom de service refusé ; fichier
  d'evidence absent refusé ; environnement non-production refusé dès
  `argparse` ; mauvaise clé de signature → revérification échoue ; clé
  `environment=test` jamais acceptée en production ; falsification
  post-signature (`run_id`) → signature invalidée ; échec de revérification
  → aucun fichier de sortie écrit.
- **Review-binding (`TestReviewBindingIsActuallyVerified`, 8 tests)** : reçu
  signé par une clé non reconnue → refusé ; reçu couvrant une autre
  autorisation → refusé ; auto-approbation (reviewer == author) → refusée ;
  reçu expiré → refusé ; autorisation hors de sa fenêtre de validité →
  refusée ; autorisation révoquée → refusée ; registre de révocation
  malformé → refusé.
- **`--output` (`TestOutputNeverAliasesAnInput`, 4 tests)** : égal à
  `--private-key-file` → refusé, clé locale intacte ; alias via lien
  symbolique → refusé ; chemin distinct → accepté ; passage complet par
  `main()` → aucune écriture.
- **Faits Git/workflow en direct (`TestGitAndWorkflowFactsAreLiveVerified`,
  9 tests)** : PR non mergée → refusée ; `merge_sha` ≠ `merge_commit_sha`
  réel → refusé ; `pr_head_sha` ≠ `head.sha` réel → refusé ; PR/fork d'un
  autre repository → refusée ; `workflow_path` ≠ chemin réel du run →
  refusé ; `workflow_ref` ≠ `head_branch` réel du run → refusé ;
  `run_attempt` qui ne correspond à aucune tentative réelle → refusé ;
  échec de transport GitHub → propagé, jamais avalé ; PR/run réels
  concordants → acceptés.
- **Compose/images (`TestComposeImageBindingIsEnforced` +
  `TestRealCommittedComposeFileParsesAsExpected`, 13 tests)** : images et
  Compose concordants → signature réussie ; digest upstream divergent →
  refusé ; service upstream omis (liste vide, puis liste non vide mais
  incomplète) → refusé ; service upstream inventé → refusé ; service
  application omis/inventé → refusé ; service compose sans `image:` ni
  `build:` → ignoré sans erreur ; valeur `image:` templatée (`${...}`) →
  refusée explicitement ; YAML de Compose malformé → refusé ; Compose sans
  clé `services` → refusé ; **tag Compose normalisé avant comparaison**
  (`name:tag@sha256:...` → `name@sha256:...`, jamais un assouplissement du
  contrat partagé) ; image Compose non pinnée par digest → refusée ; tag
  différent mais même digest → accepté (le tag n'est pas le fait vérifié) ;
  et, **contre la vraie racine du dépôt** (jamais une fixture synthétique) :
  `docker-compose.v2.yml` a réellement `ingestor` en `build:` et
  `{pgvector, prometheus}` en `image:` digest-pinné.

## 6. Discipline de vérification — deux bugs réels trouvés et corrigés pendant ce lot

**Bug 1 (dans l'outil) : `pr_head_tree_sha` substitué par `pr_head_sha`.**
Le premier jet assignait par erreur le SHA de commit à la place du SHA
d'arbre Git — exactement le genre de fait fabriqué que cet outil existe
pour empêcher. Corrigé avant tout commit : deux arguments CLI distincts et
obligatoires, jamais l'un dérivé de l'autre.

**Bug 2 (dans le test, pas dans l'outil) :**
`test_main_never_writes_output_when_verification_fails` construisait son
propre `argv` à la main sans jamais créer les fichiers d'evidence requis
— le test passait, mais parce que l'outil échouait plus tôt (fichier
introuvable), jamais parce que la revérification avait réellement été
exercée. Prouvé en pratique : une régression injectée délibérément (suppression
du bloc de revérification dans `main()`) faisait **toujours passer** ce
test tel qu'il était écrit à l'origine. Corrigé en réutilisant
`_base_args(tmp_path)` (qui crée réellement les fichiers) ; réinjection de
la même régression après correction → le test échoue bien
(`assert rc == 1` reçoit `0`, `MANIFEST_DIGEST=...` imprimé, fichier de
sortie effectivement écrit). Régression retirée, suite repassée verte
(13/13), diff confirmé identique à l'état pré-injection.

## 6bis. Codex — trois constats sur le diff initial, vérifiés en direct

Trois commentaires Codex sont arrivés après le premier push (`c4d5b60`) :

- **P1 — « Verify governance artifacts before signing them ».** Constat
  exact : l'outil se contentait de hacher `--review-binding-file` et
  `--authorization-file`, jamais de vérifier qu'ils décrivent une revue
  humaine réelle, non expirée, non révoquée, portant sur l'autorisation
  présentée. **Corrigé** dans le premier round de remédiation (`d136da5`) :
  voir §6ter.
- **P1 — « Bind the complete image inventory to the Compose file ».**
  Constat exact. **Corrigé dans un second round** (§6quater) après qu'une
  instruction humaine a explicitement refusé le verdict initial « hors
  périmètre » et exigé la remédiation dans ce même lot.
- **P2 — « Reject output paths that alias signing inputs ».** Constat
  exact : rien n'empêchait `--output` de désigner (y compris via lien
  symbolique) le même fichier que `--private-key-file`. **Corrigé** dans le
  premier round (`d136da5`).

## 6ter. Premier round de remédiation (`d136da5`) — review-binding et `--output`

`assemble_and_sign()` vérifie le reçu de revue avec le vérificateur
canonique d'ADR-0025/0035 (`verify_review_binding`,
`require_matches_authorization`, `require_challenge_is_bound` —
`packages/contracts`, aucune primitive réinventée), confronte
l'autorisation à sa fenêtre de validité, et la confronte au registre de
révocation (nouveau `--review-binding-trust-anchor-file`, requis).
`_reject_output_aliasing_an_input()` compare le chemin résolu de `--output`
à celui de chaque entrée avant tout traitement.

Chaque nouveau chemin de refus a été prouvé par mutation :

```
Mutation 1 : le bloc de vérification review-binding est remplacé par un
  raise inconditionnel.
  -> Les tests qui doivent réussir (manifeste valide, round-trip) échouent.
  -> Les tests qui attendent un message *différent* (fenêtre de validité,
     registre de révocation malformé) échouent aussi, avec le message de
     la mutation au lieu du leur -- preuve qu'ils exercent réellement leur
     propre chemin de code en temps normal, pas un chemin déjà mort.
  Mutation retirée, suite repassée verte.

Mutation 2 : l'appel à `_reject_output_aliasing_an_input(args)` est retiré
  de `main()`.
  -> `test_main_refuses_before_touching_any_file_when_output_aliases_the_key`
     échoue : `rc == 0` au lieu de `1`, et le manifeste est bien écrit
     par-dessus la graine de signature (`MANIFEST_DIGEST=...` imprimé).
  Mutation retirée, suite repassée verte.
```

## 6quater. Second round de remédiation — faits Git/workflow en direct et binding Compose/images

Une instruction humaine a bloqué le HUMAN GATE sur le premier round : le P1
Compose/images avait été signalé comme « hors périmètre » sans être
vérifié en profondeur. En le creusant réellement (lecture des fichiers
Compose réels du dépôt, pas déduction), trois choses non anticipées sont
apparues :

1. **Des fichiers Compose réels existent et sont commités**
   (`services/rag-engine/infra/docker-compose*.yml`) — l'affirmation
   initiale « aucun fichier Compose commité » du premier jet de ce rapport
   était fausse, corrigée ici.
2. **Les images upstream sont déjà pinnées par digest dans le fichier
   réel** (`pgvector/pgvector:pg16@sha256:...`,
   `prom/prometheus:v2.54.1@sha256:...` dans `docker-compose.v2.yml`),
   **sous forme `name:tag@sha256:...`** — alors que le contrat partagé
   (`ProductionReadinessManifestV1._image_digests_are_pinned`, jamais
   modifié ici) n'accepte que la forme sans tag `name@sha256:...`. Un
   premier essai de ce lot avait élargi la regex *du CLI* pour accepter un
   tag — **erreur retenue avant commit** : cela n'aurait fait qu'accepter
   un format que le contrat partagé aurait ensuite refusé à la
   construction du manifeste (`pydantic.ValidationError`, capturé par un
   test qui a réellement échoué). Corrigé différemment : le côté Compose
   est normalisé (tag retiré) avant comparaison ; le contrat et le format
   `--upstream-image`/`--application-image` restent inchangés — aucun
   changement de contrat silencieux (AGENTS.md).
3. **L'image applicative (`ingestor`, et par construction les deux workers
   de production `multilevel-worker-a/b-production`) est un service
   `build:`, jamais `image:`** — aucun digest n'existe avant qu'un pipeline
   ne construise et pousse cette image quelque part. `.github/workflows/`
   ne contient **aucun workflow de build/promotion/déploiement**
   aujourd'hui (seulement `ci.yml`, `trusted-human-review.yml`,
   `_produce-h2-evidence.yml`). Ce n'est donc pas un défaut de cet outil à
   corriger par un meilleur analyseur YAML : **l'infrastructure qui
   produirait un digest applicatif vérifiable n'existe pas encore.**

**Corrigé dans ce lot** (tractable sans nouvelle infrastructure) :

- **Faits Git en direct.** `pr_head_sha`/`merge_sha` ne sont plus
  seulement validés en format : `_verify_git_and_workflow_facts()`
  confronte la PR à l'API GitHub réelle (`repos/<repo>/pulls/<pr_number>`)
  — mergée, même `merge_commit_sha`, même `head.sha`, même repository des
  deux côtés (refuse un fork). `pr_head_tree_sha`/`merge_tree_sha` ne sont
  plus des arguments CLI : ils sont **dérivés** de
  `repos/<repo>/git/commits/<sha>` (`.tree.sha`), jamais affirmés.
  Sanity-check en direct contre PR #101 réellement mergée (pas seulement un
  test avec double) : `merged=true`, `merge_commit_sha`/`head.sha`
  concordent avec les valeurs déjà enregistrées dans
  `docs/reports/lot_h2b_accept_adr_0035.md`, `tree.sha` identique des deux
  côtés (squash merge, comme attendu).
- **Provenance workflow en direct.** `run_id`/`run_attempt`/
  `workflow_path`/`workflow_ref` confrontés à
  `repos/<repo>/actions/runs/<run_id>` (chemin réel, repository réel,
  `head_branch` réel) et `.../attempts/<run_attempt>` (l'existence de la
  réponse prouve que l'entier n'est pas inventé). Sanity-check en direct
  contre un run réel (`31695475756`, workflow `trusted-human-review.yml`) :
  concordance confirmée.
- **Binding Compose/images.** `_verify_image_bindings()` confronte
  `--application-image`/`--upstream-image` au fichier nommé par
  `--compose-file`, déjà haché dans le manifeste : ensemble de services
  identique des deux côtés (aucun omis, aucun inventé) pour les deux
  catégories ; pour les services `image:` (upstream), digest
  byte-identique après normalisation du tag. Un service sans `image:` ni
  `build:` est ignoré sans erreur. Une valeur `image:` templatée
  (`${...}`) est refusée explicitement plutôt que silencieusement mal
  interprétée — vérifié contre les fichiers Compose réellement commités :
  aucun ne template sa valeur `image:` aujourd'hui (`grep image:` sur les
  treize fichiers).
- **Transport GitHub.** `_github_api_get()` — seule frontière réseau de cet
  outil, isolée pour être substituée par un double en tests, jamais
  exercée contre le réseau réel dans la suite automatisée. Utilise `gh api`
  (même transport que `scripts/github/` et l'ensemble de cette mission),
  pas `httpx` : ce CLI tourne en contexte opérateur/CI où `gh` est
  disponible, contrairement à
  `ingestor.ingestion_control.github_authority` (construit spécifiquement
  pour l'image Docker minimale du worker, qui ne l'a pas) — réutilisation,
  pas un second protocole (AGENTS.md, instruction humaine §10).

**Non corrigé — gap réel, signalé, pas contourné :**

- **Provenance de l'image applicative.** `--application-image` reste une
  affirmation opérateur pour les services `build:`. La remédier exige un
  pipeline CI/CD qui construit et pousse ces images avec un digest
  vérifiable — infrastructure qui n'existe pas dans ce dépôt aujourd'hui.
  Nécessite un lot dépendant avec sa propre décision de conception (quel
  registre, quel déclencheur de promotion, quel format d'attestation) et
  son propre rapport ; ne peut pas être fait « en passant » dans ce lot
  signing-tool sans deviner ces décisions.
- **Vérification sémantique de `catalog`/`sealed_manifest`/`h2b_report`.**
  Toujours seulement hachés, jamais reparsés contre leurs outils canoniques
  respectifs (`corpus_catalog_compiler.py`, gate H2-B). `gate_result`
  reste une constante `Literal["pass"]` du contrat (jamais un booléen libre
  côté CLI — structurellement impossible à injecter — mais pas non plus
  une conséquence vérifiée de ce que ces fichiers attestent réellement).
- **Registre de révocation via un parseur local minimal**, pas le parseur
  canonique complet de `h2b_coverage_report.py` (non importable ici,
  service différent). Suffisant pour la question posée (« cette
  autorisation est-elle révoquée ? »), pas pour toute la discipline de
  validation du fichier lui-même (unicité, champs inconnus).

**Chaque nouveau garde-fous prouvé par mutation** (le bloc de vérification
Git/workflow retiré → 8 des 9 tests dédiés échouent pour la raison
attendue ; l'appel à `_verify_image_bindings` retiré → 8 des 12 tests
dédiés échouent, les 4 restants continuant de tester un refus antérieur
non affecté par cette mutation, comme attendu). Suite repassée verte après
chaque retrait de mutation.

## 6quinquies. Intégration finale — PR #102/#104 consommées, les deux blockers fermés

Les deux blockers explicitement identifiés en §6quater/§7/§8
(`APPLICATION_IMAGE_PROVENANCE_VERIFIED=false`,
`GOVERNANCE_EVIDENCE_SEMANTICALLY_VERIFIED=false`) dépendaient tous deux
de lots qui n'existaient pas encore à l'époque. Les deux existent
maintenant, mergés sur `main` : PR #102 (provenance d'image, ADR-0036
phase B) et PR #104 (`NEXUS-H2-COVERAGE-EVIDENCE-V1` + registre de
révocation strict partagé, ADR-0042, accepté par PR #106). Ce round
rebase la branche sur `main` actuel et intègre réellement les deux.

**1. Images applicatives — plus une saisie opérateur.** L'ancien
`--application-image name=ref@sha256:...` (répété, affirmé par
l'opérateur, jamais vérifié) est retiré. `_derive_application_image_
digests()` appelle `deployment_image_inventory.verify_application_
image_provenance()` (PR #102) avec `--provenance-run-id`/
`--provenance-run-attempt`, ancrée sur `merge_sha`/`merge_tree_sha` — le
commit qui atterrit réellement sur `main`, jamais le head de PR avant
merge (les deux sont des constantes de test distinctes ; un test dédié,
`test_provenance_is_anchored_on_merge_sha_not_pr_head_sha`, le prouve,
et la mutation `source_commit_sha=merge_sha → pr_head_sha` fait
échouer deux tests pour la bonne raison — commit non reconnu par le run
de provenance). Le téléchargement d'artefact utilise `deployment_image_
inventory.make_download_artifact_via_gh(repository=...)` (PR #105,
liaison au dépôt vérifié, jamais dépendant du `cwd`).

**2. Rapport H2-B — parsé et son verdict exigé, plus un fichier
opaque.** `--h2b-report-file` était haché sans jamais être lu. Il est
maintenant parsé via `nexus_contracts.h2_coverage_evidence.parse_h2_
coverage_evidence()` (PR #104/ADR-0042), et `h2_coverage_gate_pass`
doit être vrai — un rapport dont le verdict est faux, ou dont les octets
ne sont pas canoniques, est refusé avant toute signature.

**3. Liaison croisée — quatre preuves qui ne pouvaient jusque-là jamais
diverger sans être détectées.** Un digest, seul, prouve qu'un fichier
n'a pas changé depuis sa lecture — jamais qu'il appartient à la même
campagne que les trois autres preuves signées dans le même manifeste.
Quatre croisements nouveaux, chacun mutation-testé (retrait individuel
→ le test dédié passe au rouge) :
- `h2_evidence.authorization_id == authorization.authorization_id`
- `h2_evidence.input_file_digests["authority"] == authorization_digest`
- `h2_evidence.input_file_digests["catalog"] == catalog_digest`
- `h2_evidence.manifest_sha256 == sealed_manifest_digest`

**4. Registre de révocation — parseur strict partagé, plus un parseur
local minimal.** L'ancien `_revoked_authorization_ids()` (parseur local
de ce fichier, documenté dès son introduction comme insuffisant — pas de
détection de doublon, entre autres) est retiré, remplacé par
`nexus_contracts.authorization_revocations.parse_revoked_authorization_
ids()` (PR #104, le même parseur que `rag-pedago`). Preuve d'amélioration
réelle, pas seulement cosmétique : un nouveau test
(`test_duplicate_revoked_id_is_refused`) prouve qu'un registre avec un
identifiant dupliqué — que l'ancien parseur local acceptait
silencieusement, faute de toute logique de détection — est désormais
refusé.

```
$ cd services/rag-engine && .venv/bin/python -m pytest \
    tests/test_sign_production_readiness_manifest_cli.py -v
60 passed

$ .venv/bin/python -m pytest \
    tests/test_sign_production_readiness_manifest_cli.py \
    tests/test_deployment_image_inventory.py \
    tests/test_verify_release_image_provenance_cli.py -q
124 passed

$ .venv/bin/python -m ruff check scripts/sign_production_readiness_manifest_cli.py \
    tests/test_sign_production_readiness_manifest_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/sign_production_readiness_manifest_cli.py
Success: no issues found in 1 source file

$ cd ../.. && bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).
```

Les sept nouveaux points de contrôle (dérivation de provenance ancrée
sur `merge_sha`, refus d'une provenance pour le mauvais commit, refus
d'un service manquant dans l'inventaire de provenance, refus d'un gate
H2-B faux, les quatre liaisons croisées, refus d'un registre de
révocation dupliqué) sont tous mutation-testés individuellement.

## 7. Limitations

- Aucune clé privée de production n'a été utilisée par cet outil dans ce
  lot — seulement des graines de test triviales (`"11"*32`, `"22"*32`,
  `"33"*32`).
- Aucun manifeste réel n'a été assemblé ni signé pour PR #97, #98, #99,
  #100 ou #101.
- L'outil n'a pas encore été exercé contre les vrais fichiers d'evidence
  de production (catalogue de disposition réel, rapport H2-B réel,
  registre de révocation réel, run de provenance d'image réel) — ceux-ci
  n'existent pas encore tant que PR #98 n'est pas enregistrée et que le
  workflow de provenance d'image n'a pas tourné pour de vrai sur `main`.

## 8. Booléens finaux

```
PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=true
FREE_FORM_READINESS_BOOLEAN_ALLOWED=false
SIGNED_MANIFEST_VERIFY_ROUNDTRIP=true
REVIEW_BINDING_ACTUALLY_VERIFIED_BEFORE_SIGNING=true
OUTPUT_PATH_CANNOT_ALIAS_A_SIGNING_INPUT=true
GIT_FACTS_VERIFIED=true
WORKFLOW_PROVENANCE_VERIFIED=true
UPSTREAM_COMPOSE_IMAGE_CROSS_BINDING=true
APPLICATION_IMAGE_PROVENANCE_MECHANISM_VERIFIED=true   # mécanisme livré/testé ; jamais exécuté contre un run de provenance réel (§7)
GOVERNANCE_EVIDENCE_SEMANTICALLY_VERIFIED=true
REVOCATION_REGISTRY_STRICTLY_VERIFIED=true
CATALOG_SEALED_BINDING_VERIFIED=true
H2_GATE_RESULT_DERIVED_PASS=true
PRODUCTION_MANIFEST_SIGNED=false   # aucun manifeste réel signé dans ce lot (§7)
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
