# LOT — Correction du workflow producteur de preuve H2 (`_produce-h2-evidence.yml`)

## 1. Verdict

`.github/workflows/_produce-h2-evidence.yml` référençait des chemins qui
n'ont jamais existé dans ce dépôt, cassé depuis son introduction (même
commit que les fichiers réels, différemment nommés, PR #95) —
`gh run list --workflow="_produce-h2-evidence.yml"` : **0 exécution,
jamais**. Corrigé pour référencer les fichiers réellement committés, et
pour respecter un refus déjà codé dans le producteur réel qui n'était pas
qu'un problème de nommage. Garde-fou de non-régression ajouté :
13 tests structurels qui parsent le YAML et confrontent chaque chemin
littéral à l'arbre réel du dépôt, mutation-testés (7/13 échouent pour la
bonne raison contre l'ancienne version cassée).

`GO_LIVE_READY` reste `false`. Aucune mutation live. Ce lot ne crée
aucune campagne, autorisation ou liaison de revue réelle — ces
répertoires (`governance/authorizations/`, `governance/review-bindings/`,
`governance/revocations/`, `governance/corpus-campaigns/`) restent vides,
comme déjà défini dans `corpus_campaign.py` (`AUTHORIZATIONS_DIR`,
`CAMPAIGNS_DIR`) — leur peuplement pour une vraie campagne de production
est un processus de gouvernance distinct, hors périmètre de ce lot.

## 2. Défauts réels trouvés et corrigés

1. **Trois noms de fichiers de configuration erronés** (mécaniques,
   jamais un renommage after-the-fact — `git log` confirme que le
   workflow et les fichiers réels ont été introduits dans le même commit
   `2182339`) :
   - `services/rag-pedago/configs/rights_registry.yml` →
     `rights_evidence_registry.yml` (fichier réel).
   - `services/rag-pedago/configs/pii_policy.yml` →
     `pii_gate_policy.yml`.
   - `services/rag-pedago/configs/golden_controls.yml` →
     `golden_corpus_h2b.yml`.
2. **Un défaut plus profond qu'un nom de fichier** :
   `--authority-trust-anchor governance/trust-anchors/production-v1.json`
   et `--authority-revocations governance/revocations/registry.json`
   n'auraient jamais dû être passés du tout. Le vrai producteur
   (`h2b_coverage_report.py`, `_resolve_trust_anchor_path`/`_load_
   revoked_authorization_ids`) **refuse explicitement** ces deux
   arguments en `--authority-environment production`
   (`TRUST_ANCHOR_ARGUMENT_FORBIDDEN`/`REVOCATION_REGISTRY_ARGUMENT_
   FORBIDDEN` — documenté dans son propre `--help`) : en production, le
   gate lit ces deux preuves **lui-même**, aux chemins gouvernés
   `governance/trust-anchors/review-binding-v1.json` et
   `governance/trust-anchors/authorization-revocations-v1.json` (les
   deux existent déjà, committés). Un opérateur ne peut pas désigner sa
   propre ancre de confiance ou son propre registre de révocation en
   production — corriger seulement le nom de fichier aurait laissé le
   gate échouer à coup sûr à la première exécution réelle. Ces deux
   arguments sont retirés purement et simplement de l'appel du gate ;
   l'étape d'assemblage du bundle de preuve (`rag_pedago.governance.cli
   h2-evidence`) hache désormais ces deux mêmes fichiers gouvernés
   (`review-binding-v1.json`/`authorization-revocations-v1.json`) au
   lieu des chemins fictifs précédents, pour que la preuve enregistre le
   digest de ce qui a été **réellement** consulté par le gate.

## 3. Ce qui reste correct sans modification

- `--authority governance/authorizations/${CAMPAIGN_ID}.json` et
  `--authority-review-binding governance/review-bindings/${CAMPAIGN_ID}.json`
  restent des chemins par campagne légitimes — `corpus_campaign.py`
  définit déjà `AUTHORIZATIONS_DIR = "governance/authorizations"` comme
  racine canonique. Ces répertoires n'existent simplement pas encore
  faute d'une vraie campagne créée — non fabriqué ici (voir §5).
- Les trois actions (`actions/checkout`, `actions/setup-python`,
  `actions/upload-artifact`) étaient déjà épinglées par SHA de commit
  40-hex — vérifié, aucun changement nécessaire.
- La structure `workflow_call` uniquement, l'Environment `production`
  protégé, l'absence de toute clé privée dans ce workflow (il
  *constate*, ne signe jamais) — tous vérifiés inchangés et corrects.

## 4. Garde-fou de non-régression

`services/rag-pedago/tests/test_h2_evidence_workflow_paths.py` — 13 tests,
zéro accès réseau/GHCR :

- YAML valide, `workflow_call` uniquement.
- Chaque chemin littéral (non interpolé par `${...}`) suivant
  `--routing`/`--rights`/`--pii`/`--golden`/`--config` existe réellement
  sur disque.
- Chaque chemin littéral suivant `sha256sum` existe réellement sur disque.
- `--authority-trust-anchor`/`--authority-revocations` n'apparaissent
  **jamais** dans un step `run:` réel (regression guard exact sur le
  second défaut, §2.2).
- Le bundle de preuve hache bien les deux fichiers gouvernés réels.
- Les trois actions `uses:` restent épinglées par SHA 40-hex.
- Aucune référence à une clé privée/de signature, même par nom.

```
$ .venv/bin/python -m pytest tests/test_h2_evidence_workflow_paths.py -v
13 passed

$ .venv/bin/python -m ruff check tests/test_h2_evidence_workflow_paths.py
All checks passed!

$ .venv/bin/python -m mypy tests/test_h2_evidence_workflow_paths.py
Success: no issues found in 1 source file
```

**Mutation-testing** : le fichier workflow corrigé a été temporairement
remplacé par sa version d'avant ce lot (les quatre chemins erronés et les
deux arguments interdits), tests relancés :

```
7 failed, 6 passed
```

Les 7 échecs correspondent exactement aux deux classes de défaut
corrigées (3× chemin de config erroné, 1× sha256sum sur chemin erroné,
2× argument interdit présent, 1× bundle référençant un chemin fictif) —
jamais un échec pour une autre raison. Fichier restauré, suite revérifiée
verte (13/13).

## 5. Ce que ce lot ne fait pas — limite honnête, pas silencieuse

- **Aucune exécution réelle de bout en bout** (`resolve-corpus` exige un
  vrai pull OCI/GHCR d'un corpus scellé réel via `oras` — hors de portée
  d'un test local sans réseau ni artefact GHCR réel).
- **Aucune fixture de campagne/autorisation/liaison-de-revue synthétique
  n'a été construite** pour exercer les étapes 4 à 7 (catalogue, vue de
  revue, gate H2, assemblage du bundle) de bout en bout contre des
  données de test. C'était une des propriétés minimales demandées
  (« tests du workflow local/topology ») et ce lot ne la satisfait que
  partiellement : les tests ajoutés prouvent le **câblage statique**
  (chemins, refus d'arguments interdits, épinglage d'actions), pas
  l'**exécution réelle des étapes shell/Python** du job. Construire un
  harnais de répétition complet (corpus factice, campagne factice,
  autorisation factice, TSV factice cohérent avec §21 du mandat sur le
  compilateur de catalogue) est un travail substantiel et distinct —
  comparable en ampleur à `h2c_governed_rehearsal.py`/
  `h2e_materialize_rehearsal_inputs.py` déjà existants pour d'autres
  campagnes — non tenté ici pour rester dans le périmètre du bug
  confirmé et corrigé. Recommandé comme lot de suivi explicite.
- **`actionlint` n'était pas disponible** dans cet environnement — la
  validation s'appuie sur `yaml.safe_load` plus les tests structurels
  ci-dessus, pas sur un linter GitHub Actions dédié.
- Aucune campagne/autorisation/liaison de revue réelle n'a été créée —
  processus de gouvernance distinct (voir §1).

## 6. Rehearsal end-to-end réel (suivi, round 2)

`services/rag-pedago/tests/test_h2_evidence_e2e_rehearsal.py` (9 tests)
exécute les vrais producteurs Python de la chaîne H2 — jamais
réimplémentés — contre un corpus scellé synthétique sûr. Aucune clé
privée réelle, aucun accès réseau réel.

**Défaut structurel réel trouvé en construisant ce rehearsal, signalé,
pas contourné** : `corpus_catalog_compiler.compile_sealed_catalog`/
`compile_governed_sealed_catalog` ne peuvent **jamais** produire
`disposition="INGEST"` pour un objet — même droits et PII au vert, la
disposition finale reste `REVIEW_REQUIRED` (`gate_statuses.authority`
toujours `"BLOCKED_NOT_CLEARED"`), par construction explicite du
compilateur candidat (« L'autorité n'est jamais injectée dans ce
compilateur candidat »). Or `h2b_coverage_report.generate_coverage_
report`'s boucle de vérification des invariants de sûreté ne s'exécute
que pour les objets dont `disposition == "INGEST"` (jamais
`base_disposition`) — confirmé en lisant le code puis en l'exécutant
réellement (`test_real_catalog_compiler_never_promotes_a_candidate_to_
ingest`, `test_gate_correctly_blocks_the_real_compilers_honest_
output`). **Conséquence : aucun objet compilé par le vrai compilateur
candidat ne peut jamais atteindre `h2_coverage_gate_pass=True`, même en
mode production avec une autorité et une liaison de revue entièrement
valides.** Il manque, dans ce dépôt, une étape automatisée réelle de
« republication gouvernée » qui consommerait un catalogue candidat + une
autorité vérifiée pour produire un catalogue où `disposition="INGEST"`
— cette étape n'existe pas encore. `h2b_coverage_report.py`'s propre
suite de tests le contournait déjà en écrivant à la main un catalogue
qui simule cette sortie future (`_write_real_catalog`) ; ce rehearsal
documente pourquoi, et prouve séparément (Part A) que l'incapacité
structurelle du vrai compilateur est correctement **détectée et
bloquée** par le gate plutôt que silencieusement ignorée. Construire
cette étape manquante est un lot distinct, non tenté ici.

**Ce qui est prouvé, pour de vrai, en mode production (jamais
rehearsal — le mode `rehearsal` ne peut par construction jamais rendre
`coverage_complete=True`, ADR-0035), via la technique déjà établie et
revue de substitution de racine gouvernée en test
(`_install_governed_root`, qui remplace `_GOVERNED_REPOSITORY_ROOT` en
mémoire par une racine locale portant une ancre/un registre de test —
jamais une clé de production réelle, jamais une action réservée à un
opérateur) :**

```
H2_EVIDENCE_WORKFLOW_E2E_REHEARSAL=true        -- chaîne complète, producteurs réels, catalogue-shape "post-republication" (voir constat ci-dessus)
H2_GATE_PASS_ARTIFACT_PRODUCED=true            -- coverage_complete=True obtenu pour de vrai (mode production, clé de test locale)
H2_JSON_PARSE_CANONICAL=true                   -- report_to_h2_coverage_evidence + parse_h2_coverage_evidence, aller-retour octet-identique
H2_WRONG_MANIFEST_REFUSED=true                 -- refus dur (ValueError), jamais un rapport dégradé
H2_WRONG_AUTHORITY_REFUSED=true                -- SEMANTIC_VALIDATION failed, autorité ne couvrant pas le contenu
H2_REVOKED_AUTHORITY_REFUSED=true              -- registre de révocation réel (nexus_contracts.authorization_revocations)
H2_PII_FAILURE_REFUSED=true                    -- preuve PII et catalogue cohérents, tous deux "non blanchi"
H2_RIGHTS_FAILURE_REFUSED=true                 -- même discipline côté droits
```

```
$ cd services/rag-pedago && PYTHONPATH=$(pwd):$PYTHONPATH .venv/bin/python -m pytest \
    tests/test_h2_evidence_e2e_rehearsal.py -v
9 passed

$ PYTHONPATH=$(pwd):$PYTHONPATH .venv/bin/python -m pytest \
    tests/test_h2b_coverage_report.py tests/test_corpus_catalog_compiler.py \
    tests/test_h2_evidence_e2e_rehearsal.py -q
149 passed

$ .venv/bin/python -m ruff check tests/test_h2_evidence_e2e_rehearsal.py
All checks passed!

$ .venv/bin/python -m mypy tests/test_h2_evidence_e2e_rehearsal.py
Success: no issues found in 1 source file
```

Chaque scénario a exigé un diagnostic réel avant de passer (documenté en
commentaire dans le fichier de test lui-même) : un premier essai de
dictionnaires droits/PII construits à la main a été refusé par une
revérification interne du compilateur (`verify_catalog_evidence_
bindings`, un vrai croisement catalogue-vs-preuve, pas un artefact du
test) ; un premier essai de falsifier directement `gate_statuses` dans
le catalogue pour simuler un échec PII/droits a été refusé pour une
raison différente (« catalog PII/rights gate evidence mismatch » — la
détection de falsification elle-même, un constat positif inattendu,
pas la panne visée) et corrigé en rendant catalogue et preuve
cohérents plutôt qu'en les faisant diverger.

## 7. Booléens finaux

```
H2_EVIDENCE_WORKFLOW_PATHS_FIXED=true
H2_EVIDENCE_WORKFLOW_FORBIDDEN_PRODUCTION_ARGS_REMOVED=true
H2_EVIDENCE_WORKFLOW_PATH_REGRESSION_TESTS_ADDED=true
H2_EVIDENCE_WORKFLOW_MUTATION_TESTED=true
H2_EVIDENCE_WORKFLOW_END_TO_END_REHEARSAL_BUILT=true
H2_EVIDENCE_WORKFLOW_RUNNABLE_AGAINST_REAL_CAMPAIGN=unknown   # aucune vraie campagne n'existe encore pour le vérifier ; le mécanisme lui-même est prouvé (§6)
GOVERNED_REPUBLISH_STEP_EXISTS=false   # constat structurel réel, §6 -- lot distinct requis avant qu'un vrai catalogue candidat puisse jamais atteindre INGEST
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
