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

## 6. Booléens finaux

```
H2_EVIDENCE_WORKFLOW_PATHS_FIXED=true
H2_EVIDENCE_WORKFLOW_FORBIDDEN_PRODUCTION_ARGS_REMOVED=true
H2_EVIDENCE_WORKFLOW_PATH_REGRESSION_TESTS_ADDED=true
H2_EVIDENCE_WORKFLOW_MUTATION_TESTED=true
H2_EVIDENCE_WORKFLOW_END_TO_END_REHEARSAL_BUILT=false
H2_EVIDENCE_WORKFLOW_RUNNABLE_AGAINST_REAL_CAMPAIGN=unknown   # aucune vraie campagne n'existe encore pour le vérifier
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
