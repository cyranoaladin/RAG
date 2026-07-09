# LOT 26.3 — Sécurisation v2 centralisée + rôles (ADR-0014)

**Date** : 2026-07-10
**Issue pilotage** : #47
**Branche** : `codex/lot26-3-security-v2-roles`
**PR** : #51
**Statut** : draft prête pour revue lead après corrections

---

## Objectif du lot

Mettre en place la sécurisation centralisée côté `rag-engine` pour les endpoints v2 avec rôles explicites, sans déploiement production, sans SSH, sans secret ajouté ou modifié, sans changement cockpit, sans changement LOT 26.4+ et sans modification des verrous gouvernance.

## Travaux réalisés

1) Centralisation de la sécurité v2

- Création de `services/rag-engine/src/ingestor/security_v2.py`.
- Définition des rôles `admin`, `reviewer`, `teacher`, `ingest_agent`, `student`.
- Remplacement des logiques d’authentification locales des endpoints v2 par le module central.

2) `/search/v2` — visibilité revue unifiée

- Endpoint `/search/v2` passe par `SecurityRole.admin/reviewer/teacher/ingest_agent/student`.
- Filtre SQL appliqué systématiquement : `review_status = 'reviewed'`.
- La règle de visibilité est identique pour tous les rôles.

3) Endpoints de workflow v2

- `/ingest/v2` conservé pour ingestion fonctionnelle.
- `/review/v2/queue` : rôle requis `admin`, `reviewer`, `teacher`.
- `/review/v2/decide` : rôle requis `admin`, `reviewer`.

4) Tests de sécurité et visibilité

- Ajustements ciblés sur `services/rag-engine/tests/test_security_v2.py` et `services/rag-engine/tests/test_review_visibility.py` (complété par `test_retrieval_v2_endpoint.py`, `test_review_v2.py`).
- Invariant `needs_review` : accessible uniquement via la queue review.

5) Références techniques

- `SecurityRole` + garde-fou fail-closed si rôles requis non configurés.
- Démonstration de la logique par tests sur rôles et SQL/visibility.

## Corrections post-revue automatisée

- Alias multiples par rôle acceptés : reviewer (`RAG_REVIEWER_TOKEN`, `REVIEWER_API_TOKEN`) et ingest_agent (`RAG_INGEST_AGENT_TOKEN`, `INGESTOR_API_TOKEN`, `INGEST_AUTH_TOKEN`).
- Collision de tokens entre deux rôles détectée et bloquée en fail-closed `503`, sans exposer le token.
- Allowlist ingestion : par défaut, seule l'IP peer `request.client.host` est fiable.
- Headers forwarded utilisés uniquement si le peer appartient aux CIDR de proxy de confiance configurés via `INGESTOR_TRUSTED_PROXY_CIDRS`; depuis le round 4, `X-Real-IP` est ignoré côté application et seul `X-Forwarded-For` anti-spoof est utilisé derrière proxy trusted.
- Fail-closed `403` si `INGESTOR_IP_ALLOWLIST` est configurée mais qu'aucune IP exploitable n'est disponible.
- Manifests/docs prod mis à jour pour câbler uniquement les noms de variables des tokens de rôles v2.
- Unicité des tokens de rôles documentée : les alias d'un même rôle peuvent partager une valeur, mais une collision entre rôles distincts bloque en fail-closed `503`.
- `_extract_token` mort supprimé de `review_v2_endpoint.py`.
- Test fail-closed reviewer restauré en comportement réel.
- Test isolation corrigé avec `monkeypatch.setenv`.
- Assignation `actor` inutilisée supprimée dans `/search/v2`.
- `/review/v2/queue` borne `limit` et `offset` via validation FastAPI.

## Vérifications

### Validation complète demandée (lot 26.3)

```bash
cd services/rag-engine
pytest -q tests/test_security_v2.py tests/test_retrieval_v2_endpoint.py tests/test_review_v2.py tests/test_review_visibility.py
make test
cd ../..
bash scripts/check-governance-locks.sh
bash scripts/tests/test-governance-locks.sh
bash scripts/ci-local.sh
```

Résultats enregistrés dans `/tmp/lot26_3_logs/*` :

- `pytest tests/test_security_v2.py tests/test_retrieval_v2_endpoint.py tests/test_review_v2.py tests/test_review_visibility.py` : PASS.
- `make test` : PASS (`make test exit=0`).
- `bash scripts/check-governance-locks.sh` : PASS (`OK: all governance locks match baseline`).
- `bash scripts/tests/test-governance-locks.sh` : PASS (`16 passed, 0 failed, 16 total`).
- `bash scripts/ci-local.sh` : PASS (`Total: 7 passed, 0 failed`).

### Conformité métier du lot

- `/search/v2 reviewed-only` pour **tous** les rôles.
- `needs_review` visible uniquement via `/review/v2/queue`.
- `teacher` peut lire la queue mais **ne peut pas** décider.
- `admin` et `reviewer` peuvent décider via `/review/v2/decide`.
- `ingest_agent` ne peut pas accéder aux routes review (`/review/v2/*`).
- `student` ne peut pas accéder à ingestion ni review.

### Vérification de périmètre

- Base locale confirmée : `main` contient le merge de `#50`.
- Aucun déploiement production.
- Aucun SSH.
- Aucun secret ajouté ou modifié.
- Aucun verrou gouvernance modifié.
- Modifications runtime limitées à `services/rag-engine`.
- Modifications docs/manifests prod versionnées limitées aux noms de variables et consignes d'exploitation.
- Aucun changement cockpit.
- Aucun changement LOT 26.4+.

## Validations finales post-revue automatisée

- pytest ciblé (`tests/test_security_v2.py`, `tests/test_retrieval_v2_endpoint.py`, `tests/test_review_v2.py`, `tests/test_review_visibility.py`) : PASS, 49 passed.
- `make test` depuis `services/rag-engine` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Invariant `/search/v2` : PASS, aucune réintroduction de `review_status IN ('reviewed', 'needs_review')` dans `retrieval_v2_endpoint.py`.
- Marqueurs de conflit : PASS, aucun marqueur réel `<<<<<<<` / `>>>>>>>` dans le périmètre inspecté ; seules des lignes séparatrices markdown historiques `==============================` sont remontées dans d'anciens rapports.

## Corrections post-revue automatisée — round 2

- Headers forwarded ignores par defaut : `X-Forwarded-For` et `X-Real-IP` ne sont utilises que si le peer direct appartient aux CIDR configures dans `INGESTOR_TRUSTED_PROXY_CIDRS`.
- Allowlist ingestion maintenue fail-closed : si `INGESTOR_IP_ALLOWLIST` est configuree et qu'aucune IP fiable n'est disponible, la requete est rejetee en `403` sans exposer IP ni CIDR.
- Unicite des tokens de roles documentee : alias autorises au sein d'un meme role, collision interdite entre roles distincts et bloquee en `503`.
- Perimetre du lot clarifie : aucun deploiement production, aucun SSH, aucun secret, aucun verrou gouvernance, aucun cockpit, aucun LOT 26.4+.
- `/review/v2/queue` valide `limit` et `offset` avec bornes FastAPI (`limit` 1..500, `offset` >= 0).

## Validations finales post-revue automatisée — round 2

- pytest ciblé (`tests/test_security_v2.py`, `tests/test_retrieval_v2_endpoint.py`, `tests/test_review_v2.py`, `tests/test_review_visibility.py`) : PASS, 55 passed.
- `make test` depuis `services/rag-engine` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Invariant `/search/v2` : PASS, aucune réintroduction de `review_status IN ('reviewed', 'needs_review')` dans `retrieval_v2_endpoint.py`.
- Marqueurs de conflit : PASS, aucun marqueur réel `<<<<<<<` / `>>>>>>>` dans le périmètre inspecté.

## Corrections post-revue automatisée — round 3

- `INGESTOR_TRUSTED_PROXY_CIDRS` est transmis au conteneur `ingestor` via `docker-compose.prod.yml`.
- Test compose prod étendu pour vérifier le câblage de `INGESTOR_TRUSTED_PROXY_CIDRS`.
- XFF durci contre le spoof : `X-Forwarded-For` et `X-Real-IP` sont ignorés depuis un peer non trusted.
- Depuis le round 4, `X-Real-IP` est ignoré côté application tant qu'un template proxy versionné ne prouve pas sa réécriture stricte.
- `X-Forwarded-For` n'est plus lu naïvement en première position : la chaîne est parcourue de droite à gauche en retirant les proxies de confiance.
- Ne pas utiliser `proxy_add_x_forwarded_for` sans stratégie anti-spoof côté application ou sans réécriture stricte du header par le proxy.
- Allowlist ingestion maintenue fail-closed si aucune IP fiable n'est disponible.

## Validations finales post-revue automatisée — round 3

- pytest ciblé (`tests/test_security_v2.py`, `tests/test_retrieval_v2_endpoint.py`, `tests/test_review_v2.py`, `tests/test_review_visibility.py`) : PASS, 56 passed.
- `make test` depuis `services/rag-engine` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Invariant `/search/v2` : PASS, aucune réintroduction de `review_status IN ('reviewed', 'needs_review')` dans `retrieval_v2_endpoint.py`.
- Marqueurs de conflit : PASS, aucun marqueur réel `<<<<<<<` / `>>>>>>>` dans le périmètre inspecté.

## Corrections post-revue automatisée — round 4

- `X-Real-IP` ignoré côté application sauf preuve future de réécriture stricte par un template proxy versionné et testé.
- Authentification évaluée avant l'allowlist IP pour éviter un oracle IP sur requêtes non authentifiées ou token invalide.
- `X-API-Token` vide ou whitespace-only ne bloque plus le fallback vers `Authorization`.
- Tokens v2 câblés aussi dans `infra/docker-compose.yml`, utilisé par `infra/scripts/provision-prod.sh`.
- `provision-prod.sh` génère et écrit les noms de variables v2 attendus sans valeur versionnée.
- Tests ajoutés pour X-Real-IP ignoré, oracle allowlist, fallback auth, compose par défaut et provision.

## Validations finales post-revue automatisée — round 4

- pytest ciblé (`tests/test_security_v2.py`, `tests/test_retrieval_v2_endpoint.py`, `tests/test_review_v2.py`, `tests/test_review_visibility.py`) : PASS, 61 passed.
- `make test` depuis `services/rag-engine` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Invariant `/search/v2` : PASS, aucune réintroduction de `review_status IN ('reviewed', 'needs_review')` dans `retrieval_v2_endpoint.py`.
- Marqueurs de conflit : PASS, aucun marqueur réel `<<<<<<<` / `>>>>>>>` dans le périmètre inspecté.

## Corrections post-revue automatisée — round 5

- `X-Real-IP` reste ignoré côté application.
- Authentification vérifiée avant l'allowlist IP.
- `X-API-Token` vide n'empêche pas le fallback vers `Authorization`.
- Tokens v2 transmis dans tous les chemins de déploiement livrés.
- Un peer trusted sans chaîne `X-Forwarded-For` démontrant une IP cliente est désormais rejeté en fail-closed, même si l'adresse du proxy appartient aussi à l'allowlist.
- Test de non-régression ajouté pour le proxy trusted sans XFF fiable.
- Ordre chronologique des rounds de validation rétabli dans ce rapport.

## Validations finales post-revue automatisée — round 5

- pytest ciblé (`tests/test_security_v2.py`, `tests/test_retrieval_v2_endpoint.py`, `tests/test_review_v2.py`, `tests/test_review_visibility.py`) : PASS, 62 passed.
- `make test` depuis `services/rag-engine` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS, 18 clés vérifiées.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Invariant `/search/v2` : PASS, aucune réintroduction de `review_status IN ('reviewed', 'needs_review')` dans `retrieval_v2_endpoint.py`.
- Marqueurs de conflit : PASS, aucun marqueur réel `<<<<<<<` / `>>>>>>>` dans le périmètre inspecté.

## Corrections post-revue automatisée — round 6

- Proxy trusted sans XFF fiable rejeté fail-closed, y compris lorsque XFF ne contient que des adresses de proxies trusted.
- Rapport LOT 26.3 remis et conservé en ordre chronologique strict.
- README v2/legacy séparé entre tokens de rôles statiques et profil-token HMAC.

## Validations finales post-revue automatisée — round 6

- pytest ciblé : PASS, 63 passed.
- `make test` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS, 18 clés vérifiées.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Grep invariant `/search/v2` : PASS.
- Grep conflits : PASS.

## Corrections post-revue automatisée — round 7

- `/search/v2` échoue en fail-closed `503` si `nexus_contracts.embedding_utils.format_query` est indisponible ; aucun fallback local `.strip()` ne subsiste.
- Les tokens reçus sont comparés aux tokens configurés via `hmac.compare_digest`, sans journalisation ni exposition des valeurs.
- `_ROLE_TOKEN_ENV` est utilisé comme source unique et ordonnée des rôles évalués par `_match_role`.
- Un test XFF réaliste couvre la chaîne client non trusted suivie d'un proxy trusted.

## Validations finales post-revue automatisée — round 7

- pytest ciblé : PASS, 67 passed.
- `make test` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS, 18 clés vérifiées.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Grep invariant `/search/v2` : PASS.
- Grep conflits : PASS.

## Corrections post-revue automatisée — round 8

- Tokens v2 transmis aussi dans `docker-compose.v2.yml` et le chemin `make v2-up`.
- Isolation des tokens de test via `monkeypatch` dans `test_review_visibility.py`.
- `INGESTOR_TRUSTED_PROXY_CIDRS` explicitement invalide échoue en fail-closed `503` lorsqu'aucun CIDR valide n'est disponible.
- Tests de non-régression ajoutés pour les trois chemins de déploiement livrés, le provisionnement, l'isolation d'environnement et la validation trusted-proxy.

## Validations finales post-revue automatisée — round 8

- pytest ciblé : PASS, 71 passed.
- `make test` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS, 18 clés vérifiées.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Grep invariant `/search/v2` : PASS.
- Grep conflits : PASS.
- `git diff --check` : PASS.

## Corrections post-revue automatisée — round 9

- `token_hash()` calcule désormais le hash sur le token complet avant troncature d'affichage.
- Les calculs de fingerprint dupliqués dans `ingest_v2_endpoint.py` et l'ancien helper inutilisé de `ingest_v2.py` sont supprimés au profit de `security_v2.token_hash()`.
- La comparaison des tokens encode les opérandes en UTF-8 et rejette les entrées non comparables sans erreur `500`.
- L'assertion compose vérifie une référence `${VARIABLE}` complète, y compris les syntaxes avec valeur par défaut et le fallback imbriqué d'`INGESTOR_API_TOKEN`.
- Tests de non-régression ajoutés pour le hash complet, les tokens non ASCII, le fingerprint de provenance partagé et les références Compose.

## Validations finales post-revue automatisée — round 9

- pytest ciblé : PASS, 91 passed.
- `make test` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS, 18 clés vérifiées.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Grep invariant `/search/v2` : PASS.
- Grep conflits : PASS.
- Grep hash partiel `token[:8]` : PASS.
- `git diff --check` : PASS.

## Corrections post-revue automatisée — round 10

- `X-Forwarded-For` contenant une entrée malformée est rejeté en fail-closed.
- Les entrées XFF vides rendent la chaîne non fiable.
- Le legacy `/ingest` utilise la résolution IP durcie partagée, sans changer sa sémantique d'authentification.
- La documentation `README-PROD.md` clarifie la garantie partagée des chemins `/ingest` et `/ingest/v2`.
- Les tests legacy ciblent `_enforce_security`, niveau commun aux routes legacy protégées, afin de valider l'ordre auth/allowlist et la résolution IP sans déclencher les traitements métier d'ingestion.

## Résultats round 10

- pytest ciblé : PASS, 113 passed.
- `make test` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS, 18 clés vérifiées.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Grep invariant `/search/v2` : PASS.
- Grep conflits : PASS.
- Grep logique XFF naïve : PASS.
- `git diff --check` : PASS.
- Rendu `docker compose -f infra/docker-compose.v2.yml config` : PASS avec valeurs factices locales.

## Corrections post-revue automatisée — round 11

- Les routes legacy `/admin/*` sont separees des tokens d'ingestion via `LEGACY_ADMIN_API_TOKEN`.
- La documentation interdit la reutilisation des tokens d'ingestion sur les routes admin legacy.
- Le provisionnement prod genere et transmet un `LEGACY_ADMIN_API_TOKEN` distinct.
- `INGESTOR_TRUSTED_PROXY_CIDRS` n'est plus laisse vide par le provisioning lorsque l'allowlist applicative est configuree.
- Le preflight prod verifie la presence, le format et la separation des tokens admin legacy et ingestion.
- Des tests de non-regression couvrent le guard admin, les compose et le provisioning.

## Résultats round 11

- pytest ciblé : PASS, 145 passed.
- `make test` : PASS, exit 0.
- `bash scripts/check-governance-locks.sh` : PASS, 18 clés vérifiées.
- `bash scripts/tests/test-governance-locks.sh` : PASS, 16 passed, 0 failed.
- `bash scripts/ci-local.sh` : PASS, 7 passed, 0 failed.
- Grep invariant `/search/v2` : PASS.
- Grep conflits : PASS.
- Grep isolation admin legacy : PASS.
- Grep provisioning trusted proxy vide : PASS.
- `git diff --check` : PASS.
- Rendu `docker compose -f infra/docker-compose.v2.yml config` : PASS avec valeurs factices locales.

## Corrections post-revue automatisée — round 12

- Token UI du stack `make v2-up` aligné sur le token effectif accepté par l'ingestor.
- Clients Makefile v2 (`v2-eval`, `v2-stats`) alignés sur `INGESTOR_API_TOKEN` avec fallback `API_SECRET_KEY` ; le smoke legacy utilisait déjà le token d'ingestion effectif.
- Tests de non-régression ajoutés pour le cas `API_SECRET_KEY != INGESTOR_API_TOKEN` et pour le fallback historique.

## Résultats round 12

- pytest ciblé : PASS, 100 passed.
- `make test` : PASS, exit 0.
- `check-governance-locks` : PASS, 18 clés vérifiées.
- `test-governance-locks` : PASS, 16 passed, 0 failed.
- `ci-local.sh` : PASS, 7 passed, 0 failed.
- `git diff --check` et greps d'invariants : PASS.
- Rendu `docker compose -f infra/docker-compose.v2.yml config` : PASS; `RAG_API_TOKEN` et `INGESTOR_API_TOKEN` valent tous deux `ingestor-dummy` avec des valeurs factices distinctes.

## Corrections post-revue automatisée — round 13

- Preflight production renforcé : `LEGACY_ADMIN_API_TOKEN` doit être distinct de `RAG_ADMIN_TOKEN`, `INGESTOR_API_TOKEN` et `INGEST_AUTH_TOKEN`.
- Validation de format 64-hex ajoutée pour `RAG_ADMIN_TOKEN`.
- Tests de non-régression ajoutés pour empêcher la réutilisation du token admin v2 sur les routes admin legacy.

## Résultats round 13

- pytest ciblé : PASS, 119 passed.
- `make test` : PASS, exit 0.
- `check-governance-locks` : PASS, 18 clés vérifiées.
- `test-governance-locks` : PASS, 16 passed, 0 failed.
- `ci-local.sh` : PASS, 7 passed, 0 failed.

## Corrections post-revue automatisée — round 14

- Documentation `/admin/*` corrigée : les routes legacy admin utilisent `LEGACY_ADMIN_API_TOKEN`, pas les tokens d'ingestion.
- Preflight production renforcé : collisions inter-rôles v2 rejetées avant déploiement.
- Aliases intra-rôle conservés pour reviewer (`RAG_REVIEWER_TOKEN` / `REVIEWER_API_TOKEN`) et ingest-agent (`RAG_INGEST_AGENT_TOKEN` / `INGESTOR_API_TOKEN` / `INGEST_AUTH_TOKEN`).
- Tests de non-régression ajoutés pour collisions inter-rôles et aliases autorisés.

## Résultats round 14

- pytest ciblé : PASS, 126 passed.
- `make test` : PASS, exit 0.
- `check-governance-locks` : PASS, 18 clés vérifiées.
- `test-governance-locks` : PASS, 16 passed, 0 failed.
- `ci-local.sh` : PASS, 7 passed, 0 failed.

## Corrections post-revue automatisée — round 15

- Preflight production renforcé : chaque token v2 configuré doit être un token 64-hex.
- Aliases intra-rôle conservés uniquement avec des valeurs 64-hex.
- Provisioning prod corrigé : `INGESTOR_TRUSTED_PROXY_CIDRS` ne fait plus confiance à toute la plage `172.16.0.0/12`.
- Default trusted proxy restreint à loopback et, si détectable, au peer Docker exact en `/32`.

## Résultats round 15

- pytest ciblé : PASS, 131 passed.
- `make test` : PASS, exit 0.
- `check-governance-locks` : PASS, 18 clés vérifiées.
- `test-governance-locks` : PASS, 16 passed, 0 failed.
- `ci-local.sh` : PASS, 7 passed, 0 failed.
