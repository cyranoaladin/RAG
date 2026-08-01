# LOT40 — Retrieval hybride pgvector

Date de vérification : 2026-08-01

## Verdict et identité de la preuve

- Base `main` vérifiée : `84821b240776bea74baebb078d3b7b5d4e29945a`.
- Candidat de code final relu et soumis à la CI intégrale :
  `4c8c2f80b18e75828207f64d7327efea9585f7cd`.
- Le présent commit documentaire vient nécessairement après ce SHA. Cette
  distinction évite une référence circulaire sans présenter le rapport comme un
  delta fonctionnel non vérifié.
- Première tête de PR contrôlée par GitHub :
  `e72b2e408629b6b31d987bd7940c49549ea8d272`.
- Branche vérifiée : `lot-40-hybrid-retrieval`.

LOT40: PASS_CANDIDATE

REVUE_INDÉPENDANTE: APPROVE_HIGH

GO_LIVE: NO_GO

`PASS_CANDIDATE` signifie que le candidat LOT40 satisfait les preuves locales
fraîches, la revue indépendante globale et les checks GitHub. Il ne signifie
encore ni fusion dans `main`, ni aptitude globale au go-live.

## Périmètre livré

LOT40 fournit dans `rag-engine` :

- la migration versionnée `002_hybrid_retrieval`, son rollback et un registre
  de migrations vérifié et atomique ;
- un pool PostgreSQL paresseux et borné ;
- les canaux dense HNSW et lexical GIN, leur fusion RRF, le rerank, la
  diversification MMR et les refus fail-closed ;
- un chemin de retrieval v2 commun aux endpoints et au CLI, avec visibilité
  `reviewed` et génération `/chat` maintenue verrouillée ;
- un test d'intégration sur PostgreSQL/pgvector réel et éphémère, incluant le
  cycle `001 → 002 → 001 → 002`, l'atomicité, les rôles, les plans SQL, le
  retrieval et le smoke HTTP ;
- le raccordement obligatoire de ce smoke à GitHub Actions et à la CI locale,
  avec tests de topologie et de propagation des échecs.

## Hors périmètre

- aucune évolution de `packages/contracts` ;
- aucun filtre serveur exhaustif d'identité, tenant, candidat ou année de
  LOT41 ;
- aucun corpus réel lu, qualifié, ingéré ou publié ;
- aucune activation de verrou de validation ou de production ;
- aucune génération OpenRouter ;
- aucune suppression des chemins historiques encore utilisés.

La base d'intégration ne contient qu'une fixture synthétique. `TARGET_SCALE`
vaut nominalement 45 000, mais l'univers cible admissible réellement inséré
compte 45 002 lignes : 82 seeds et 44 920 lignes bulk. S'y ajoutent exactement
4 500 lignes `needs_review`, 3 lignes à provenance incomplète et 6 750 lignes
hors collection, soit un sous-total de charge de 56 255 lignes. Enfin, les
collections auxiliaires ajoutent 260 lignes — 52 d'égalité, 205 d'égalité de
débordement et 3 de petit corpus — pour un total réel de 56 515 lignes insérées.
Cette fixture ne constitue pas une preuve de qualité d'un corpus pédagogique
réel.

## Artefacts de migration et image OCI

- Image immuable :
  `pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`.
- Head final relu : `002_hybrid_retrieval`.
- `001_rag_chunks_v2_schema.sql` :
  `sha256:c0ce69353bd04c87a9bf7adf885ebf9e915885b8e0b286faffc620b74cebc88c`.
- `002_hybrid_retrieval.sql` :
  `sha256:6fef12777291653611aa8b561709e2090b169b40629ce99acf0767ebb388f89d`.
- `002_hybrid_retrieval.down.sql` :
  `sha256:a4dda5729997a8d54a7a0790d94716ce3b9878e2959fe678d866414e5259bdf6`.

Le runner a vérifié le registre et les objets réels, puis les trois empreintes
ont été relues avec `sha256sum` sur le candidat. Le cycle s'est terminé au head
`002_hybrid_retrieval`.

## Preuves fraîches

Toutes les suites de cette section ont été exécutées après la dernière
correction sur le candidat de code
`4c8c2f80b18e75828207f64d7327efea9585f7cd`.

### Suites ciblées

Commande exécutée depuis `services/rag-engine` :

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/test_pgvector_v2_schema.py tests/test_pg_pool.py \
  tests/test_retrieval_hybrid_v2.py tests/test_retrieval_pg_v2.py \
  tests/test_retrieval_v2_endpoint.py tests/test_retrieval_v2_gate.py \
  tests/test_review_visibility.py tests/test_retrieval_v2_cli.py -q
```

Verdict : PASS, 405 tests collectés et exécutés. Répartition : 104 schéma, 39
pool, 82 cœur hybride, 90 accès PostgreSQL, 46 endpoint, 8 gate, 9 visibilité
et 27 CLI.

Commande réelle PostgreSQL :

```bash
make test-integration-hybrid
```

Verdict : PASS dans la CI intégrale, avec 7 tests pytest d'intégration et 28
marqueurs `PASS`. Les preuves incluent notamment : bootstrap réel `init.sql`
déjà au schéma 002 sans registre, adoption atomique des versions 001 et 002,
cycle complet, rollback atomique après les trois échecs injectés — adoption,
montée et descente —, head final 002, rôle applicatif non-superuser et lecture
seule, objets réels, rang 50 déterministe, sentinelle d'égalité HNSW, plans
GIN/HNSW, underfill sans scan global, retrieval réel, `/search` HTTP et `/chat`
verrouillé. Le temps du plan HNSW était de 68,465 ms ; il est informatif, sans
seuil normatif.

### Qualité complète de `rag-engine`

Commandes exécutées depuis `services/rag-engine` :

```bash
make lint
make typecheck
make test
```

- Ruff : PASS, `All checks passed!`.
- mypy : PASS, 43 fichiers source.
- pytest hors intégration : PASS, 1 053 tests collectés et exécutés.

Deux avertissements non bloquants ont été observés : dépréciation de `crypt`
dans passlib et incompatibilité déclarée par Requests entre ses versions de
`urllib3`/`chardet`/`charset_normalizer`. Aucun test n'a échoué.

### Garde-fous racine

```bash
bash scripts/check-governance-locks.sh
bash scripts/check-repository-hygiene.sh
YAML_PYTHON_BIN=services/rag-engine/.venv/bin/python \
  bash scripts/tests/test-ci-local-topology.sh
YAML_PYTHON_BIN=services/rag-engine/.venv/bin/python \
  NEXUS_CI_LOCAL_RUNNING=1 bash scripts/tests/test-ci-local-failsafe.sh
git diff --check main...HEAD
```

- verrous de gouvernance : PASS, 18 clés sur 18 ;
- hygiène du dépôt : PASS ;
- topologie CI : PASS, fixture canonique acceptée, 22 mutations refusées et
  graphe acyclique ;
- politique de protection de `main` : PASS, 31 tests sur 31 ;
- fail-safe CI : PASS, 44 contrôles sur 44 ;
- contrôle d'espaces du diff et scan strict des lignes ajoutées : PASS.

Aucun verrou de gouvernance n'a été activé.

### Correctifs issus des revues

La revue globale initiale a demandé cinq corrections : adoption du bootstrap
002 sans registre, protection des ressources Docker préexistantes, conservation
publique de `score_final`/`page` et de l'ordre MMR, warmup réellement inerte
quand le cache est désactivé, et aide `--sweep` honnête jusqu'au LOT43. Elles ont
été corrigées en TDD et relues. La revue qualité finale a ensuite signalé deux
P3 — docstring du warmup et preuve du refus 401 sans purge —, fermés par
`4c8c2f80b18e75828207f64d7327efea9585f7cd`.

Le reviewer indépendant `lot40_final_code_review` a relu `main...HEAD`, exécuté
139 tests ciblés, Ruff, mypy, les tests cockpit et une intégration pgvector
réelle. Verdict figé sur le candidat de code : `APPROVE`, confiance `HIGH`,
aucun finding P0, P1, P2 ou P3 ouvert. Les deux revues ciblées complémentaires
de spécification et de qualité ont également rendu `APPROVE/HIGH`.

Le scan prescrit des lignes ajoutées contre les chemins machine-locaux, les
clés et les DSN avec credentials est PASS. Les 39 tests de pool préservent les
valeurs runtime historiques des fixtures sans inscrire de secret en clair.

### CI locale intégrale

Commande interne exacte :

```bash
bash scripts/ci-local.sh
```

Elle a été lancée avec Node 22.22.0 et un wrapper exécutable temporaire qui
transmettait `python3.11` au binaire CPython 3.11.14 uv valide. Le wrapper vivait
hors dépôt, son environnement a été prévalidé par création d'un venv puis
supprimé après la preuve. Aucun fichier versionné n'a été adapté.

Verdict final : exit 0 en 692,02 s, résumé exact 13 PASS et 0 FAIL :

1. `packages/contracts` ;
2. `services/rag-pedago` — Ruff et mypy PASS, 1 751 tests PASS en 250,27 s ;
3. `services/rag-engine` — 1 053 tests hors intégration PASS puis
   `LOT40_HYBRID_INTEGRATION=PASS` ;
4. `services/cockpit` — lint, 29 tests Vitest, contrats et deux builds Next.js
   sur 7 pages PASS,
   zéro vulnérabilité npm signalée ;
5. `repository-hygiene` ;
6. `repository-hygiene-tests` ;
7. `ci-topology-tests` ;
8. `main-protection-policy-tests` ;
9. `governance-locks` ;
10. `taxonomy-validation` — 57 taxonomies, 0 erreur ;
11. `source-evidence-check` ;
12. `governance-guard-tests` — 16 sur 16 ;
13. `ci-failsafe-tests` — 44 sur 44.

Dans cette exécution intégrale, le temps informatif du plan HNSW était de
68,465 ms. Les propriétés normatives portaient sur l'index, le plan et le
nombre de lignes borné, pas sur ce temps.

Le préflight final a vérifié Node 22.22.0, CPython 3.11.14, les imports système
du build cockpit et la création d'un venv. Aucun contrôle n'a été ignoré ni
modifié.

### Checks GitHub de la PR

La draft PR `#83`, de `lot-40-hybrid-retrieval` vers `main`, a évalué la tête
`e72b2e408629b6b31d987bd7940c49549ea8d272`. Les deux runs déclenchés sur ce
même arbre sont terminés avec succès :

- push : run `30715764715` ;
- pull request : run `30715779465`.

Dans chacun, les six contextes protégés sont `SUCCESS` :
`packages/contracts`, `services/rag-pedago`, `services/rag-engine`,
`services/cockpit`, `governance locks guard` et `repository controls`. Le job
`services/rag-engine` a exécuté `make test-integration-hybrid` dans les deux
runs, respectivement en 6 min 59 s et 7 min 02 s. Le contrôle supplémentaire
GitGuardian est également PASS.

Le commit documentaire qui consigne ces résultats vient nécessairement après
la tête contrôlée. Il doit à son tour obtenir les six checks avant passage de la
PR en ready et fusion ; cette exigence évite de présenter une preuve circulaire.

## Nettoyage Docker

Le runner utilise un token propriétaire aléatoire de 128 bits, l'ID immuable du
conteneur et l'empreinte `label + CreatedAt` du volume. Il refuse les collisions
et substitutions avant tout montage ou nettoyage, puis détruit uniquement ses
ressources au moyen d'un `trap`. Les contrôles après la CI intégrale ont donné :

```text
LOT40_CONTAINERS=0
LOT40_VOLUMES=0
```

Le répertoire temporaire de la CI finale a été supprimé. Les sept stashes
historiques sont restés inchangés. Le conteneur utilisateur `rag_pgvector` a
conservé l'ID `5b3f88114af82cc5177553b32d9003a4d1b00bfaf8792c838b7813424e8c19a8`,
son `StartedAt` du 31 juillet et `RestartCount=0`.

## Matrice de preuve

| Contrôle | Responsable | Environnement | Artefact | Digest/SHA | Verdict |
|---|---|---|---|---|---|
| Schéma et cycle `001 → 002 → 001 → 002` | runner d'intégration LOT40 | PostgreSQL 16/pgvector éphémère | migrations, rollback et registre | empreintes SQL et digest OCI complets ci-dessus | PASS |
| Atomicité et moindre privilège | runner d'intégration LOT40 | rôle migration + rôle applicatif réel | échecs injectés, objets et privilèges | candidat de code complet ci-dessus | PASS |
| Retrieval dense, lexical, RRF, rerank et MMR | pytest ciblé + runner réel | Python 3.11 + PostgreSQL éphémère | 405 tests ciblés + 7 tests DB | candidat de code complet ci-dessus | PASS |
| Endpoints v2, CLI, review-only et chat verrouillé | pytest ciblé + smoke HTTP | modèles déterministes, aucun réseau de génération | tests endpoint/gate/visibilité/CLI + smoke | candidat de code complet ci-dessus | PASS |
| Qualité `rag-engine` | Ruff, mypy, pytest | venv Python 3.11 frais | 43 fichiers typés, 1 053 tests | candidat de code complet ci-dessus | PASS |
| Topologie et propagation du smoke | tests shell fail-closed | racine du worktree | 22 mutations de topologie + 44 contrôles fail-safe | candidat de code complet ci-dessus | PASS |
| Gouvernance et hygiène | garde-fous racine | worktree LOT40 | baseline 18 clés, racine suivie | SHA de base et candidat de code complets ci-dessus | PASS |
| CI locale intégrale | orchestrateur `ci-local.sh` | Node 22.22.0 + Python 3.11.14 + Docker | 13 cibles canoniques | candidat de code complet ci-dessus | PASS |
| Hygiène des fixtures | pytest, Ruff et scan prescrit | candidat final | 39 tests de pool et lignes ajoutées | candidat de code complet ci-dessus | PASS |
| Nettoyage des ressources | runner + relecture postérieure | Docker local | inventaire conteneurs/volumes LOT40 | 0 conteneur ; 0 volume | PASS |
| Revue indépendante `main...HEAD` | `lot40_final_code_review` | candidat de code final | diff LOT40 complet + 139 tests ciblés + DB réelle | `4c8c2f80b18e75828207f64d7327efea9585f7cd` | APPROVE/HIGH |
| Checks GitHub | GitHub Actions | draft PR `#83` vers `main` | six contextes protégés + smoke réel dans deux runs | `e72b2e408629b6b31d987bd7940c49549ea8d272` | PASS |
| Fusion | mainteneur | PR `#83` vers `main` | SHA fusionné et équivalence des arbres | non encore disponible | PENDING |

Les revues de réalisation des Tasks 1 à 9 ont été conduites par incréments de
spécification et de qualité, avec commits correctifs séparés. La revue globale
Task 11 ci-dessus est distincte et couvre le diff complet.

## Risques et portes restantes

- **Task 11** : checks du commit documentaire final, passage ready, fusion et
  contrôle post-merge restent obligatoires avant de déclarer LOT40
  `MERGED/PASS`.
- **LOT41** : imposer l'identité et les filtres serveur exhaustifs ; aucun
  utilisateur réel ne doit dépendre du seul filtrage actuel.
- **LOT41A** : obtenir l'autorisation humaine GitHub pour l'environnement de
  validation isolé avant toute lecture ou écriture de document réel.
- **LOT42** : qualifier chaque ressource, prouver `quality → gate → review` sur
  100 % du périmètre et publier le corpus pilote dans la DB de validation.
- **LOT43** : figer le snapshot, la baseline reproductible, la sécurité, la
  performance et la calibration sur le corpus pilote final.
- Les avertissements passlib/Requests et la dépendance cockpit Recharts 2
  dépréciée sont des dettes d'environnement/dépendances à traiter sans les
  confondre avec une preuve fonctionnelle du lot.

En conséquence, le candidat LOT40 est approuvé pour publication par PR, mais
le projet complet n'est pas prêt pour un go-live public.
