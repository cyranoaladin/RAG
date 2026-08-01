# LOT40 — Retrieval hybride pgvector

Date de vérification : 2026-08-01

## Verdict et identité de la preuve

- Base `main` vérifiée : `84821b240776bea74baebb078d3b7b5d4e29945a`.
- Candidat final avant le présent commit documentaire :
  `973e00b59c20b1ce399d96b7ef5dee3f5bba3aa4`.
- Tête de la preuve fonctionnelle et de la CI intégrale :
  `74a3dea70b7ab8bed1874b3d269b8bb88c43e2df`. Les seuls deltas de code jusqu'au
  candidat final sont deux micro-correctifs test-only dans
  `tests/test_pg_pool.py` ; ils ne modifient aucun code de production et
  possèdent leurs preuves fraîches ci-dessous.
- Le SHA ci-dessus évite une référence circulaire : la Task 11 devra reporter le
  nouveau SHA exact si elle modifie le code ou le rapport après la revue.
- Branche vérifiée : `lot-40-hybrid-retrieval`.

LOT40: PASS_CANDIDATE

REVUE_INDÉPENDANTE: PENDING

GO_LIVE: NO_GO

`PASS_CANDIDATE` signifie uniquement que le candidat LOT40 satisfait les
preuves locales de la Task 10. Il ne signifie ni revue indépendante achevée,
ni checks GitHub verts, ni fusion dans `main`, ni aptitude globale au go-live.

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

La base d'intégration ne contient qu'une fixture synthétique, dont 45 000
lignes cibles complétées par des cas hors collection ou non revus. Elle ne
constitue pas une preuve de qualité d'un corpus pédagogique réel.

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

Sauf la sous-section dédiée au micro-correctif d'hygiène, les suites de cette
section ont été exécutées sur la tête fonctionnelle
`74a3dea70b7ab8bed1874b3d269b8bb88c43e2df`. La Task 11 doit rejouer
l'intégralité des preuves sur sa dernière tête après la revue indépendante.

### Suites ciblées

Commande exécutée depuis `services/rag-engine` :

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/test_pgvector_v2_schema.py tests/test_pg_pool.py \
  tests/test_retrieval_hybrid_v2.py tests/test_retrieval_pg_v2.py \
  tests/test_retrieval_v2_endpoint.py tests/test_retrieval_v2_gate.py \
  tests/test_review_visibility.py tests/test_retrieval_v2_cli.py -q
```

Verdict : PASS, 401 tests collectés et exécutés en 10,11 s. Répartition : 104
schéma, 38 pool, 82 cœur hybride, 90 accès PostgreSQL, 43 endpoint, 8 gate,
9 visibilité et 27 CLI.

Commande réelle PostgreSQL :

```bash
make test-integration-hybrid
```

Verdict : PASS en 84,73 s, avec 7 tests pytest d'intégration et 23 marqueurs
`PASS`. Les preuves incluent notamment : base prête, refus du head `002` sur
base fraîche, cycle complet, rollback atomique après les deux échecs injectés,
head final `002`, rôle applicatif non-superuser et lecture seule, objets réels,
rang 50 déterministe, sentinelle d'égalité HNSW, plans GIN/HNSW, underfill sans
scan global, retrieval réel, `/search` HTTP et `/chat` verrouillé. Le temps du
plan HNSW était de 49,011 ms ; il est consigné à titre informatif, sans seuil
normatif.

### Qualité complète de `rag-engine`

Commandes exécutées depuis `services/rag-engine` :

```bash
make lint
make typecheck
make test
```

- Ruff : PASS, `All checks passed!`, 0,96 s.
- mypy : PASS, 43 fichiers source, 54,16 s.
- pytest hors intégration : PASS, 1 037 tests, 31,06 s.

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

- verrous de gouvernance : PASS, 18 clés sur 18, 0,25 s ;
- hygiène du dépôt : PASS, 0,03 s ;
- topologie CI : PASS, fixture canonique acceptée, 22 mutations refusées et
  graphe acyclique, 2,99 s ;
- fail-safe CI : PASS, 44 contrôles sur 44, 1,90 s ;
- contrôle d'espaces du diff : PASS, 0,06 s.

Aucun verrou de gouvernance n'a été activé.

### Micro-correctif d'hygiène du candidat final

Le scan prescrit a d'abord échoué comme attendu sur six DSN factices écrits en
un seul littéral dans `tests/test_pg_pool.py`. Le commit test-only
`5530e32e91361d5d6fc5f12a5267114e3a1f59f9` les a remplacés par un helper qui
compose les fragments à l'exécution.

La revue Task 10 a ensuite relevé un P1 : ce premier helper avait raccourci les
hôtes historiques de fixture. Le commit test-only
`973e00b59c20b1ce399d96b7ef5dee3f5bba3aa4` restaure exactement l'hôte nominal
`db.example` et l'hôte alternatif `other.example`. Trois assertions explicites
figent désormais les valeurs runtime historiques nominale, malformed et autre
hôte. Elles sont construites par fragments pour ne pas réintroduire sur une
ligne source le motif secret interdit. Les assertions de non-divulgation
existantes restent inchangées.

Preuves fraîches sur ce commit :

- RED : la nouvelle assertion nominale a échoué sur l'hôte raccourci, avec
  `db/rag` obtenu au lieu de `db.example/rag` attendu ;
- `PYTHONPATH=src .venv/bin/pytest tests/test_pg_pool.py -q` : PASS, 39 tests en
  0,34 s après correction ;
- `.venv/bin/ruff check tests/test_pg_pool.py` : PASS en 0,01 s ;
- assertions directes sur les trois valeurs construites à l'exécution : PASS ;
- `git diff --check` : PASS ;
- scan exact des lignes ajoutées de `services/rag-engine` et du présent rapport
  contre les chemins locaux, clés et DSN avec credentials : PASS.

Le typecheck canonique de `rag-engine` cible uniquement `src`; il n'était donc
pas applicable à ce delta limité au fichier de tests. Le mypy complet de `src`
était déjà PASS sur la tête fonctionnelle, et aucun fichier de `src` n'a changé.

### CI locale intégrale

Commande interne exacte :

```bash
bash scripts/ci-local.sh
```

Elle a été lancée avec Node 22.22.0 et un wrapper exécutable temporaire qui
transmettait `python3.11` au binaire CPython 3.11 uv valide. Le wrapper vivait
hors dépôt, son environnement avait été prévalidé par création de venv et il a
été supprimé automatiquement. Aucun fichier versionné n'a été adapté pour le
banc de test.

Verdict final : exit 0 en 668,77 s, résumé exact 13 PASS et 0 FAIL :

1. `packages/contracts` ;
2. `services/rag-pedago` — Ruff et mypy PASS, 1 751 tests PASS en 230,19 s ;
3. `services/rag-engine` — 1 037 tests hors intégration PASS puis
   `LOT40_HYBRID_INTEGRATION=PASS` ;
4. `services/cockpit` — lint, 21 tests Vitest, contrats et build Next.js PASS,
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
85,149 ms. Les propriétés normatives portaient sur l'index, le plan et le
nombre de lignes borné, pas sur ce temps.

Avant cette preuve verte, trois lancements ont exposé des défauts du poste :
Node 22.21 trop ancien ; un lien Python uv relocalisé avec un préfixe invalide ;
puis un `python3` système dépourvu des dépendances de l'export de
contrats pendant le build cockpit. Ils ont respectivement été arrêtés avec un
diagnostic explicite et n'ont pas été comptés comme preuves du candidat. La
relance finale ci-dessus a utilisé les exécutables prévalidés, sans ignorer ni
modifier un contrôle.

## Nettoyage Docker

Le runner nomme et détruit son conteneur et son volume temporaires au moyen
d'un `trap`, y compris en cas d'erreur. Deux contrôles postérieurs indépendants
— après la cible d'intégration seule puis après la CI intégrale — ont donné :

```text
LOT40_CONTAINERS=0
LOT40_VOLUMES=0
```

Le répertoire d'environnement temporaire de la CI finale a également été
confirmé absent. Les sept stashes historiques sont restés inchangés.

## Matrice de preuve

| Contrôle | Responsable | Environnement | Artefact | Digest/SHA | Verdict |
|---|---|---|---|---|---|
| Schéma et cycle `001 → 002 → 001 → 002` | runner d'intégration LOT40 | PostgreSQL 16/pgvector éphémère | migrations, rollback et registre | empreintes SQL et digest OCI complets ci-dessus | PASS |
| Atomicité et moindre privilège | runner d'intégration LOT40 | rôle migration + rôle applicatif réel | échecs injectés, objets et privilèges | tête fonctionnelle complète ci-dessus | PASS |
| Retrieval dense, lexical, RRF, rerank et MMR | pytest ciblé + runner réel | Python 3.11 + PostgreSQL éphémère | 401 tests ciblés + 7 tests DB | tête fonctionnelle complète ci-dessus | PASS |
| Endpoints v2, CLI, review-only et chat verrouillé | pytest ciblé + smoke HTTP | modèles déterministes, aucun réseau de génération | tests endpoint/gate/visibilité/CLI + smoke | tête fonctionnelle complète ci-dessus | PASS |
| Qualité `rag-engine` | Ruff, mypy, pytest | venv Python 3.11 frais | 43 fichiers typés, 1 037 tests | tête fonctionnelle complète ci-dessus | PASS |
| Topologie et propagation du smoke | tests shell fail-closed | racine du worktree | 22 mutations de topologie + 44 contrôles fail-safe | tête fonctionnelle complète ci-dessus | PASS |
| Gouvernance et hygiène | garde-fous racine | worktree LOT40 | baseline 18 clés, racine suivie | SHA de base et tête fonctionnelle complets ci-dessus | PASS |
| CI locale intégrale | orchestrateur `ci-local.sh` | Node 22.22.0 + Python 3.11 + Docker | 13 cibles canoniques | tête fonctionnelle complète ci-dessus | PASS |
| Micro-correctifs DSN test-only | pytest, Ruff et scan prescrit | candidat final | 39 tests de pool, trois valeurs historiques et lignes ajoutées | SHA candidat final complet ci-dessus | PASS |
| Nettoyage des ressources | runner + relecture postérieure | Docker local | inventaire conteneurs/volumes LOT40 | 0 conteneur ; 0 volume | PASS |
| Revue indépendante `main...HEAD` | reviewer indépendant de Task 11 | tête finale de PR | diff LOT40 complet | à fixer après dernière correction | PENDING |
| Checks GitHub et fusion | GitHub Actions + mainteneur | PR vers `main` | contextes protégés et SHA fusionné | non encore disponible | PENDING |

Les revues de réalisation des Tasks 1 à 9 ont été conduites par incréments de
spécification et de qualité, avec commits correctifs séparés. Elles ne sont pas
présentées comme la revue indépendante globale exigée en Task 11.

## Risques et portes restantes

- **Task 11** : revue indépendante sur le diff complet, nouvelle exécution des
  preuves après toute correction, PR, checks GitHub, fusion et contrôle
  post-merge restent obligatoires avant de déclarer LOT40 `MERGED/PASS`.
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

En conséquence, le dépôt candidat peut passer à la revue indépendante de
LOT40, mais le projet complet n'est pas prêt pour un go-live public.
