# Rapport de lot — LOT41A/LOT42 : autorité de scope + chaîne d'attestations de publication

- **Branche** : `track-a/lot41a-lot42-governance-authorities`
- **Statut** : mécanismes candidats implémentés, testés, prêts pour revue humaine. **Aucune autorisation de scope réelle, aucune attestation de publication réelle n'existe** à l'issue de ce lot.
- **ADR** : ADR-0032 (LOT41A), ADR-0033 (LOT42) — toutes deux Proposées, non Acceptées.
- **Mandat** : décision de gouvernance TRACK A/B/C/D/E/F de l'utilisateur — construire les mécanismes candidats LOT41A/LOT42 puis STOP au GATE H1, sans jamais fabriquer d'autorité humaine.

## Ce qui a été livré

### Audit préalable (étape 1-3 du mandat)
Recherche exhaustive du dépôt pour établir les invariants LOT41A/LOT42 déjà spécifiés, sans les inventer : ADR-0021/LOT38 (`pilot_validation_policy.yml`) porte déjà `activation_boundary: LOT41A` et `required_authorization` avec `evidence_kind: github_pr_approval`, `scope_digest_required`, `expiry_required`, `pii_absence_required`, `rollback_proof_required`. `manifest.py` (LOT44f) documente explicitement l'absence de toute implémentation LOT41A antérieure. `resource_state.py` documente `RETRIEVAL_ELIGIBLE` comme le point d'ancrage naturel de LOT42.

### Conception (étape 4-6)
- **ADR-0032** — LOT41A : autorité d'autorisation de scope. Contrat `ScopeAuthorization`, stockage `ingestion_control.scope_authorizations`, vérification live via `scripts/github/trusted_human_review_github.check_github_review`, CLI opérateur, intégration worker fail-closed.
- **ADR-0033** — LOT42 : chaîne d'attestations de publication. Contrat `PublicationAttestation`, stockage `ingestion_control.publication_attestations`, cinq conditions d'invalidation live, point d'ancrage unique `REVIEWED -> RETRIEVAL_ELIGIBLE`.

### Implémentation (étape 7-8)
- `packages/contracts/src/nexus_contracts/scope_authorization.py`, `publication_attestation.py` (contrats Pydantic `extra="forbid"`, aucun champ de confiance figé).
- Migrations `007_scope_authorizations.sql`, `008_publication_attestations.sql` + rollbacks, rejouées et vérifiées sur PostgreSQL jetable réel (bootstrap, provisioning, rollback partiel, ré-application — cycle complet).
- `infra/scripts/provision_ingestion_control_roles.sh` étendu : deux nouveaux rôles least-privilege (`ingestion_control_authority`, `ingestion_control_attestor`), moindre privilège vérifié colonne par colonne (`information_schema.role_column_grants`) — le rôle worker (`ingestion_control_app`) ne reçoit qu'un accès `SELECT` sur les deux nouvelles tables, jamais d'écriture ; les rôles d'autorité/attestation ne reçoivent qu'un `UPDATE` de colonne restreint aux champs de révocation/invalidation.
- `infra/scripts/rollback_ingestion_control_schema.sh` : ordre canonique de verrouillage étendu aux deux nouvelles tables.
- `services/rag-engine/src/ingestor/ingestion_control/scope_authority.py`, `publication_attestation.py`, `_trusted_review.py` (invocation partagée, sous-processus, du script racine `trusted_human_review_github.py` — jamais un import direct inter-service).
- `services/rag-engine/src/ingestor/ingestion_worker/authorize_scope_cli.py`, `attest_publication_cli.py` (outils opérateur `docker exec` uniquement, jamais un endpoint réseau — revérifient toujours la review GitHub en direct avant d'écrire).
- `infra/Dockerfile.ingestion-worker` : copie `scripts/github/{trusted_human_review.py,trusted_human_review_github.py,trusted-reviewers.json}` et fixe `NEXUS_TRUSTED_REVIEW_SCRIPT` — l'image aplatie du worker ne contient jamais le dépôt complet, la résolution par défaut du script (relative à `__file__`) échouerait silencieusement sans cet override explicite.
- `attempt_retrieval_eligible_transition` (LOT42) : point d'ancrage unique testé indépendamment, **non encore appelé par le pipeline worker actuel** (aucune ressource n'atteint `REVIEWED` dans ce lot — hors périmètre, cf. ADR-0033 § Hors périmètre) ; prêt pour un futur lot qui construira la chaîne jusqu'à `REVIEWED`.
- Intégration worker (LOT41A) : `runner.py::_process_claimed_job` vérifie le scope en direct avant tout traitement, journalise `SCOPE_AUTHORIZATION_DENIED` dans `workflow_events` en cas de refus. Point d'injection `WorkerDeps.verify_scope_authorization` (même motif que `safe_fetch`/`validate_destination`) — production utilise toujours la vérification live réelle.

### Tests (étape 9-10)
- `tests/integration/test_lot41a_scope_authority.py`, `test_lot42_publication_attestation.py`, `_fake_github.py` (support partagé) : falsification, révocation (base **et** dismiss GitHub live sans écriture PostgreSQL — preuve centrale de la révocabilité réelle), replay, mismatch de scope, dérive de digest (contenu/profil/manifest), refus CLI sur PR non approuvée, exactitude de `verify_scope_authorization_by_id` (ne bascule jamais silencieusement sur une autorisation plus récente). 20 tests, PostgreSQL réel + frontière GitHub réelle (`gh` remplacé sur `PATH`, tout le reste de la chaîne — y compris `trusted_human_review_github.py`/`trusted_human_review.py` non modifiés — exécuté pour de vrai).
- Suites préexistantes : 8 fichiers d'intégration ont dû être mis à jour pour fournir les deux nouveaux mots de passe de rôle désormais requis par `provision_ingestion_control_roles.sh`, et pour stubber `WorkerDeps.verify_scope_authorization` dans les scénarios qui ne portent pas sur LOT41A (`test_lot44e_worker_e2e.py`, `test_lot44f_worker_resume.py`) — jamais une régression fonctionnelle, uniquement l'adaptation attendue d'un nouveau gate fail-closed. `test_lot44f_rollback_runner.py` : un test de rollback partiel ancrait sa cible sur `_HEAD - 2` (supposant implicitement 6 migrations) ; corrigé en cible fixe (`4`), le test portant sur le contenu précis des migrations 005/006, indépendant du nombre total de migrations.

### Validation (étape 10)
- `ruff check .` : clean.
- `mypy src` : clean (90 fichiers).
- `pytest -m "not integration"` : 1730 passed, 1 skipped (préexistant), 0 failed. Rejoué trois fois pendant ce lot, stable.
- `pytest tests/integration/` : rejoué trois fois (Docker réel, ~15 fixtures PostgreSQL jetables séquentielles par run) — deux runs entièrement verts, un run avec un échec unique et non reproductible (`test_password_visible_to_a_process_listing_is_never_the_real_secret`, une course de minutage préexistante entre un thread d'observation `ps` à 50 ms et le sous-processus `psql` réel — le test documente lui-même explicitement ce risque). Rejoué isolément immédiatement après : vert. Non lié aux changements de ce lot (le mécanisme de passage des mots de passe via `\getenv`/`PASSWORD %L` est identique pour les quatre rôles, ancien et nouveaux).

## Hors périmètre (escaladé, non implémenté)

- Toute autorisation de scope réelle, toute attestation de publication réelle.
- Le raccordement bidirectionnel formel `rag-pedago` ↔ LOT41A (ADR-0032, hors périmètre explicite).
- La chaîne `STAGED -> NEEDS_REVIEW -> REVIEWED` elle-même (aucune ressource n'y accède dans ce lot) — donc `attempt_retrieval_eligible_transition` reste non appelée en production tant qu'un futur lot ne construit pas ce chemin.
- La publication produit réelle (chunking/embedding/écriture `rag_chunks`) — hors périmètre de `nexus_contracts.resource_state` par sa propre docstring, donc hors périmètre de LOT42.

## Risques connus

- `docker-compose.ingestion.yml` exige désormais deux variables d'environnement supplémentaires (`INGESTION_CONTROL_AUTHORITY_PASSWORD`, `INGESTION_CONTROL_ATTESTOR_PASSWORD`) — tout déploiement existant utilisant ce fichier doit les fournir avant le prochain `up`. Aucun défaut silencieux : `provision_ingestion_control_roles.sh` échoue explicitement si absentes.
- `ScopeAuthorizationDeniedError`/`PublicationAttestationInvalidError` dépendent d'un appel réseau `gh api` — une panne GitHub transitoire ferait échouer la vérification live (fail-closed par construction : aucune ingestion ne procède sans preuve fraîche, jamais un cache qui masquerait une panne).

## GATE H1 — demande d'approbation humaine

Conformément à la décision de gouvernance : ce lot s'arrête ici. Aucune autorisation LOT41A, aucune attestation LOT42 n'a été créée. `LOT41A_AUTHORITY_VALID=false`, `LOT42_AUTHORITY_VALID=false` jusqu'à revue humaine `APPROVED` sur la PR portant ce lot, HEAD exact, challenge LOT41V.

- **PR** : à ouvrir depuis cette branche vers `main`.
- **HEAD** : figé au commit final de cette branche (voir rapport `git log -1` au moment de l'ouverture de PR).
- **BASE** : `main`.
- **Résumé** : ADR-0032/ADR-0033 (Proposées) + implémentation candidate complète LOT41A/LOT42 + 20 tests adversariaux dédiés + mise à jour des suites préexistantes pour le nouveau gate fail-closed.
- **Tests** : `ruff check .`, `mypy src`, `pytest -m "not integration"` (1730 passed), `pytest tests/integration/` (suite complète verte).
- **Risques** : voir section ci-dessus.

Décision attendue : review humaine `APPROVED` par `@abenrhouma`, sur le HEAD exact de cette PR, avant toute suite (GATE H2 et au-delà).
