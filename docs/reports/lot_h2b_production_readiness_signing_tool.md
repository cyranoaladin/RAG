# LOT H2-B — Outil de signature du ProductionReadinessManifest

## 1. Verdict du lot

**Toujours `PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=false`.**
Un précédent commit de ce rapport a affirmé `true` à tort — corrigé ici
après un audit plus approfondi (§6sexies) qui a trouvé un blocker réel
non fermé, plus cinq défauts réels distincts corrigés. Ce que ce lot
ferme réellement (§6quinquies/§6sexies) : image applicative dérivée
d'une provenance GitHub Actions vérifiée (PR #102) au lieu d'une saisie
opérateur ; les six `input_file_digests` du rapport H2-B
(`catalog`/`routing`/`rights`/`pii`/`golden`/`authority`) confrontés
chacun à un fichier réel, plus le rapport lui-même sémantiquement
vérifié (`h2_coverage_gate_pass` exigé vrai) et lié par commit/digest à
l'autorisation, au manifeste scellé et au commit signés ; registre de
révocation analysé par le parseur strict partagé (ADR-0042) ; dépôt
GitHub épinglé (`_TRUSTED_REPOSITORY`, jamais un `--repository`
opérateur) ; lien physique (`hardlink`) désormais détecté par
`--output` ; documentation honnête sur l'absence de garantie
d'effacement mémoire de la clé privée. **Ce qui reste bloquant** :
`--workflow-path`/`--workflow-ref`/`--run-id`/`--run-attempt`
(provenance de l'émission du manifeste lui-même) désignent toujours un
workflow GitHub Actions **qui n'existe pas encore dans ce dépôt** —
`.github/workflows/` ne contient que `ci.yml`, `_produce-h2-evidence.
yml`, `production-image-provenance.yml`, `trusted-human-review.yml`,
aucun « workflow de promotion » au sens du contrat lui-même
(`production_readiness.py` : « le workflow de promotion, qui l'émet et
le signe »). Le fixture de test `promote.yml` était une fiction jamais
ancrée dans un fichier réel — corrigé dans les tests, mais le vrai
workflow reste à construire comme lot séparé avant que ce champ puisse
être épinglé (§6sexies). Le Compose analysé reste un unique fichier
source (§6sexies), pas le Compose résolu final de la topologie de
production réelle. **Aucun manifeste de production réel n'a été signé.**
`GO_LIVE_READY` reste `false`. Aucune mutation live.

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

## 6sexies. Sixième round — audit approfondi, un blocker réel non fermé trouvé

Un audit ligne par ligne du diff complet, mené avant de déclarer ce lot
terminé, a trouvé six défauts réels — cinq corrigés, un identifié comme
un vrai blocker externe :

1. **`--repository` restait une entrée opérateur** (même classe de
   défaut déjà corrigée dans PR #105) — un opérateur pouvait fournir un
   autre dépôt puis faire vérifier PR/run/workflow/provenance contre ce
   dépôt alternatif. Retiré, remplacé par `_TRUSTED_REPOSITORY =
   "cyranoaladin/RAG"`, une constante du module.
2. **La provenance du workflow de promotion était incomplète.**
   `_verify_git_and_workflow_facts` confrontait `path`/`repository`/
   `head_branch`, mais jamais `status`/`conclusion` (un run échoué ou en
   cours passait), jamais `head_sha` (un run bâti sur un autre commit
   passait), et appelait l'endpoint `/attempts/<n>` sans jamais exploiter
   sa réponse ni croiser `run_attempt` du run général (même bug, déjà
   trouvé et corrigé dans `deployment_image_inventory.py`, PR #102).
   Les quatre contrôles manquants sont ajoutés, reproduisant exactement
   le correctif déjà validé côté provenance d'image.
3. **Le rapport H2-B n'était pas lié au commit signé.** `h2_evidence.
   git_commit` (le commit sur lequel la campagne H2-B a réellement
   tourné) n'était jamais confronté à `--merge-sha`. Un rapport H2 PASS
   produit pour un tout autre commit aurait pu signer cette release.
   Corrigé.
4. **Quatre des six digests H2 n'étaient jamais confrontés à un fichier
   réel.** Seuls `catalog` et `authority` l'étaient ; `routing`/
   `rights`/`pii`/`golden` pouvaient porter un digest arbitraire dans un
   document H2 par ailleurs structurellement valide, sans jamais être
   détectés. Corrigé par quatre nouveaux arguments (`--routing-file`/
   `--rights-file`/`--pii-file`/`--golden-file`), chacun relu et
   rehaché puis confronté à sa clé correspondante dans `input_file_
   digests`.
5. **`Path.resolve()` ne détecte jamais un lien physique** (`ln`, pas
   `ln -s`) : deux entrées de répertoire vers le même inode, dont
   aucune n'est un « lien » que `resolve()` puisse suivre — chacune se
   résout vers elle-même. Le commentaire du code affirmait pourtant
   détecter ce cas. Corrigé par `os.path.samefile()` en complément
   (jamais en remplacement) du contrôle `resolve()` existant.
6. **`private_key_hex = "0" * len(...)` ne garantit aucun effacement
   mémoire réel** — réaffecter un nom Python à une nouvelle chaîne de
   zéros ne touche jamais la mémoire de l'original (chaînes immuables) ;
   le commentaire prétendait le contraire. `sign_production_readiness_
   manifest` (contrat partagé, `packages/contracts`, d'autres appelants)
   exige un `str` — changer sa signature pour un tampon mutable est hors
   périmètre de ce lot (Escalade AGENTS.md). Corrigé en documentant
   honnêtement l'absence de garantie plutôt qu'en la prétendant.

**Blocker réel identifié, pas fermé — signalé, pas contourné.**
`--workflow-path`/`--workflow-ref`/`--run-id`/`--run-attempt`
prétendent vérifier « le workflow de promotion » — mais aucun tel
workflow n'existe dans `.github/workflows/` de ce dépôt aujourd'hui
(vérifié : `ci.yml`, `_produce-h2-evidence.yml`, `production-image-
provenance.yml`, `trusted-human-review.yml`, aucun « promote.yml » ni
équivalent). Le fixture de test `WORKFLOW_PATH = ".github/workflows/
promote.yml"` était une fiction jamais ancrée dans un fichier réel du
dépôt — les tests continuent de fonctionner (ils stubbent l'API GitHub,
jamais un vrai fichier), mais cela masquait le fait qu'aucun opérateur
ne pourrait aujourd'hui fournir un `--workflow-path` réellement
canonique. Construire ce workflow de promotion est son propre lot,
distinct de celui-ci (même pattern que PR #102 pour la provenance
d'image) — non implémenté ici de ma propre initiative.

**Également non fermé, signalé au §1** : le Compose analysé
(`_compose_services`) reste un unique fichier source passé via
`--compose-file`, jamais le Compose résolu de la topologie de
production réelle (`docker-compose.v2.yml` +
`docker-compose.production-workers.yml` +
`docker-compose.production-release.yml`, résolution `docker compose ...
config`, comme PR #105/futur Lot C). Un seul fichier source ne peut pas
représenter simultanément les trois services applicatifs, `pgvector`,
`prometheus` et les variables résolues de la release réelle.

```
$ cd services/rag-engine && .venv/bin/python -m pytest \
    tests/test_sign_production_readiness_manifest_cli.py -v
72 passed

$ .venv/bin/python -m pytest \
    tests/test_sign_production_readiness_manifest_cli.py \
    tests/test_deployment_image_inventory.py \
    tests/test_verify_release_image_provenance_cli.py -q
136 passed

$ .venv/bin/python -m ruff check scripts/sign_production_readiness_manifest_cli.py \
    tests/test_sign_production_readiness_manifest_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/sign_production_readiness_manifest_cli.py
Success: no issues found in 1 source file

$ cd ../.. && bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).
```

Les onze nouveaux points de contrôle (dépôt épinglé, statut/conclusion/
head_sha/run_attempt du run de promotion, liaison git_commit, quatre
liaisons de digest routing/rights/pii/golden, détection de lien
physique) sont tous mutation-testés individuellement.

## 6septies. Section 11 — Compose résolu multi-fichiers, plus un fichier source unique

`--compose-file` (un seul fichier YAML source, jamais capable de
représenter la topologie de production réelle — sa propre docstring
l'admettait : « n'invoque jamais `docker compose config` ») est
supprimé. Remplacé par exactement le mécanisme déjà construit, testé et
utilisé par `verify_release_image_provenance_cli.py` (PR #105) :
`docker-compose.v2.yml` + `docker-compose.production-workers.yml` +
`docker-compose.production-release.yml`, lus depuis l'objet git
`merge_sha:services/rag-engine/infra/<fichier>` (jamais un disque qui
pourrait avoir divergé), résolus avec `docker compose --env-file
<env-file> config --format json`. Réutilisé par import
(`verify_release_image_provenance_cli.run_docker_compose_config_via_
subprocess`), jamais réimplémenté — même primitive, déjà exercée contre
un vrai `docker`/`git` par la suite de tests de PR #105.

**Nouveaux arguments CLI** : `--repo-root` (défaut : la racine réelle du
dépôt) et `--env-file` (requis — explicite, comme tous les autres faits
de cet outil, jamais un défaut implicite pour un fichier qui porte des
secrets de production).

**Ce que le Compose résolu change réellement** :

1. Les trois services applicatifs (`ingestor`,
   `multilevel-worker-a/b-production`) apparaissent maintenant, dans le
   Compose résolu réel, pleinement résolus par la release overlay
   (`!reset null` + `image:` épinglée) — plus jamais seulement des
   services à `build:`. `deployment_image_inventory.require_resolved_
   compose_images_are_pinned` (déjà écrite, déjà testée, jamais exercée
   avant ce lot par ce fichier) confronte cela : chaque service
   applicatif attendu existe, ne porte plus `build:`, son image est
   épinglée par digest.
2. **Renforcement réel, pas seulement un changement de source** : ce
   fichier ne confrontait auparavant que les NOMS des services
   applicatifs entre Compose et provenance (jamais leurs digests
   d'image). `verify_release_image_provenance_cli.require_pinned_
   images_match_verified_provenance` (réutilisée, jamais réimplémentée)
   ferme ce même défaut déjà trouvé et corrigé pour PR #105 round 2 : un
   digest correctement formé et épinglé, mais qui n'est pas celui produit
   par la provenance vérifiée pour ce commit exact, est maintenant
   refusé — `test_compose_application_image_diverging_from_provenance_
   is_refused`, mutation-testée (désactiver le croisement fait échouer
   ce test précisément, pour la bonne raison).
3. Les services upstream (ex. `pgvector`) sont dérivés du Compose résolu
   entier (`_upstream_services_from_resolved_compose`) : tout service qui
   n'est pas l'un des trois services applicatifs connus, et qui déclare
   une image épinglée par digest, en fait partie ; un service à `build:`
   inconnu (hors des trois attendus) est désormais refusé plutôt
   qu'ignoré — un Compose résolu de production ne devrait plus jamais en
   laisser passer un.
4. Plus besoin de normaliser un tag avant comparaison (`_COMPOSE_IMAGE_
   REF`, supprimée) : un Compose déjà résolu ne porte plus de tag pour
   une image déjà digest-pinnée côté source — `docker compose config` le
   retire lui-même.
5. `compose_digest`, le fait signé dans le manifeste, est maintenant le
   digest du Compose RÉSOLU (JSON canonique, clés triées) — pas d'un
   fichier source. C'est exactement ce que
   `nexus_contracts.production_readiness.require_manifest_matches_
   release` documente déjà pour ce champ (« le fichier compose résolu »,
   confronté par un futur vérificateur hôte qui résoudrait à nouveau les
   mêmes fichiers avec le même `.env`) — pas un changement de contrat,
   seulement la source réellement hachée qui s'aligne enfin sur ce que le
   contrat documentait déjà. Contrat partagé (`packages/contracts`) non
   modifié.

**Tests.** `TestComposeImageBindingIsEnforced` entièrement réécrite (13
scénarios contre le Compose résolu, via un nouveau double injecté
`tool._run_docker_compose_config`, autousé — même convention que
`_stub_github_api`/`_stub_download_artifact`). `TestRealCommittedCompose
FileParsesAsExpected` (qui exerçait l'ancien parseur local contre le
vrai `docker-compose.v2.yml`) est supprimée : la preuve contre de vrais
fichiers Compose et un vrai `docker`/`git` existe déjà, exercée par
`TestRunDockerComposeConfigViaSubprocess` dans `test_verify_release_
image_provenance_cli.py` — la redériver ici pour une fonction que ce
fichier ne fait qu'appeler aurait été une pure duplication (AGENTS.md,
DRY).

```
$ .venv/bin/python -m pytest tests/test_sign_production_readiness_manifest_cli.py -v
72 passed

$ .venv/bin/python -m pytest tests/test_sign_production_readiness_manifest_cli.py \
    tests/test_deployment_image_inventory.py tests/test_verify_release_image_provenance_cli.py -q
136 passed

$ .venv/bin/python -m ruff check scripts/sign_production_readiness_manifest_cli.py \
    tests/test_sign_production_readiness_manifest_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/sign_production_readiness_manifest_cli.py
Success: no issues found in 1 source file
```

Mutation-testées individuellement (désactivation ciblée → test rouge
pour la bonne raison → restauration → suite verte) : le croisement
digest applicatif/provenance (point 2 ci-dessus), le refus d'un service
à `build:` inconnu hors des trois attendus (point 3), le refus d'une
image upstream non épinglée par digest dans le Compose résolu.

**Ce qui reste ouvert.** Le workflow de promotion canonique n'existe
toujours pas (`.github/workflows/` : `ci.yml`, `_produce-h2-evidence.
yml`, `production-image-provenance.yml`, `trusted-human-review.yml`,
vérifié à nouveau à la fin de ce round — toujours aucun `promote.yml` ni
équivalent) — seul blocker restant pour
`PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE`, non fermable dans ce lot
(§6sexies, Escalade AGENTS.md : construire ce workflow est un lot
séparé).

## 7. Limitations

- Aucune clé privée de production n'a été utilisée par cet outil dans ce
  lot — seulement des graines de test triviales (`"11"*32`, `"22"*32`,
  `"33"*32`).
- Aucun manifeste réel n'a été assemblé ni signé pour PR #97, #98, #99,
  #100 ou #101.
- **Aucun workflow de promotion canonique n'existe encore** — voir
  §6sexies/§6septies. `--workflow-path`/`--workflow-ref`/`--run-id`/
  `--run-attempt` restent, de fait, des entrées opérateur non ancrées à
  un workflow pinné, faute d'un tel workflow dans ce dépôt. C'est
  aujourd'hui le SEUL blocker qui maintient
  `PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=false`.
- L'outil n'a pas encore été exercé contre les vrais fichiers d'evidence
  de production (catalogue de disposition réel, rapport H2-B réel,
  registre de révocation réel, run de provenance d'image réel, vrai
  `.env` de production) — ceux-ci n'existent pas encore tant que PR #98
  n'est pas enregistrée et que le workflow de provenance d'image n'a pas
  tourné pour de vrai sur `main`.

## 8. Booléens finaux

```
PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=false   # bloqué par le workflow de promotion manquant, §6sexies/§6septies
FREE_FORM_READINESS_BOOLEAN_ALLOWED=false
SIGNED_MANIFEST_VERIFY_ROUNDTRIP=true
REVIEW_BINDING_ACTUALLY_VERIFIED_BEFORE_SIGNING=true
OUTPUT_PATH_CANNOT_ALIAS_A_SIGNING_INPUT=true
REPOSITORY_PINNED=true
GIT_FACTS_VERIFIED=true
WORKFLOW_PROVENANCE_VERIFIED=false   # workflow canonique de promotion inexistant, §6sexies
UPSTREAM_COMPOSE_IMAGE_CROSS_BINDING=true
RESOLVED_COMPOSE_BINDING=true   # Section 11 : Compose résolu multi-fichiers, plus un fichier source unique
APPLICATION_IMAGE_PROVENANCE_MECHANISM_VERIFIED=true   # mécanisme livré/testé ; jamais exécuté contre un run de provenance réel (§7)
GOVERNANCE_EVIDENCE_SEMANTICALLY_VERIFIED=true
H2_INPUT_CATALOG_DIGEST_VERIFIED=true
H2_INPUT_ROUTING_DIGEST_VERIFIED=true
H2_INPUT_RIGHTS_DIGEST_VERIFIED=true
H2_INPUT_PII_DIGEST_VERIFIED=true
H2_INPUT_GOLDEN_DIGEST_VERIFIED=true
H2_INPUT_AUTHORITY_DIGEST_VERIFIED=true
REVOCATION_REGISTRY_STRICTLY_VERIFIED=true
CATALOG_SEALED_BINDING_VERIFIED=true
H2_GATE_RESULT_DERIVED_PASS=true
H2_GIT_COMMIT_BOUND_TO_MERGE_SHA=true
PRODUCTION_MANIFEST_SIGNED=false   # aucun manifeste réel signé dans ce lot (§7)
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
