# Rapport LOT41R — Durcissement runtime et review authentifiée

Date : 2026-08-02

**Verdict : `GO_LIVE: NO_GO`**

## État du lot

- Base confirmée par `git merge-base main HEAD` : `f545b15`.
- Branche : `lot-41r-review-runtime-hardening`.
- PR LOT41R : non ouverte et non fusionnée au moment de ce relevé Task8.
- Périmètre : correctifs post-review des LOT40/LOT41, contrat de review partagé,
  routes BFF de review et reprise contrôlée après rejet Redis.
- Verrous de gouvernance : inchangés ; aucun `*_allowed` n'est activé par ce lot.

LOT41R ne constitue ni une revue réelle du corpus, ni une autorisation du
LOT41A, ni une preuve d'aptitude au go-live. Les LOT42 à LOT47 restent ouverts.

## Sources P1 et causes racines

### 1. Runtime ingestor aplati — PR #83, commit revu `428fd5382a`

Le Dockerfile ingestor v2 copie le contenu de `src/ingestor` directement sous
`/app` et démarre `uvicorn api:app`. Dans ce layout, `retrieval_pg_v2` était
chargé comme module top-level mais importait `ingestor.retrieval_hybrid_v2`,
package absent de l'image. La cause racine était donc une divergence entre la
topologie d'import des tests et celle réellement déployée.

Correction : imports explicites compatibles avec le mode package et le mode
top-level dans les deux modules traversés, plus un test qui importe `api` avec
le seul layout aplati du conteneur.

### 2. Opérations de review inaccessibles — PR #84, commit revu `6e955ff416`

Le moteur exigeait désormais le credential machine BFF et une identité interne
signée, alors que le Cockpit n'exposait aucune route `/review/v2` correspondante.
Le token reviewer direct ne pouvait plus satisfaire la frontière moteur et
aucun parcours humain supporté ne remplaçait cet accès.

Correction : `GET /api/review/queue` et `POST /api/review/decide` authentifient
une session Auth.js `reviewer|admin`, appliquent le scope signé, enrichissent la
décision avec le tenant de l'identité et appellent le moteur avec des credentials
séparés. Les payloads et réponses sont validés avant et après la frontière.

### 3. Promesse Redis rejetée mémorisée — P1 additionnelle de la PR #84

`configuredStore()` conservait définitivement la première promesse de
connexion. Si cette tentative était rejetée, tous les appels futurs réutilisaient
la même promesse rejetée jusqu'au redémarrage du Cockpit. La cause racine était
l'absence d'éviction conditionnelle de la tentative échouée.

Correction : tous les appelants concurrents partagent et refusent la même
tentative, puis une tentative ultérieure peut repartir. L'éviction compare
l'identité de la promesse, de sorte qu'un rejet tardif ne peut pas effacer une
connexion plus récente.

## Contrat canonique

`nexus-contracts` passe à la version **0.5.0**. Les modèles Python, les cinq
schémas JSON racine et les types/validateurs TypeScript générés couvrent la
queue, la décision navigateur, la décision moteur et leurs réponses. Le tenant
n'est jamais une autorité navigateur et le champ libre `reason` est rejeté.

L'[ADR-0023](../adr/ADR-0023-review-bff-et-durcissement-runtime.md) documente
l'extension additive du contrat, les frontières navigateur/BFF/moteur et
l'absence de migration de données ou d'activation de gouvernance.

## Commits d'implémentation consignés

| SHA | Objet |
| --- | --- |
| `f5aedb0` | cadrage du durcissement runtime LOT41R |
| `82f79fb` | plan d'implémentation vérifiable |
| `4452ff4` | compatibilité du runtime ingestor aplati |
| `66c3ba3` | contrat de review canonique 0.5.0 et ADR-0023 |
| `46b1725` | consommation du contrat partagé par le moteur |
| `d25152b` | appels moteur de review bornés côté Cockpit |
| `2f70305` | route BFF de queue authentifiée |
| `02c02a1` | route BFF de décision authentifiée |
| `75dd274` | reprise Redis après une connexion rejetée |

Le présent rapport ne prétend pas contenir son propre SHA. La Task9 consignera
le SHA d'implémentation final vérifié avant son commit documentaire final.

## Cycles RED/GREEN et vérifications ciblées

Le cycle RED initial a reproduit `ModuleNotFoundError: No module named
'ingestor'` depuis le layout Docker aplati. Les cycles suivants ont d'abord
échoué sur l'absence des modèles/schémas de review, l'absence des routes BFF et
la promesse Redis rejetée persistante, avant les implémentations minimales.

Résultats ciblés obtenus pendant les tâches, avec des commandes copiables
depuis la racine du dépôt. Le `.venv` référencé est l'environnement Python du
service/dépôt préparé par `make install` ; aucun chemin absolu local n'est
requis.

| Tâche | SHA | Commande exacte exécutée | Résultat et code de sortie |
| --- | --- | --- | --- |
| Task1 — runtime aplati | `4452ff4` | `(cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_ingestor_flattened_runtime.py tests/test_retrieval_pg_v2.py tests/test_retrieval_scope_v2.py -q)` | 134 tests réussis ; exit 0 |
| Task2 — contrat | `66c3ba3` | `PYTHONPATH=packages/contracts/src services/rag-engine/.venv/bin/python -m pytest packages/contracts/tests -q` | 93 tests réussis ; exit 0 |
| Task3 — moteur review | `46b1725` | `(cd services/rag-engine && PYTHONPATH=src:../../packages/contracts/src .venv/bin/pytest tests/test_review_v2.py tests/test_lot41_review_scope.py tests/integration/test_lot40_hybrid_pgvector.py -q -m 'not integration')` | 32 tests réussis ; exit 0 |
| Task4 — client moteur ciblé | `d25152b` | `(cd services/cockpit && npm test -- --run src/app/api/_engine.test.ts)` | 6 tests réussis ; exit 0 |
| Task4 — bundle Cockpit au même SHA | `d25152b` | `(cd services/cockpit && npm test -- --run)` | 76 tests réussis ; exit 0 |
| Task5 — queue BFF | `2f70305` | `(cd services/cockpit && npm test -- --run src/app/api/review/queue/route.test.ts src/server/bff-auth.test.ts)` | 43 tests réussis ; exit 0 |
| Task6 — décision BFF | `02c02a1` | `(cd services/cockpit && npm test -- --run src/app/api/review src/app/api/_engine.test.ts src/server/bff-auth.test.ts)` | 89 tests réussis ; exit 0 |
| Task7 — Redis | `75dd274` | `(cd services/cockpit && npm test -- --run src/server/revocation-store.redis.test.ts src/server/revocation-store.test.ts src/server/bff-auth.test.ts)` | 18 tests réussis ; exit 0 |

Les revues indépendantes intermédiaires ont notamment fait ajouter la
préservation d'un préfixe de chemin dans l'URL moteur, l'en-tête
`Cache-Control: private, no-store, max-age=0` sur toutes les réponses de review
et la corrélation stricte entre cible/décision demandées et réponse moteur.

## Preuves Task8 et preuves finales restantes

La Task8 vérifie le format des trois documents, les références
`/api/review/*`, la version 0.5.0 et les 18 verrous de gouvernance inchangés.

Les preuves exhaustives suivantes relèvent de la Task9 et sont **en attente** :

- suites complètes contrats, `rag-engine` et Cockpit ;
- Ruff, mypy, ESLint, TypeScript et build Next.js ;
- import frais du runtime aplati et CI locale racine ;
- contrôle final du diff, `gitleaks`, revue indépendante complète ;
- push, ouverture de PR et statut des checks GitHub.

Aucun de ces contrôles en attente n'est déclaré `PASS` dans ce rapport Task8.
Même après leur réussite, la conclusion fonctionnelle restera
`GO_LIVE: NO_GO` tant que la revue substantielle du corpus, le LOT41A et les
lots 42 à 47 ne sont pas clos avec leurs propres preuves.
