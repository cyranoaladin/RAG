# LOT41 — plan d'implémentation identité et filtres

> Exécuter dans le worktree `lot-41-identity-filters` par incréments TDD. Chaque
> étape produit d'abord un test rouge, puis le minimum de code, puis une revue.

**Base :** `a02a09fe0342cf107f1dec49605f01dd4de324ae`

**Design :**
`docs/superpowers/specs/2026-08-01-lot41-identity-filters-design.md`

## Task 1 — contrat 0.4.0 et ADR

- Modifier `packages/contracts/pyproject.toml` vers `0.4.0`.
- Ajouter `InternalIdentity.school_year` et ses validations TDD.
- Borner les claims et matières, imposer sujet pseudonymisé, unicité et entier
  JSON sûr, puis porter manuellement les tests utiles du prototype LOT35.
- Mettre à jour les tests d'export `/v0.4/`, régénérer les schémas et le client
  cockpit.
- Définir dans le package `InternalIdentityEnvelope` et
  `PilotRetrievalScopeArtifact`, exporter leurs schémas et livrer l'artefact
  dormant dérivé de LOT38 avec preuve cross-service de projection/digest.
- Livrer dans le cockpit le validateur sémantique complémentaire et des
  fixtures de parité Python/TypeScript pour les invariants non exprimables par
  JSON Schema.
- Créer `docs/adr/ADR-0022-identite-et-filtres-retrieval.md`.
- Vérifier pytest/ruff contrats et cohérence générée cockpit.

## Task 2 — transport d'identité cockpit → moteur

- Tester puis construire un jeton interne imbriqué, HS256, issuer/audience
  exacts, TTL borné et sans secret par défaut.
- Produire `school_year` depuis `NEXUS_RELEASE_SCHOOL_YEAR`.
- Étendre `fetchEngine` avec un header identité distinct du jeton service.
- Exiger une session active et non révoquée sur search/chat ; prouver 401 avant
  tout appel moteur.
- Ne sérialiser ni identité complète ni jeton interne dans la session remise au
  navigateur ; les extraire seulement du JWT httpOnly dans les routes serveur.
- Supprimer le profil de chat codé en dur et le dériver de l'identité signée.
- Remplacer le store mémoire de révocation par Redis partagé fail-closed hors
  tests ; prouver deux instances et persistance après redémarrage logique.

## Task 3 — validation et scope serveur

- Créer `identity_v2.py` avec validation JWT et `InternalIdentity` stricte.
- Créer `retrieval_scope_v2.py` avec mapping rôle/droits/visibility,
  restrict-only et digest sans PII.
- Lier `scope_id`, `scope_digest=a1ed0fb1…` de l'artefact JSON canonique et
  allowlist dans le jeton, conserver `source_sha256=b55ef138…` pour le YAML
  LOT38, puis exiger leur concordance exacte avec l'artefact du package.
- Tester les égalités sub/jti, la borne d'expiration, issuer/audience externes,
  rotation immuable et `programme_version`.
- Centraliser le mapping de voie dans `collection_config.py`.
- Tester token absent/mal signé/expiré, identité 0.3, matière/niveau/voie/année,
  collection arbitraire et IDOR.

## Task 4 — migration PostgreSQL 003

- Écrire les tests de manifeste et d'objets attendus.
- Ajouter `003_profile_filtering.sql`, son rollback conditionnel et `HEAD`.
- Garder tenant, candidat, visibilité, année et version de programme à `NULL`
  sans backfill ; LOT42 seul les classifie.
- Étendre les validateurs de migration et l'adoption 002 → 003.
- Prouver application, rollback sans données, refus du rollback après
  enrichissement, puis réapplication.

## Task 5 — filtres du noyau et du store

- Faire porter le scope par `CandidateStore` et `retrieve_hybrid`.
- Étendre `RetrievalCandidate` avec les dimensions retournées par PostgreSQL.
- Écrire un prédicat partagé dense/lexical et des paramètres stricts.
- Vérifier chaque ligne post-DB ; toute incohérence fait échouer le canal.
- Adapter les tests unitaires existants sans affaiblir les invariants LOT40.

## Task 6 — endpoints, cache, CLI et évaluation

- Exiger jeton service + identité sur search/chat et warmup.
- Contrôler toutes les collections avant le premier retrieval.
- Partitionner les clés de warmup par scope et conserver l'absence de lecture
  du cache public.
- Faire refuser CLI/eval DB sans identité explicite.
- Tester révocation, cache empoisonné, `needs_review` et quarantaine.

## Task 7 — review scopée et fermeture des bypasses

- Dériver le scope review de l'identité signée et de l'artefact ; tenant et
  collection clients sont restrict-only.
- Tester l'IDOR document/chunk et des réponses ne révélant pas l'existence.
- Conserver `needs_review → reviewed` et ajouter uniquement la révocation
  `reviewed → quarantined`, sans réactivation implicite.
- Fermer `/search`, `/kb/*` et `/rag/*` dans Nginx production par `410`.
- Ajouter des tests de topologie interdisant leur re-publication.

## Task 8 — intégration réelle exhaustive

- Étendre la fixture PostgreSQL avec lignes positives et une mutation par
  dimension de scope.
- Tester les trois candidats et les deux matières.
- Tester dense, lexical, HTTP, IDOR et ordre de contrôle avant DB.
- Raccorder la suite au target Docker déjà obligatoire dans CI locale/GitHub.
- Vérifier zéro conteneur/volume LOT41 résiduel.

## Task 9 — revue, rapport et publication

- Lancer les suites ciblées, Ruff, mypy, cockpit lint/typecheck/build et
  `git diff --check`.
- Faire une revue indépendante du diff complet et corriger P0–P3.
- Créer `docs/reports/lot_41_profile_filter_enforcement.md` avec matrice de
  preuve et `GO_LIVE: NO_GO`.
- Lancer `bash scripts/ci-local.sh` au SHA final de code.
- Pousser la branche, ouvrir la PR vers `main`, attendre tous les checks,
  fusionner uniquement via PR, puis vérifier `main == origin/main`, CI
  post-fusion, worktree propre et aucune PR fonctionnelle ouverte.

## Critères de sortie

- `nexus-contracts==0.4.0`, ADR et snapshots concordants ;
- aucune route de retrieval sans identité autoritative ;
- aucune route historique de retrieval exposée en production ;
- client restrict-only et collection contrôlée avant DB ;
- prédicats dense/lexical identiques sur toutes les dimensions ;
- vérification post-DB fail-closed ;
- review tenant/collection-scopée et révocation immédiatement observable ;
- matrice candidats × matières et cas adverses verte sur PostgreSQL réel ;
- aucun verrou activé, aucun document réel lu, `GO_LIVE: NO_GO` maintenu ;
- CI locale et GitHub vertes sur le candidat fusionné.
