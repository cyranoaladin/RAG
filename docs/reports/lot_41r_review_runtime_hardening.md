# Rapport LOT41R — Durcissement runtime et review authentifiée

Date : 2026-08-02

**Verdict : `GO_LIVE: NO_GO`**

## État du lot

- Base confirmée par `git merge-base main HEAD` : `f545b15`.
- Branche : `lot-41r-review-runtime-hardening`.
- PR LOT41R : à ouvrir après le commit documentaire final ; non fusionnée au
  moment de ce relevé Task9.
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
| `b6bdf3c` | protections CSRF et validation stricte des formats JSON Schema |
| `998c984` | origine publique canonique des mutations derrière reverse proxy |

Le SHA d'implémentation final vérifié avant le présent commit documentaire est
`998c9847e1819b64f6f80b4e0854c0365aba7e21`. Le rapport ne prétend pas contenir
son propre SHA.

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
et la corrélation stricte entre cible/décision demandées et réponse moteur. La
revue complète a ensuite détecté deux frontières manquantes : la mutation
n'imposait pas encore une origine navigateur canonique et Ajv ignorait le
format `date-time`. Les correctifs imposent désormais une origine HTTPS pure
configurée par `NEXUS_COCKPIT_PUBLIC_ORIGIN`, sans faire confiance aux en-têtes
du reverse proxy, exigent `application/json` et activent `ajv-formats` dans les
validateurs générés. L'origine publique du smoke et du runbook est la même
valeur canonique.

## Preuves finales Task9

La vérification finale a été exécutée sur le SHA d'implémentation ci-dessus,
avec Node.js 22.23.1 et CPython 3.11.14. Le wrapper Python temporaire utilisé
pour contourner un lien système 3.11 cassé est resté hors dépôt.

| Périmètre | Résultat final |
| --- | --- |
| `packages/contracts` | 93 tests réussis ; Ruff et mypy réussis |
| `services/rag-pedago` | 1 751 tests réussis ; Ruff et mypy réussis |
| `services/rag-engine` | 1 178 tests non-intégration réussis, 15 tests d'intégration désélectionnés ; Ruff et mypy réussis |
| smoke hybride PostgreSQL/pgvector réel | `LOT40_HYBRID_INTEGRATION=PASS`, y compris le runtime aplati et la review scopée |
| `services/cockpit` | 19 fichiers et 168 tests réussis ; ESLint, TypeScript et build Next.js 16.2.12 réussis |
| dépendances Cockpit | `npm audit` : 0 vulnérabilité |
| gouvernance | 18 clés identiques à la baseline ; aucun verrou activé |
| taxonomie | 57 fichiers validés, 0 erreur ; 15 fichiers explicitement `PREMIER JET` |
| tests des garde-fous | 16/16 gouvernance et 44/44 CI fail-safe réussis |
| CI locale racine | **13 cibles réussies, 0 échec** |
| diff Git | `git diff main...HEAD --check` réussi |
| secrets | `gitleaks git . --log-opts=main..HEAD --redact --no-banner` : 12 commits analysés, aucune fuite |
| revue indépendante finale | **APPROVE**, confiance élevée, aucun constat P0, P1, P2 ou P3 |

Commande de preuve globale exécutée depuis la racine, avec les exécutables
Node.js et Python 3.11 placés en tête de `PATH` :

```bash
bash scripts/ci-local.sh
```

Les seuls avertissements observés sont la dépréciation de `crypt` via
Passlib, une incompatibilité déclarative de versions `requests` dans
l'environnement de test et la dépréciation de Recharts 2.x. Ils ne masquent
aucun échec ; la validation `date-time` Ajv qui manquait avant correction est
désormais active et testée.

La publication de la branche, l'ouverture de la PR et les checks GitHub sont
des opérations postérieures à ce relevé local et ne sont donc pas pré-déclarés
comme réussis. Même après leur réussite, la conclusion fonctionnelle demeure
`GO_LIVE: NO_GO` tant que la revue substantielle du corpus, le LOT41A et les
lots 42 à 47 ne sont pas clos avec leurs propres preuves.
