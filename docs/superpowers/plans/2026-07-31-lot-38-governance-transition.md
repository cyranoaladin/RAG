# LOT38 — Dormant Validation Governance Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Versionner une politique de validation réelle strictement dormante pour le pilote `libre_terminale` Mathématiques + NSI, prouver ses refus fail-closed et laisser tous les verrous globaux à `false`.

**Architecture:** Le plan de contrôle `rag-pedago` possède deux documents canoniques séparés : un scope immuable, lié par SHA-256 aux deux taxonomies, et une politique de capacités/autorisation. Un évaluateur pur confronte le document LOT41A non fiable à une preuve GitHub indépendante, vérifie l'intégrité des octets du scope et de la politique, puis refuse tant que toutes les capacités nécessaires ne sont pas ouvertes. LOT38 ne fournit aucun exécuteur runtime : LOT41 devra raccorder `rag-engine` par contrat/API ou artefact signé, sans import cross-service, et LOT42 devra prouver ce raccordement ainsi que `quality → gate → review` avant toute publication.

**Tech Stack:** Python 3.11, Pydantic 2.13.4, PyYAML 6.0.3, pytest 9.1.1, Ruff, mypy, Make, GitHub Actions.

**Norme:** `docs/superpowers/specs/2026-07-31-pilot-go-live-finalization-design.md`, sections 3, 6, 7, 8, 9, 10.2, 12 et 13.

---

## Chunk 1: Scope et politique canoniques

### Task 1: Verrouiller le scope pilote et les taxonomies

**Files:**
- Create: `services/rag-pedago/configs/pilot_validation_scope.yml`
- Create: `services/rag-pedago/rag_pedago/governance/__init__.py`
- Create: `services/rag-pedago/rag_pedago/governance/pilot_validation.py`
- Create: `services/rag-pedago/tests/unit/test_pilot_validation_scope.py`

- [ ] **Step 1: Écrire le test RED du scope absent**

Créer un test qui charge `configs/pilot_validation_scope.yml` au moyen de l'API souhaitée et exige :

```python
def test_canonical_scope_is_exact_and_taxonomies_are_content_addressed() -> None:
    scope = load_scope(SCOPE_PATH)
    assert scope.scope_id == "libre_terminale_maths_nsi_real_v1"
    assert scope.status == "eligible_for_promotion"
    assert scope.identity.tenant == "libre_terminale"
    assert scope.identity.candidates == ("cned_libre", "individuel", "libre")
    assert tuple(sorted(scope.collections)) == (
        "rag_nexus_maths_terminale_gen_specialite",
        "rag_nexus_nsi_terminale_specialite",
    )
    assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == ()
    assert sum(len(subject.notions) for subject in scope.subjects) == 39
```

- [ ] **Step 2: Vérifier le RED**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_scope.py
```

Expected: FAIL parce que le fichier et le module LOT38 n'existent pas.

- [ ] **Step 3: Définir le document de scope minimal**

Le YAML doit contenir exactement :

```yaml
scope_id: libre_terminale_maths_nsi_real_v1
status: eligible_for_promotion
school_year: 2026-2027
identity:
  tenant: libre_terminale
  level: terminale
  track: generale
  teaching_status: specialite
  audience: libre
  candidates: [cned_libre, individuel, libre]
subjects:
  - subject: maths
    collection: rag_nexus_maths_terminale_gen_specialite
    taxonomy_path: taxonomy/maths/terminale_gen_specialite.yml
    taxonomy_sha256: 4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6
    programme_version: BOEN_special_8_2019-07-25
    notions: [suites_limites, continuite, derivation_convexite, logarithme, primitives_integration, equations_differentielles, combinatoire, geometrie_espace, produit_scalaire_espace, succession_epreuves, variables_aleatoires_esperance, loi_grands_nombres, python]
  - subject: nsi
    collection: rag_nexus_nsi_terminale_specialite
    taxonomy_path: taxonomy/nsi/terminale.yml
    taxonomy_sha256: b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f
    programme_version: BOEN_special_8_2019-07-25
    notions: [listes, piles, files, arbres, graphes, dictionnaires, recursivite, diviser_pour_regner, programmation_dynamique, parcours_graphes, recherche, tri, modele_relationnel, sql, contraintes, jointures, processus, protocoles, reseaux, routage, securisation, poo, tests_mise_au_point, gestion_modules, paradigme_fonctionnel, calculabilite_decidabilite]
```

Les modèles Pydantic utilisent `ConfigDict(extra="forbid", frozen=True)`. `validate_scope_integrity()` relit les fichiers de taxonomie depuis une racine dérivée de `pilot_validation.py`, recalcule leurs SHA-256, extrait toutes les notions et exige l'égalité exacte, sans doublon ni collection supplémentaire.

- [ ] **Step 4: Écrire les tests RED de réfutation du scope**

Tester séparément : hash de taxonomie modifié, taxonomie remplacée, notion absente, notion supplémentaire, collection supplémentaire, mauvais tenant, mauvais profil, statut `active`, chemin absolu et traversal `..`. Chaque cas doit produire une raison stable et ne jamais ouvrir d'accès.

- [ ] **Step 5: Vérifier le RED des réfutations**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_scope.py::TestScopeRefutations
```

Expected: FAIL pour chaque validation que l'implémentation minimale de Step 3 ne couvre pas encore.

- [ ] **Step 6: Implémenter les validations minimales manquantes**

Ajouter uniquement les contrôles nécessaires aux réfutations observées : chemins relatifs confinés à `taxonomy/`, égalité brute des digests, égalité exhaustive des notions et des collections, identité exacte et statut dormant.

- [ ] **Step 7: Vérifier le GREEN et les types**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_scope.py
python -m ruff check rag_pedago/governance tests/unit/test_pilot_validation_scope.py
python -m mypy rag_pedago/governance
```

Expected: PASS, zéro erreur Ruff/mypy.

- [ ] **Step 8: Commit**

```bash
git add services/rag-pedago/configs/pilot_validation_scope.yml \
  services/rag-pedago/rag_pedago/governance \
  services/rag-pedago/tests/unit/test_pilot_validation_scope.py
git commit -m "rag-pedago: verrouille le scope pilote LOT38"
```

### Task 2: Définir la politique dormante et sa matrice

**Files:**
- Create: `services/rag-pedago/configs/pilot_validation_policy.yml`
- Modify: `services/rag-pedago/rag_pedago/governance/pilot_validation.py`
- Create: `services/rag-pedago/tests/unit/test_pilot_validation_policy.py`

- [ ] **Step 1: Écrire les tests RED d'intégrité**

Exiger que le document canonique porte `status=eligible_for_promotion`, que les quatre capacités suivantes soient exactement `false`, et que les quatre verrous publics historiques soient attendus à `false` :

```python
VALIDATION_CAPABILITIES = {
    "validation_real_documents_allowed",
    "validation_pipeline_allowed",
    "validation_answer_generation_allowed",
    "validation_openrouter_allowed",
}
PUBLIC_LOCKS = {
    "real_documents_allowed",
    "ui_runtime_allowed",
    "answer_generation_allowed",
    "curated_ingestion_allowed",
}
```

Le test lit aussi `configs/pedago_interface_contract.yml` et exige que les quatre valeurs publiques observées correspondent aux attentes fermées de la politique.

- [ ] **Step 2: Vérifier le RED**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_policy.py
```

Expected: FAIL parce que le fichier de politique et son loader n'existent pas.

- [ ] **Step 3: Créer la politique canonique**

Le YAML doit déclarer :

```yaml
policy_id: libre_terminale_validation_policy_v1
status: eligible_for_promotion
scope_ref: libre_terminale_maths_nsi_real_v1
activation_boundary: LOT41A
capabilities:
  validation_real_documents_allowed: false
  validation_pipeline_allowed: false
  validation_answer_generation_allowed: false
  validation_openrouter_allowed: false
public_locks:
  real_documents_allowed: false
  ui_runtime_allowed: false
  answer_generation_allowed: false
  curated_ingestion_allowed: false
validation_environment:
  environment_id: nexus-validation-1
  isolation_status: intended_pending_lot41a
  public_routes_allowed: false
  credentials_ref_env: NEXUS_VALIDATION_CREDENTIALS_REF
  dsn_ref_env: NEXUS_VALIDATION_DATABASE_URL
  bucket_ref_env: NEXUS_VALIDATION_BUCKET
  network_ref_env: NEXUS_VALIDATION_NETWORK
authorization_matrix:
  read_real_documents:
    capabilities: [validation_real_documents_allowed]
    allowed_callers: [lot42_publisher, lot43_evaluator]
  publish_reviewed_chunks:
    capabilities: [validation_real_documents_allowed, validation_pipeline_allowed]
    allowed_callers: [rag-engine]
    quality_chain_required: true
  generate_grounded_answer:
    capabilities: [validation_answer_generation_allowed, validation_openrouter_allowed]
    allowed_callers: [rag-engine]
required_authorization:
  decision: AUTHORIZE_VALIDATION_PIPELINE
  authority_role: lead
  evidence_kind: github_pr_approval
  scope_digest_required: true
  policy_digest_required: true
  expiry_required: true
  rights_verification_required: true
  pii_absence_required: true
  rollback_proof_required: true
```

La configuration ne contient aucune valeur de secret, DSN, bucket ou réseau : uniquement les noms de références d'environnement. Le schéma général accepte des booléens de capacité, afin que LOT41A puisse charger un vrai overlay YAML par la même API. La validation séparée `validate_dormant_policy()` exige les quatre valeurs `false` pour le fichier canonique LOT38. Le modèle refuse les clés inconnues, `status=active`, un environnement autre que `nexus-validation-1`, une isolation présentée à tort comme prouvée, une route publique autorisée, un appelant public ou une matrice qui omet une capacité nécessaire.

- [ ] **Step 4: Ajouter les tests anti-dérive des verrous globaux**

Le test charge le contrat public sans le modifier, exige les quatre verrous à `false` et rejoue le comportement du garde canonique. La comparaison avec le parent Git appartient à la vérification de dépôt de Task 6, jamais à pytest, afin de rester valable en archive et en shallow checkout.

- [ ] **Step 5: Vérifier le GREEN**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_scope.py tests/unit/test_pilot_validation_policy.py
python -m ruff check rag_pedago/governance tests/unit/test_pilot_validation_scope.py tests/unit/test_pilot_validation_policy.py
python -m mypy rag_pedago/governance
```

Expected: PASS, zéro erreur Ruff/mypy.

- [ ] **Step 6: Commit**

```bash
git add services/rag-pedago/configs/pilot_validation_policy.yml \
  services/rag-pedago/rag_pedago/governance/pilot_validation.py \
  services/rag-pedago/tests/unit/test_pilot_validation_policy.py
git commit -m "rag-pedago: définit la politique dormante LOT38"
```

---

## Chunk 2: Autorisation réfutable et garde canonique

### Task 3: Refuser toute autorisation incomplète ou hors scope

**Files:**
- Modify: `services/rag-pedago/rag_pedago/governance/pilot_validation.py`
- Create: `services/rag-pedago/tests/fixtures/pilot_validation/activation.valid.yml`
- Create: `services/rag-pedago/tests/fixtures/pilot_validation/authorization.valid.yml`
- Create: `services/rag-pedago/tests/fixtures/pilot_validation/github_approval.valid.yml`
- Create: `services/rag-pedago/tests/fixtures/pilot_validation/publication_package.valid.yml`
- Create: `services/rag-pedago/tests/unit/test_pilot_validation_authorization.py`

- [ ] **Step 1: Écrire le test RED du chemin futur chargé depuis YAML**

Le scénario LOT41A de test est un vrai fichier YAML chargé par `load_policy()`, jamais un `model_copy`. Le document LOT41A ne contient aucun merge SHA de sa propre PR. Il référence seulement le SHA LOT41, le SHA-256 brut du scope, `base_policy_digest` pour les octets exacts de la politique dormante LOT38 et `activation_policy_digest` pour les octets exacts du fichier d'activation réellement chargé, puis l'environnement, le périmètre, l'expiration et le rollback. Une preuve GitHub séparée représente le readback API postérieur et doit couvrir exactement le head approuvé.

Définir l'API pure :

```python
decision = evaluate_authorization(
    scope=scope,
    base_policy=load_policy(CANONICAL_POLICY),
    activation_policy=load_policy(ACTIVATION_FIXTURE),
    authorization=valid_authorization,
    approval_evidence=verified_github_readback,
    publication_package=reviewed_package,
    request=ValidationRequest(...),
    now=datetime(2026, 7, 31, 22, 0, tzinfo=UTC),
)
assert decision.allowed is True
assert decision.reasons == ()
```

La politique versionnée réelle reste fermée. Un test distinct charge cette politique depuis disque et exige que la même autorisation indépendante soit refusée. Un autre test appelle l'évaluateur sans `approval_evidence` et prouve qu'un YAML d'autorisation plausible ne crée jamais seul une autorité.

- [ ] **Step 2: Vérifier le RED**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_authorization.py
```

Expected: FAIL, fonction d'évaluation absente.

- [ ] **Step 3: Implémenter le premier GREEN minimal**

Le document d'autorisation de test contient : décision et statut, identité et digest brut du scope, digests bruts distincts de la politique de base et de la politique d'activation réellement chargée, SHA LOT41, environnement exact, collections exactes, profil exact, droits/provenance/PII vérifiés, rollback testé et une référence de PR. La preuve GitHub indépendante contient le dépôt exact, la PR, la base `main`, le head, le head effectivement approuvé, le reviewer humain déclaré `lead`, les instants, l'état de révocation et, après fusion, le merge SHA. Les erreurs de parsing et champs inconnus deviennent des raisons de refus, jamais des exceptions d'accès.

L'ordre de décision est déterministe : intégrité scope/politique, capacités, autorisation/expiration, preuve d'approbation indépendante, environnement, collections, identité/profil, droits/provenance/PII, rollback, appelant/opération, puis package de publication. `publish_reviewed_chunks` exige en plus un package adressé par contenu, non révoqué, dont les trois états sont exactement `quality=passed`, `gate=passed`, `review=reviewed` et dont le publisher est `rag-engine`.

- [ ] **Step 4: Ajouter RED puis GREEN pour l'autorité indépendante**

Créer `TestAuthorityEvidence` avec des tests distincts pour : autorisation absente/partielle/périmée, preuve GitHub absente, dépôt/PR/base incorrects, approbateur non-lead, head approuvé différent, approbation révoquée, décision/statut inconnu, SHA LOT41 incorrect et expiration incohérente.

Run RED puis GREEN :

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_authorization.py::TestAuthorityEvidence
```

- [ ] **Step 5: Ajouter RED puis GREEN pour le scope et l'identité**

Ajouter un test nommé par cas et vérifier une raison stable pour :

1. digest scope erroné ;
2. digest politique erroné ;
3. taxonomie modifiée ;
4. collection supplémentaire ;
5. mauvais tenant ;
6. mauvais profil candidat ;
7. matière, année, niveau, voie, audience ou statut hors scope ;
8. mauvais environnement ;
9. capacité partiellement ouverte ;
10. opération ou appelant inconnu, `cockpit` et `public_bff`.

Run RED puis GREEN :

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_authorization.py::TestScopeAndIdentityRefutations
```

- [ ] **Step 6: Ajouter RED puis GREEN pour la chaîne de publication**

Créer `TestPublicationChain` : provenance inconnue/non vérifiée, droits inconnus/non vérifiés, PII non vérifiée, rollback absent/non testé, package absent, digest du package divergent, `quality` non passée, `gate` non passée, `needs_review`, quarantaine, révocation et publisher différent de `rag-engine`. Chaque test appelle le vrai évaluateur et charge les fixtures réelles, sans mock.

Run RED puis GREEN :

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_authorization.py::TestPublicationChain
```

- [ ] **Step 7: Ajouter RED puis GREEN pour les entrées mal formées**

Créer `TestMalformedInputs` pour YAML invalide, mapping absent, clé inconnue, date naïve, digest non SHA-256 et chemin absolu/traversal. Run :

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_authorization.py::TestMalformedInputs
```

- [ ] **Step 8: Vérifier la suite complète et la qualité**

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q \
  tests/unit/test_pilot_validation_scope.py \
  tests/unit/test_pilot_validation_policy.py \
  tests/unit/test_pilot_validation_authorization.py
python -m ruff check rag_pedago/governance tests/unit/test_pilot_validation_authorization.py
python -m mypy rag_pedago/governance
```

Expected: PASS, et la politique canonique LOT38 refuse toujours le scénario valide.

- [ ] **Step 9: Commit**

```bash
git add services/rag-pedago/rag_pedago/governance/pilot_validation.py \
  services/rag-pedago/tests/fixtures/pilot_validation \
  services/rag-pedago/tests/unit/test_pilot_validation_authorization.py
git commit -m "rag-pedago: refuse les autorisations LOT38 invalides"
```

### Task 4: Exposer un audit déterministe sans effet de bord

**Files:**
- Create: `services/rag-pedago/scripts/pilot_validation_policy_audit.py`
- Create: `services/rag-pedago/tests/unit/test_pilot_validation_policy_audit.py`
- Modify: `services/rag-pedago/Makefile`

- [ ] **Step 1: Écrire les tests RED du CLI**

Le CLI sans argument charge les deux configs canoniques et le contrat public, imprime une synthèse Markdown stable contenant `DORMANT`, le scope, les deux hashes taxonomiques, `39 notions`, les quatre capacités fermées et `GO_LIVE: NO_GO`, puis sort zéro. Un fichier invalide, une taxonomie dérivée ou un verrou public ouvert sort non-zéro sans traceback.

- [ ] **Step 2: Vérifier le RED**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_policy_audit.py
```

Expected: FAIL, script absent.

- [ ] **Step 3: Implémenter le CLI et la cible Make**

Ajouter `pilot-validation-policy-audit` à `.PHONY` et :

```make
pilot-validation-policy-audit:
	$(PY) scripts/pilot_validation_policy_audit.py
```

Le script accepte `--scope`, `--policy`, `--public-contract` pour les tests. Il ne lit aucune variable de secret, n'appelle ni réseau, ni PostgreSQL, ni subprocess et ne crée aucun fichier.

- [ ] **Step 4: Vérifier le premier GREEN du CLI**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_policy_audit.py::TestCanonicalAudit
```

Expected: PASS pour la synthèse canonique et les refus d'intégrité de base.

- [ ] **Step 5: Écrire les tests RED d'absence d'effet de bord**

Vérifier : statut Git inchangé, aucun accès réseau/environnement, aucune création sous `data/`, refus propre en mode Python `-O`, chemins dérivés de `__file__` et overrides relatifs/explicites uniquement.

- [ ] **Step 6: Vérifier le RED des effets de bord**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_policy_audit.py::TestAuditSideEffects
```

Expected: FAIL tant que le CLI minimal ne protège pas toutes les frontières observées.

- [ ] **Step 7: Implémenter le durcissement minimal**

Ajouter uniquement les contrôles nécessaires : chargement explicite par `Path`, erreurs capturées sans traceback, absence totale d'accès à `os.environ`, réseau, subprocess et chemins d'écriture.

- [ ] **Step 8: Vérifier le GREEN complet**

Run:

```bash
cd services/rag-pedago
PYTHONPATH=. pytest -q tests/unit/test_pilot_validation_policy_audit.py
make pilot-validation-policy-audit
python -m ruff check scripts/pilot_validation_policy_audit.py tests/unit/test_pilot_validation_policy_audit.py
```

Expected: PASS et verdict dormant/NO_GO.

- [ ] **Step 9: Commit**

```bash
git add services/rag-pedago/Makefile \
  services/rag-pedago/scripts/pilot_validation_policy_audit.py \
  services/rag-pedago/tests/unit/test_pilot_validation_policy_audit.py
git commit -m "rag-pedago: audite la politique dormante LOT38"
```

---

## Chunk 3: Décision, preuves et livraison

### Task 5: Documenter la décision et les exclusions du stash

**Files:**
- Create: `docs/adr/ADR-0021-politique-validation-pilote-dormante.md`
- Create: `docs/reports/lot_38_governance_transition.md`

- [ ] **Step 1: Rédiger l'ADR**

Consigner : scope exact, deux collections/taxonomies et digests, quatre capacités de validation fermées, quatre verrous publics fermés, environnement `nexus-validation-1`, autorité LOT41A, séparation contrôle/données, refus fail-closed et rollback. Expliquer que l'état est `eligible_for_promotion`, jamais `active`.

Déclarer explicitement que LOT38 est un modèle dormant sans exécuteur. LOT41 doit raccorder `rag-engine` au scope via contrat/API ou artefact signé, sans import ni lecture directe du code `rag-pedago`. LOT41A doit fournir l'approbation GitHub indépendante du payload ; LOT42 doit vérifier ce raccordement et la chaîne `quality → gate → review` avant la première publication. Qualifier l'isolation `nexus-validation-1` d'intention configurée non encore prouvée.

- [ ] **Step 2: Consigner l'audit du stash immuable**

Référencer le stash `906558ab06c384dd3b5ed0ed5387646a06585427` sans l'appliquer ni le supprimer. Retenir seulement l'intention de garde réfutable. Exclure explicitement : activation de `ui_runtime_allowed`/`real_documents_allowed`, migration 002, modifications retrieval/review/Compose, suppression de `.gitkeep`, rattrapage des `except Exception` et plan multi-lots obsolète.

- [ ] **Step 3: Construire la matrice de preuve**

Le rapport initial contient exactement les sections `Verdict`, `Périmètre`, `Audit du stash`, `Scope canonique`, `Politique dormante`, `Tests de réfutation`, `Matrice de preuve`, `Dettes et frontières`, `Décision de livraison`. Sa matrice suit `critère → responsable → commande/procédure → environnement → artefact → digest → verdict`. Tant que la CI finale n'est pas exécutée, le verdict du lot reste `LOT38_AWAITING_FINAL_EVIDENCE` et les lignes non observées restent `PENDING` ; aucune preuve n'est anticipée.

- [ ] **Step 4: Vérifier les documents**

Contrôler liens, hashes bruts, compte exact de 39 notions, quatre capacités `false`, quatre verrous publics `false`, absence de secret/PII/chemin absolu, `git diff --check` et conservation du verdict global `NO_GO`.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/ADR-0021-politique-validation-pilote-dormante.md \
  docs/reports/lot_38_governance_transition.md
git commit -m "docs: consigne la transition de gouvernance LOT38"
```

### Task 6: Vérifier, revoir et publier LOT38

**Files:**
- Create: `docs/reports/evidence/lot_38/ci-local-summary.txt`
- Modify: `docs/reports/lot_38_governance_transition.md`
- Modify only if review requires: implementation files already listed in Tasks 1–5

- [ ] **Step 1: Exécuter les validations ciblées**

```bash
cd services/rag-pedago
make lint
make typecheck
PYTHONPATH=. pytest -q \
  tests/unit/test_pilot_validation_scope.py \
  tests/unit/test_pilot_validation_policy.py \
  tests/unit/test_pilot_validation_authorization.py \
  tests/unit/test_pilot_validation_policy_audit.py
make pilot-validation-policy-audit
cd ../..
bash scripts/check-governance-locks.sh
git diff --quiet origin/main...HEAD -- \
  scripts/governance-locks.baseline \
  scripts/check-governance-locks.sh \
  services/rag-pedago/configs/pedago_interface_contract.yml
git diff --check origin/main...HEAD
```

- [ ] **Step 2: Exécuter la CI locale canonique**

Résoudre d'abord `CI_SOURCE_SHA=$(git rev-parse HEAD)` et créer un répertoire hors Git avec `mktemp -d /tmp/nexus-lot38-evidence.XXXXXX`. Run `bash scripts/ci-local.sh` une seule fois depuis la racine avec Python 3.11 et Node 22.22.0, en capturant stdout/stderr dans `<evidence>/ci-local.log` et son code de sortie.

Expected: toutes les cibles PASS, zéro régression. Calculer `sha256sum <evidence>/ci-local.log`, extraire exactement les lignes `PASS` et le total, puis comparer leur nombre au journal brut. Ne pas réutiliser une exécution antérieure à une correction de code.

- [ ] **Step 3: Versionner la synthèse et actualiser le rapport**

Créer `docs/reports/evidence/lot_38/ci-local-summary.txt` avec `observedAt`, `ciSourceSha`, les résultats exacts, le total et `rawLogSha256`. Utiliser `apply_patch`, jamais une copie aveugle du log. Recalculer les SHA-256 du scope, de la politique, des deux taxonomies, de l'ADR et de la synthèse ; ne jamais inscrire dans le rapport le digest du rapport lui-même. Actualiser la matrice et passer le verdict du lot à `LOT38_LOCAL_CI_GREEN_AWAITING_REVIEWS_AND_CHECKS` uniquement si tout est vert, tout en maintenant `GO_LIVE: NO_GO`. Le digest final du rapport est calculé après commit et publié uniquement dans la PR ou un artefact GitHub externe.

Commit :

```bash
git add docs/reports/evidence/lot_38/ci-local-summary.txt \
  docs/reports/lot_38_governance_transition.md
git commit -m "docs: actualise les preuves LOT38"
```

- [ ] **Step 4: Demander les revues indépendantes**

Faire relire successivement la conformité au design, la qualité du code/tests, puis le diff complet `origin/main...HEAD`. Corriger chaque P0/P1/Important par TDD et relancer la CI complète, puis régénérer la synthèse, si du code change. Une correction documentaire après revue exige au minimum les gardes documentaires et les checks GitHub de sa tête exacte. Le statut opérationnel `READY_FOR_MERGE` n'est déclaré que dans la PR après approbation des revues et réussite des six checks du head exact ; il n'est jamais anticipé dans le rapport versionné.

- [ ] **Step 5: Publier une PR brouillon**

Pousser `lot-38-garde-fous-refutables` sans force, créer une PR vers `main` et joindre le rapport. Attendre les six checks stricts sur le SHA documentaire final exact. La preuve GitHub reste attachée au run immuable ; le rapport distingue cette validation finale de la CI locale exécutée sur `ciSourceSha` et ne crée pas de boucle de commit de preuve.

- [ ] **Step 6: Fusionner et revalider `main`**

Passer la PR prête uniquement après revues et checks, fusionner par squash avec `--match-head-commit`, sans `--admin`, puis attendre le run `push` exact de `main`. Refaire le GET-only de protection avant nettoyage de la branche LOT38.

## Hors périmètre explicite

- aucune activation de verrou global ou de capacité de validation ;
- aucune lecture de document réel, aucun appel OpenRouter et aucune connexion DB/bucket/réseau ;
- aucune modification de `packages/contracts`, des endpoints cockpit/rag-engine, de Compose ou des migrations ;
- aucune reprise des changements LOT39/LOT40 des stashes ;
- aucune autorisation humaine LOT41A anticipée.
