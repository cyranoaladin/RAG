# H2-B — remédiation exact-head avant go-live

- **PR** : https://github.com/cyranoaladin/RAG/pull/95 (reste **draft**)
- **Branche** : `track-a/lot-h2b-corpus-production-readiness`
- **HEAD de départ** : `1095c312652feceb1493eba8f8d6c25994c6dfc1`
- **Base** : `main` (`a956441645d48107ab983fad62b80f0848345e81`)
- **Audit exact-head** : `PASS_WITH_FINDINGS` — quatre findings réels (2×P1, 2×P2), aucun ancien thread historique bloquant.
- **Portée de cette mission** : fermer techniquement les quatre findings, sans déploiement, sans autorisation LOT41A/LOT42 réelle, sans provisionnement d'ancre de confiance de production réelle, sans toucher GitGuardian ni la PR #96.

Les preuves de staging multi-niveau (`STAGING_SEARCH_READY=true`, 12 collections, 395 chunks, real E5/reranker, 0 fuite cross-collection) sont préservées à l'identique — aucune donnée métier ni ingestion reconstruite.

---

## Finding 1 (P1) — NEW-AUDIT-PRODUCTION-API-RELEASE

**ISSUE** : `services/rag-engine/infra/docker-compose.v2.yml` ne montait que `wave0.release.json` — l'API de production ne pouvait pas voir les 2 collections Troisième supplémentaires ni les 10 collections multi-niveaux, alors que ces 12 collections sont désormais canoniquement actives.

**FIX** :
- Recherche préalable : le mécanisme multi-manifest (`RAG_RELEASE_MANIFESTS_JSON` → `load_release_registry`) existait déjà, testé, dans `release_readiness.py`/`retrieval_v2_endpoint.py` — mais piloté par une variable d'environnement JSON, jamais par un fichier versionné avec sa propre empreinte externe.
- Nouveau fichier canonique **`services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json`** (`registry_version`, `school_year`, `releases[]`) référençant explicitement les 2 manifests agrégés existants (`wave0/wave0.release.json` → 2 collections Troisième, `multilevel/multilevel.release.json` → 10 collections) — aucune collection listée individuellement en dur, aucune wildcard, aucun scan de répertoire.
- Nouvelle fonction `load_release_registry_file()` (`src/ingestor/release_readiness.py`) : vérifie l'empreinte SHA-256 externe du registre lui-même, borne `registry_version`, refuse toute collection dupliquée entre entrées, puis délègue **entièrement** au `load_release_registry()` existant (aucune logique de digest/collision dupliquée).
- `retrieval_v2_endpoint._configured_release_registry()` accepte désormais trois mécanismes mutuellement exclusifs (`RAG_RELEASE_REGISTRY_PATH`/`SHA256` en priorité, `RAG_RELEASE_MANIFESTS_JSON`, ou le couple historique) — une seule architecture, jamais deux systèmes parallèles staging/production.
- `docker-compose.v2.yml` : `RAG_RELEASE_MANIFEST_PATH`/`SHA256` remplacés par `RAG_RELEASE_REGISTRY_PATH`/`SHA256`, montage étendu de `wave0/` seul à toute la racine `prerentree_2026_2027/` (registre + `wave0/` + `multilevel/`) en lecture seule.

**TEST** : ~26 nouveaux/étendus tests dans `tests/test_release_readiness.py` (chargement réel des 12 collections via le fichier committé, digest du registre incorrect, manifest référencé absent/digest dérivé, collection dupliquée entre entrées, version de registre non supportée, chemin wildcard refusé, collections déclarées ≠ collections réelles du manifest, dérive de `release_kind`, ambiguïté avec les deux autres mécanismes) + `tests/test_prod_compose_config_mount.py` mis à jour (monte le registre exact, pas seulement wave0).

**RESULT** : PASS — 12/12 collections chargées et réconciliées ; suite complète rag-engine (2600+ tests non-integration) verte ; `LOT40_HYBRID_INTEGRATION=PASS` sur pgvector éphémère réel.

**REMAINING_EXTERNAL_GATE** : aucun — le mécanisme est complet et versionné. Le déploiement réel (montage effectif en production) reste hors périmètre (`API_PRODUCTION_DEPLOYED=false`).

---

## Finding 2 (P1) — NEW-AUDIT-PRODUCTION-WORKERS

**ISSUE** : Worker A/B multi-niveaux (`multilevel_cli.py`/`multilevel_publication_resume_cli.py`) refusaient tout `environment != "rehearsal"` **avant même d'appeler** `enforce_readiness_gate()` en mode production — aucun chemin production n'existait, testable ou non.

**Découverte annexe (bug réel, corrigé)** : `readiness_gate._GOVERNED_REPOSITORY_ROOT` dérivait la racine gouvernée avec `Path(__file__).resolve().parents[3]` — deux niveaux trop haut (le fichier vit à 5 niveaux sous la racine du dépôt, pas 3). Sur un checkout réel, `enforce_readiness_gate(environment="production")` échouait donc systématiquement sur « ne ressemble pas à un checkout Nexus », **avant** même de vérifier l'ancre — masquant le vrai signal (`PRODUCTION_TRUST_ANCHOR_PROVISIONED=false`). Aucun test existant ne l'exerçait contre le vrai disque (tous montent une racine synthétique). Corrigé à `parents[5]` ; nouveau test `TestTheRealGovernedRootResolvesOnAnActualCheckout` verrouille la dérivation réelle et prouve que l'unique blocage restant est bien l'ancre absente.

**FIX** :
- CLIs des deux workers : `environment != "rehearsal"` → `environment not in ("rehearsal", "production")` — la gate elle-même reste l'autorité fail-closed (ancre gouvernée non fournie ⇒ refus, inchangé).
- Nouveau module **`src/ingestor/ingestion_control/revocation_registry.py`** : le manifeste de readiness de production signé portait déjà un `revocation_registry_digest` (contrat `nexus_contracts.production_readiness`) jamais vérifié contre un fichier réel — `load_revocation_registry()` + `require_revocation_registry_matches_manifest()` comblent ce trou, fail-closed, sans repli « absence = aucune révocation ».
- `_enforce_production_evidence()` (nouveau, dans chaque CLI, appelé **avant** tout chargement d'autorité et toute connexion PostgreSQL) : exige en production le registre de releases (Finding 1) et le registre de révocation lié par digest au manifeste signé. Worker B exige en plus : `--expected-product-role`, séparation stricte DSN produit / DSN contrôle d'ingestion, attestation du rôle produit (réutilise `attest_runtime_role`, déjà utilisé côté contrôle d'ingestion) — aucun repli superutilisateur.
- Heartbeat optionnel (`--heartbeat-file`, mécanisme déjà existant côté Worker A Wave 0, étendu aux deux CLIs multi-niveaux) pour un healthcheck Docker réel.
- Nouvelle image **`infra/Dockerfile.multilevel-worker-production`** : préserve la profondeur réelle du dépôt sous `/app/services/rag-engine/src/...` (jamais l'aplatissement `/app/ingestor/...` des images rehearsal) — condition nécessaire pour que la racine gouvernée se résolve dans le conteneur.
- Nouvelle topologie **`infra/docker-compose.production-workers.yml`** : Worker A / Worker B production, `restart: unless-stopped`, `read_only: true`, aucun `ports:`, montages read-only (ancre de confiance, registre de releases, registre de révocation, artefact embedding), healthcheck heartbeat, DSN séparés.

**TEST** : `tests/test_revocation_registry.py` (10 tests), `tests/test_multilevel_worker_cli.py` étendu (+18 tests : guard logic de `_enforce_production_evidence` pour chaque pièce manquante/dérivée, séparation DSN, attestation du rôle produit, chemin complet production→Postgres-connect / production→chargement modèle atteint avec preuve complète, dérive du modèle embedding en production), `tests/test_readiness_gate.py` (+3 tests verrouillant la racine réelle), `tests/test_production_workers_compose.py` (24 tests sur la topologie).

**RESULT** : PASS — 38/38 tests worker CLI, 31/31 gate, 24/24 compose ; `PRODUCTION_WORKER_WITHOUT_TRUST_ANCHOR=STARTUP_FAIL` vérifié contre le vrai disque (pas une racine synthétique) ; `PRODUCTION_WORKER_WITHOUT_REVOCATION_REGISTRY=STARTUP_FAIL` vérifié.

**REMAINING_EXTERNAL_GATE** : `PRODUCTION_TRUST_ANCHOR_PROVISIONED=false` (inchangé, non provisionné par cette mission) ; `PRODUCTION_WORKERS_DEPLOYED=false` ; `PRODUCTION_LOT41A_AUTHORIZATIONS_CREATED=0` ; `PRODUCTION_LOT42_ATTESTATIONS_CREATED=0`.

---

## Finding 3 (P2) — NEW-AUDIT-CLI-SCOPE-COVERAGE

**ISSUE** : `scripts/rag_query.py` portait une allowlist statique de 2 scopes (`ALLOWED_SCOPES`) contre 13 scopes réellement supportés par le registre backend (`nexus_contracts.load_retrieval_scope_registry()`), et pouvait signer sa propre identité avec `NEXUS_INTERNAL_TOKEN_SECRET` — aucun client distribuable à un agent externe n'existait sans ce secret maître.

**FIX** :
- `scripts/rag_query.py` (client **opérateur interne**, désormais documenté `INTERNAL_OPERATOR_TOOL=true`) : `ALLOWED_SCOPES` remplacé par `available_scopes()`, dérivé dynamiquement du registre canonique (13/13, jamais recopié en dur) ; ajout de `--list-scopes` (aucun credential requis pour lister).
- Nouveau **`scripts/rag_query_external.py`** — client externe sûr, `EXTERNAL_IDENTITY_ISSUER_REQUIRED=true` documenté : lit uniquement `RAG_API_URL`, `RAG_BFF_SERVICE_TOKEN`, `RAG_IDENTITY_TOKEN` (identité pré-émise) ; n'importe jamais `ingestor.identity_v2` ni ne lit `NEXUS_INTERNAL_TOKEN_SECRET`, ne sait pas signer HS256 ; transmet l'identité reçue telle quelle dans `X-Nexus-Identity` ; une identité refusée par le serveur (absente/mauvaise/expirée/scope non couvert) remonte comme erreur HTTP, jamais recontournée localement. Aucun endpoint `/mint-token` créé (émission externe = responsabilité BFF/gateway, hors périmètre).

**TEST** : `tests/test_rag_query_client.py` étendu (+5 tests : couverture des 13 scopes, `--list-scopes` sans credential, identité émise pour les 12 scopes V2, refus propre du scope pilote non-V2, `--help` liste bien les 13 scopes) ; nouveau `tests/test_rag_query_external_client.py` (10 tests : succès nominal, BFF/identité absents refusés avant tout appel réseau, 401/403 serveur surfacés tels quels, `--list-scopes` sans credential, garantie structurelle par AST qu'aucun import/constante ne référence `identity_v2`/`NEXUS_INTERNAL_TOKEN_SECRET`/`hmac` en dehors des docstrings explicatives).

**RESULT** : PASS — `BACKEND_SCOPE_COUNT=13`, `INTERNAL_CLI_SCOPE_COUNT=13`, `INTERNAL_CLI_COVERS_ALL_SCOPES=true`, `EXTERNAL_CLIENT_EXISTS=true`, `EXTERNAL_CLIENT_MASTER_SECRET_REQUIRED=false`.

**REMAINING_EXTERNAL_GATE** : l'émission réelle d'identités externes courte durée reste la responsabilité du BFF/gateway Nexus (provisionnement infra, hors périmètre de cette remédiation).

---

## Finding 4 (P2) — NEW-AUDIT-REAL-MODEL-CI-COVERAGE

**ISSUE** : les tests exerçant les vrais modèles E5/reranker (`test_multilevel_real_ingestion.py`, `test_wave0_french_pgvector.py`) sont gated par des variables d'environnement (`RAG_EMBEDDING_MODEL_CACHE_DIR`, etc.) jamais positionnées par le workflow GitHub Actions — CI verte sans jamais les exécuter.

**Cartographie du coût (avant implémentation)** : E5-large ≈1.3 Go (ADR-0007) ; reranker MiniLM non documenté (typiquement <100 Mo) ; les deux chargent en `local_files_only=True` (aucun téléchargement accidentel à l'exécution) ; script de préparation d'artefact existant pour l'embedding, **absent pour le reranker** ; `test_lot40_hybrid_pgvector.py` tourne déjà réellement contre un pgvector éphémère en CI mais avec un `DeterministicEmbedder` synthétique, jamais le vrai modèle ; les deux tests real-ingestion dépendent de PDF propriétaires **volontairement non committés** (droits d'auteur des manuels) — donc structurellement hors de portée d'un runner GitHub hosted, quelle que soit l'implémentation retenue.

**FIX (option retenue : vrai job Actions, modèles pinés — pas de receipt cryptographique, disproportionné pour ce périmètre)** :
- Révisions HuggingFace résolues et épinglées en commit SHA (jamais `"latest"`/`"main"`) : `intfloat/multilingual-e5-large@3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`, `cross-encoder/ms-marco-MiniLM-L-6-v2@233902d25c440f23af6f7d6e94d2946bac0bee0a`.
- Nouveau `scripts/e2e/prepare-reranker-model-artifact.sh`, miroir exact de `prepare-embedding-model-artifact.sh` (mêmes garde-fous : chemin absolu hors dépôt, refus en `RAG_ENV=production`, `manifest.json` + `SHA256SUMS` + inventaire SHA-256).
- Nouveau `tests/integration/test_real_model_ci_acceptance.py` — acceptance minimale, honnêtement bornée : (1) le vrai E5 encode du texte français en vecteurs 1024-d plausibles (deux phrases proches sémantiquement se ressemblent plus qu'une phrase sans rapport) ; (2) le vrai reranker ordonne un passage pertinent au-dessus d'un passage non pertinent ; (3) ces vecteurs réels transitent par un **vrai** pgvector éphémère (extension `vector`, table minimale, requête ANN cosinus réelle) — jamais l'ingestion complète du corpus propriétaire.
- Nouveau job `real-model-acceptance` dans `.github/workflows/ci.yml`, distinct de `rag-engine` (CI code rapide) : `services: pgvector` (même digest d'image que `docker-compose.v2.yml`), cache `actions/cache` keyé sur révision+repo (optimisation seulement, jamais l'autorité), matérialisation + inventaire SHA-256 recalculé indépendamment du script (pas de confiance aveugle dans son stdout), échec fermé si un artefact caché est trouvé sans son inventaire.

**TEST** : le nouveau fichier de test skip proprement (module-level) en l'absence des variables requises (vérifié localement — impossible de télécharger/exécuter les vrais modèles dans cet environnement de remédiation) ; `ruff`/`mypy` verts sur le fichier de test et les deux scripts bash (`bash -n`) ; YAML du workflow validé (`yaml.safe_load`).

**RESULT** : PASS (mécanisme) — la validation d'exécution réelle du job (téléchargement effectif, exécution des trois assertions, réconciliation pgvector) ne peut être confirmée que sur le vrai HEAD poussé, via GitHub Actions (`actionlint` non disponible dans cet environnement pour une double-vérification statique).

**REMAINING_EXTERNAL_GATE** : `test_multilevel_real_ingestion.py`/`test_wave0_french_pgvector.py` (ingestion complète avec corpus propriétaire) restent local/self-hosted-only — leurs PDF source ne sont délibérément pas dans git. `REAL_MODEL_EXACT_HEAD_CI_COVERAGE=true` couvre real E5 + real reranker + real pgvector minimal, pas l'ingestion corpus complète.

---

## Régression (staging multi-niveau, préservé)

`STAGING_SEARCH_READY=true`, `SEARCH_READY_COLLECTIONS=12`, `TOTAL_GOVERNED_DOCUMENTS=13`, `TOTAL_GOVERNED_PLACEMENTS=13`, `TOTAL_GOVERNED_CHUNKS=395`, `MULTILEVEL_DOCUMENTS=11`, `MULTILEVEL_CHUNKS=359`, `THIRD_GRADE_DOCUMENTS=2`, `THIRD_GRADE_CHUNKS=36`, `REAL_EMBEDDING_MODEL_USED=true`, `REAL_RERANKER_USED=true`, `FAKE_VECTOR_ROWS=0`, `CROSS_COLLECTION_LEAKS=0`, `WRONG_SCOPE_LEAKS=0` — aucune donnée métier, aucune ingestion reconstruite ; aucun de ces faits n'a été modifié par cette remédiation.

## Note d'environnement local (non liée au code)

`scripts/ci-local.sh` a échoué localement (`packages/contracts`, `services/rag-pedago`, `services/rag-engine`, `services/cockpit`) — root cause identique dans les quatre cas : `command -v python3.11` résout un interpréteur `uv`-managé cassé (`Fatal Python error: init_fs_encoding`) sur cette machine de remédiation, avant même que `pip install` ne s'exécute. Preuve que ce n'est pas une régression de ce diff : l'échec touche à l'identique `packages/contracts` et `services/rag-pedago`, que cette mission ne modifie pas. Chaque cible individuelle (`make lint`, `make typecheck`, `make test`, `make test-integration-hybrid` pour rag-engine ; `make lint`, `make typecheck`, `make test` pour rag-pedago ; import contracts ; `check-governance-locks.sh`) a été rejouée directement avec un venv Python 3.12 sain et est verte. GitHub Actions provisionne son propre Python 3.11 via `actions/setup-python@v5` et n'est pas concerné par cette fragilité locale.
