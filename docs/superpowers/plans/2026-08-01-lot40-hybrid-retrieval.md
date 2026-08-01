# LOT40 Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer un retrieval v2 PostgreSQL/pgvector hybride, déterministe, réversible et fail-closed, utilisé par `/search/v2`, `/chat`, le warmup et le CLI.

**Architecture:** Un registre transactionnel gouverne les migrations `001/002`. `pg_pool.py` porte uniquement le cycle de vie des connexions, `retrieval_pg_v2.py` les deux canaux SQL, et `retrieval_hybrid_v2.py` les types, la fusion RRF, le rerank et MMR. Les consommateurs délèguent tous à ce noyau ; l'intégration réelle s'exécute dans un conteneur pgvector éphémère épinglé par digest.

**Tech Stack:** Python 3.11, psycopg 3.2.1, psycopg-pool 3.2.1, PostgreSQL 16, pgvector, FastAPI/Pydantic, pytest, Bash, Docker, Ruff, mypy.

---

Spécification normative :
`docs/superpowers/specs/2026-08-01-lot40-hybrid-retrieval-design.md`.

Contraintes de lot : ne modifier ni `packages/contracts`, ni les filtres LOT41,
ni les fichiers/verrous de gouvernance. Ne charger aucun corpus réel. Tous les
commits restent sur `lot-40-hybrid-retrieval` jusqu'à la PR.

## Cartographie des fichiers

| Fichier | Responsabilité unique |
|---|---|
| `infra/postgres/migrations/002_hybrid_retrieval.sql` | DDL additif FTS français |
| `infra/postgres/migrations/HEAD` | head déclaré, exactement `002_hybrid_retrieval` |
| `infra/postgres/rollbacks/002_hybrid_retrieval.down.sql` | down non destructif de 002 |
| `infra/scripts/lib/pgvector_migration_state.sh` | découverte/validation pure du manifeste et SQL d'invariants |
| `infra/scripts/apply_pgvector_migrations.sh` | backup, validation du registre et up atomique |
| `infra/scripts/rollback_pgvector_migration.sh` | backup, validation et down atomique de 002 |
| `infra/scripts/test_hybrid_integration.sh` | cycle Docker éphémère et orchestration des preuves DB/HTTP |
| `src/ingestor/pg_pool.py` | configuration et cycle de vie du pool psycopg |
| `src/ingestor/retrieval_pg_v2.py` | SQL dense/lexical et mapping des lignes |
| `src/ingestor/retrieval_hybrid_v2.py` | contrats internes, RRF, rerank, MMR et orchestration |
| `src/ingestor/retrieval_v2_endpoint.py` | auth/gates HTTP et mapping des DTO uniquement |
| `scripts/retrieval_v2.py` | interface CLI vers le même pipeline |
| `tests/integration/test_lot40_hybrid_pgvector.py` | assertions sur une vraie base et smoke HTTP |

## Chunk 1: Schéma, migrations et connexions

### Task 1: Figer le contrat statique de migration 002

**Files:**
- Create: `services/rag-engine/infra/postgres/migrations/002_hybrid_retrieval.sql`
- Create: `services/rag-engine/infra/postgres/migrations/HEAD`
- Create: `services/rag-engine/infra/postgres/rollbacks/002_hybrid_retrieval.down.sql`
- Modify: `services/rag-engine/infra/postgres/init.sql`
- Modify: `services/rag-engine/tests/test_pgvector_v2_schema.py`

- [ ] **Step 1: Écrire les tests statiques RED**

Ajouter `import re`, des constantes `MIGRATION_002`, `ROLLBACK_002` et `MIGRATION_HEAD`,
puis des tests exigeant : head exact avec newline final, colonne générée
`to_tsvector('french', coalesce(text, ''))`, index GIN nommé, rollback hors du
répertoire up, et alignement de `init.sql`. Le test de réversibilité doit aussi
interdire `DROP TABLE`, `TRUNCATE` et toute suppression d'une colonne source.

```python
def test_hybrid_migration_contract_is_additive_and_reversible() -> None:
    up = MIGRATION_002.read_text(encoding="utf-8")
    down = ROLLBACK_002.read_text(encoding="utf-8")
    assert MIGRATION_HEAD.read_text(encoding="utf-8") == "002_hybrid_retrieval\n"
    assert "text_tsv" in up
    assert "GENERATED ALWAYS AS" in up
    assert "to_tsvector('french', coalesce(text, ''))" in up
    assert "idx_rag_chunks_text_tsv" in up and "USING gin" in up
    assert "DROP COLUMN IF EXISTS text_tsv" in down
    assert "DROP TABLE" not in down.upper()
    assert "TRUNCATE" not in down.upper()
    assert "DELETE" not in down.upper()
    dropped_columns = re.findall(
        r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
        down,
        flags=re.IGNORECASE,
    )
    assert dropped_columns == ["text_tsv"]
    assert down.index("DROP INDEX") < down.index("DROP COLUMN")
    assert ROLLBACK_002.parent != MIGRATION_002.parent
    init = INIT_SQL.read_text(encoding="utf-8")
    assert "to_tsvector('french', coalesce(text, ''))" in init
    assert "idx_rag_chunks_text_tsv" in init
```

- [ ] **Step 2: Vérifier l'échec ciblé**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_v2_schema.py -q`

Expected: FAIL car les trois fichiers 002/HEAD/down n'existent pas.

- [ ] **Step 3: Écrire le DDL minimal**

Le up contient uniquement les deux statements idempotents suivants ; la
transaction appartient au runner :

```sql
ALTER TABLE rag_chunks
    ADD COLUMN IF NOT EXISTS text_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('french', coalesce(text, ''))) STORED;
CREATE INDEX IF NOT EXISTS idx_rag_chunks_text_tsv
    ON rag_chunks USING gin (text_tsv);
```

Le down supprime d'abord `idx_rag_chunks_text_tsv`, puis seulement `text_tsv`.
Ajouter la même colonne et le même index à `init.sql`; ne pas dupliquer la
table complète ailleurs.

- [ ] **Step 4: Vérifier GREEN et la forme SQL**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_v2_schema.py -q && .venv/bin/ruff check tests/test_pgvector_v2_schema.py`

Expected: PASS.

- [ ] **Step 5: Commit atomique**

```bash
git add services/rag-engine/infra/postgres/init.sql \
  services/rag-engine/infra/postgres/migrations/002_hybrid_retrieval.sql \
  services/rag-engine/infra/postgres/migrations/HEAD \
  services/rag-engine/infra/postgres/rollbacks/002_hybrid_retrieval.down.sql \
  services/rag-engine/tests/test_pgvector_v2_schema.py
git commit -m "rag-engine: ajouter la migration hybride 002"
```

### Task 2: Rendre le registre et les transitions atomiques

**Files:**
- Create: `services/rag-engine/infra/scripts/lib/pgvector_migration_state.sh`
- Modify: `services/rag-engine/infra/scripts/apply_pgvector_migrations.sh`
- Create: `services/rag-engine/infra/scripts/rollback_pgvector_migration.sh`
- Create: `services/rag-engine/infra/scripts/tests/test_pgvector_migration_state.sh`
- Create: `services/rag-engine/tests/test_pgvector_migration_runner.py`
- Modify: `services/rag-engine/tests/test_pgvector_v2_schema.py`

- [ ] **Step 1: Écrire le test shell RED du manifeste**

Le test source uniquement la future bibliothèque et construit des répertoires
temporaires. Il exige `discover_manifest DIR HEAD_FILE` vert pour `001,002`, et
un statut non nul avec diagnostics exacts pour : trou `001,003`, doublon de
numéro, nom hors `^[0-9]{3}_[a-z0-9_]+\.sql$`, HEAD absent, HEAD divergent et
fichier non régulier. Il vérifie les tableaux globaux `MIGRATION_VERSIONS`,
`MIGRATION_NAMES`, `MIGRATION_FILES`, `MIGRATION_SHA256` et deux hashes de 64
hexadécimaux.

- [ ] **Step 2: Vérifier RED du manifeste**

Run: `bash services/rag-engine/infra/scripts/tests/test_pgvector_migration_state.sh`

Expected: FAIL car `lib/pgvector_migration_state.sh` n'existe pas.

- [ ] **Step 3: Implémenter seulement `discover_manifest`**

La fonction met `LC_ALL=C`, résout les fichiers par
`find "$dir" -maxdepth 1 -type f -name '[0-9][0-9][0-9]_*.sql' | sort`, impose
`10#$number == index + 1`, vérifie chaque basename par regex et calcule
`sha256sum`. Elle compare le contenu exact de HEAD sans newline à
`${MIGRATION_NAMES[-1]%.sql}`. Elle ne lit ni Docker ni la base et ne mute rien.

- [ ] **Step 4: Vérifier GREEN du manifeste**

Run: `bash services/rag-engine/infra/scripts/tests/test_pgvector_migration_state.sh`

Expected: `PASS: migration manifest state`.

- [ ] **Step 5: Écrire les tests RED des SQL d'invariants**

Dans `test_pgvector_v2_schema.py`, exiger que la bibliothèque contienne :

- `registry_schema_sql` avec PK version positive, nom unique/non blanc,
  checksum contraint par `^[0-9a-f]{64}$`, et
  `applied_at timestamptz NOT NULL DEFAULT now()` ;
- `validate_001_sql` comptant toutes les colonnes, la PK, les huit index,
  l'extension vector et `format_type(...)='vector(1024)'` ;
- `validate_002_sql` comparant `pg_get_expr` à la génération française et
  `pg_get_indexdef` à `USING gin (text_tsv)` ;
- `validate_registry_sql` rejetant version/fichier inconnus, trou, ordre et SHA.

```python
@pytest.mark.parametrize(
    "needle",
    ["rag_schema_migrations", "sha256sum", "pg_advisory_xact_lock",
     "MIGRATION_CHECKSUM_MISMATCH", "MIGRATION_GAP", "vector(1024)",
     "pg_get_expr", "pg_get_indexdef"],
)
def test_migration_library_declares_exact_invariants(needle: str) -> None:
    assert needle in MIGRATION_LIBRARY.read_text(encoding="utf-8")
```

- [ ] **Step 6: Vérifier RED, puis implémenter les quatre émetteurs SQL**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_v2_schema.py -q`

Expected: FAIL, puis PASS après ajout des SQL exacts. Chaque validateur termine
par un bloc `DO $$ ... RAISE EXCEPTION 'SCHEMA_HEAD_...'; ... $$` : zéro ligne
ou compte différent de l'attendu est un échec, jamais une notice.

- [ ] **Step 7: Écrire le double Docker/psql RED du runner up**

Dans `test_pgvector_migration_runner.py`, créer un exécutable `docker` dans un
`tmp_path/bin`, le placer en tête de `PATH` et journaliser chaque invocation et
le stdin de `docker exec -i ... psql`. Le double répond `true` à inspect,
retourne un registre absent au preflight, simule `pg_dump`/`cp`, puis accepte
psql. Exiger cet ordre :

```python
assert events.index("READ_STATE") < events.index("PG_DUMP")
assert events.index("PG_DUMP") < events.index("DOCKER_CP")
assert events.index("DOCKER_CP") < events.index("APPLY_001")
stdin = captured_transaction("APPLY_002")
assert stdin.index("pg_advisory_xact_lock") < stdin.index("ADD COLUMN")
assert stdin.index("ADD COLUMN") < stdin.index("INSERT INTO rag_schema_migrations")
assert "--single-transaction" in psql_arguments("APPLY_002")
```

Ajouter les scénarios registre inconnu, checksum modifié, trou et schéma 001
partiel ; ils doivent sortir non-zéro avant `PG_DUMP`.

- [ ] **Step 8: Vérifier RED du runner up**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_migration_runner.py -q`

Expected: FAIL car le runner historique applique directement tous les SQL.

- [ ] **Step 9: Implémenter seulement le preflight read-only**

Sourcer la bibliothèque, appeler `discover_manifest`, puis faire une unique
lecture `to_regclass('rag_schema_migrations')` et des lignes éventuelles.
Passer celles-ci au validateur de registre. Si le registre est absent mais
`rag_chunks` présente, exécuter `validate_001_sql`; ne jamais reconnaître 001
sur le seul `chunk_id`. Aucun `CREATE`/`INSERT` ne précède le backup. Les noms
viennent du manifeste validé ; les valeurs passent par `psql -v` et
`:'variable'`.

- [ ] **Step 10: Vérifier les refus de preflight**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_migration_runner.py -q -k preflight`

Expected: PASS et aucune occurrence `PG_DUMP` dans les scénarios refusés.

- [ ] **Step 11: Implémenter le backup comme frontière de mutation**

Conserver `BACKUP_ROOT:?`, `pg_dump -Fc`, `docker cp` et permissions 0700.
Émettre `BACKUP_COMPLETE` après copie réussie. Les transactions mutatrices ne
sont appelées qu'après ce marqueur ; un échec dump/cp sort sans psql mutateur.

- [ ] **Step 12: Vérifier l'ordre du backup avec le double**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_migration_runner.py -q -k backup`

Expected: PASS, y compris dump/cp en erreur.

- [ ] **Step 13: Implémenter une transition up atomique**

Créer le registre avec contraintes `CHECK`, prendre
`pg_advisory_xact_lock(hashtext('nexus-rag-schema-migrations'))`, concaténer le
DDL up et l'`INSERT` dans une seule invocation
`psql --single-transaction -v ON_ERROR_STOP=1`. Pour la reconnaissance 001,
insérer sa ligne dans cette transaction après répétition du validateur. Après
001 exiger le schéma 001 et `{1,fichier,SHA}` ; après 002 exiger expression
générée, GIN, deux versions contiguës et `max(version)=2`.

- [ ] **Step 14: Vérifier la composition atomique up**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_migration_runner.py -q -k 'up or atomic'`

Expected: PASS sur ordre verrou → DDL → INSERT et `--single-transaction`.

- [ ] **Step 15: Écrire le double RED du runner down**

Faire répondre que 002 est le head valide. Exiger backup avant mutation,
fichier exact `rollbacks/002_hybrid_retrieval.down.sql`, puis dans un stdin :
verrou avant `DROP INDEX`, index avant colonne, et
`DELETE ... WHERE version = 2` après DDL ; exiger `--single-transaction`. Head
001, argument différent ou checksum divergent refusent avant backup.

- [ ] **Step 16: Implémenter le down 002 atomique**

Le runner accepte exactement `002_hybrid_retrieval`. Il relit registre/SHA,
sauvegarde, puis concatène down + delete sous verrou/transaction. Après commit,
exiger absence de `text_tsv` et du GIN, ligne 001/SHA intacte, une seule version
et `max(version)=1`.

- [ ] **Step 17: Vérifier le double down**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_migration_runner.py -q -k down`

Expected: PASS.

- [ ] **Step 18: Fixer la preuve réelle différée**

Task 8 injectera une erreur SQL après le DDL up puis après le DDL down dans une
copie temporaire des migrations. Elle exigera respectivement absence de
colonne/ligne 002, puis conservation de la colonne/ligne 002. Les doubles
prouvent composition/ordre ; la DB réelle prouve l'atomicité. Aucun verdict
atomique final n'est permis avant Task 8.

- [ ] **Step 19: Tester chaque syntaxe shell et la suite ciblée**

```bash
for script in \
  services/rag-engine/infra/scripts/lib/pgvector_migration_state.sh \
  services/rag-engine/infra/scripts/apply_pgvector_migrations.sh \
  services/rag-engine/infra/scripts/rollback_pgvector_migration.sh \
  services/rag-engine/infra/scripts/tests/test_pgvector_migration_state.sh
do
  bash -n "$script"
done
```

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pgvector_v2_schema.py tests/test_pgvector_migration_runner.py -q`

Expected: PASS.

- [ ] **Step 20: Commit atomique**

```bash
git add services/rag-engine/infra/scripts/lib/pgvector_migration_state.sh \
  services/rag-engine/infra/scripts/tests/test_pgvector_migration_state.sh \
  services/rag-engine/infra/scripts/apply_pgvector_migrations.sh \
  services/rag-engine/infra/scripts/rollback_pgvector_migration.sh \
  services/rag-engine/tests/test_pgvector_v2_schema.py \
  services/rag-engine/tests/test_pgvector_migration_runner.py
git commit -m "rag-engine: tracer le head pgvector atomiquement"
```

### Task 3: Introduire le pool PostgreSQL borné

**Files:**
- Create: `services/rag-engine/src/ingestor/pg_pool.py`
- Create: `services/rag-engine/tests/test_pg_pool.py`
- Modify: `services/rag-engine/requirements.lock`
- Modify: `services/rag-engine/src/ingestor/requirements.v2.txt`

- [ ] **Step 1: Écrire les tests RED du pool**

Tester `PoolSettings.from_env()` avec priorité `PG_RAG_DSN` non blanc puis
fallback `DATABASE_URL_SYNC`, sans défaut de DSN. Les paramètres sont
`PG_POOL_MIN_SIZE=1`, `PG_POOL_MAX_SIZE=10`, `PG_POOL_TIMEOUT_S=5.0` par
défaut, avec `1 <= min_size <= max_size <= 50` et timeout positif. Injecter la
classe espionne en patchant `_pool_factory`, sans API publique de test.

```python
def test_pool_is_lazy_reused_and_closeable(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePoolFactory()
    monkeypatch.setattr(pg_pool, "_pool_factory", fake)
    first = get_pool(PoolSettings("postgresql://example", 1, 4, 5.0))
    second = get_pool(PoolSettings("postgresql://example", 1, 4, 5.0))
    assert first is second
    assert fake.calls == [{"min_size": 1, "max_size": 4, "open": False}]
    assert first.events[:2] == [("open", False), ("wait", 5.0)]
    with pool_connection(PoolSettings("postgresql://example", 1, 4, 5.0)):
        pass
    assert ("connection", 5.0) in first.events
    close_pool()
    assert first.closed
    assert get_pool(PoolSettings("postgresql://example", 1, 4, 5.0)) is not first
```

Ajouter un test exigeant `PoolConfigurationError` si les settings changent
avant fermeture, et un test où `wait` échoue qui exige fermeture de l'instance
et remise de `_pool` à `None`.

- [ ] **Step 2: Vérifier RED**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_pg_pool.py -q`

Expected: FAIL avec `ModuleNotFoundError: ingestor.pg_pool`.

- [ ] **Step 3: Aligner la famille psycopg**

Dans le lock canonique et `src/ingestor/requirements.v2.txt`, utiliser
exactement :

```text
psycopg==3.2.1
psycopg-binary==3.2.1
psycopg-pool==3.2.1
```

Réinstaller avec `make install`, puis exiger
`.venv/bin/python -c "import psycopg, psycopg_pool"` vert.

- [ ] **Step 4: Implémenter le pool minimal**

Créer une dataclass gelée `PoolSettings(dsn, min_size, max_size, timeout_s)`,
un verrou de module, `_pool: ConnectionPool | None`, `_pool_settings`,
`get_pool`, `pool_connection()` et `close_pool`. À la création, appeler
`ConnectionPool(..., open=False)`, puis `open(wait=False)` et
`wait(timeout=settings.timeout_s)` avant publication du singleton. En échec,
fermer l'instance et réinitialiser l'état. `pool_connection` utilise
`pool.connection(timeout=settings.timeout_s)`. Ne jamais logguer le DSN. Si
les settings changent pendant qu'un pool existe, lever
`PoolConfigurationError`.

- [ ] **Step 5: Vérifier tests, lint et types**

Run: `cd services/rag-engine && make install && PYTHONPATH=src .venv/bin/pytest tests/test_pg_pool.py -q && .venv/bin/ruff check src/ingestor/pg_pool.py tests/test_pg_pool.py && .venv/bin/mypy src/ingestor/pg_pool.py`

Expected: PASS et import réel de `psycopg_pool` pendant les tests.

- [ ] **Step 6: Commit atomique**

```bash
git add services/rag-engine/requirements.lock \
  services/rag-engine/src/ingestor/requirements.v2.txt \
  services/rag-engine/src/ingestor/pg_pool.py services/rag-engine/tests/test_pg_pool.py
git commit -m "rag-engine: mutualiser les connexions pgvector"
```

## Chunk 2: Pipeline hybride et consommateurs

### Task 4: Implémenter le classement hybride pur

**Files:**
- Create: `services/rag-engine/src/ingestor/retrieval_hybrid_v2.py`
- Create: `services/rag-engine/tests/test_retrieval_hybrid_v2.py`

- [ ] **Step 1: Écrire les tests RED des types exacts**

Exiger trois dataclasses gelées avec ces champs, dans cet ordre logique :

```python
@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: str
    doc_id: str
    source_label: str
    source_uri: str
    rights: str
    type_doc: str
    text: str
    page_start: int | None
    vector: tuple[float, ...]
    review_status: Literal["reviewed"]
    dense_score: float | None = None
    lexical_score: float | None = None

@dataclass(frozen=True)
class RankedCandidate:
    candidate: RetrievalCandidate
    dense_rank: int | None
    lexical_rank: int | None
    rrf_score: Fraction
    rerank_score: float | None = None

@dataclass(frozen=True)
class HybridHit:
    candidate: RetrievalCandidate
    dense_rank: int | None
    lexical_rank: int | None
    rrf_score: float
    rerank_score: float
    mmr_score: float
    score_final: float
```

Les tests refusent identifiants, texte et les trois provenances normatives
`source_label/source_uri/rights` blancs, statut autre que reviewed, score non
fini, vecteur de longueur différente de 1024, composante non finie et vecteur
de norme zéro. `type_doc` n'est pas un gate d'éligibilité. `page_start <= 0`
est normalisé à `None` par le store, sans exclure le chunk. Une similarité
cosinus égale à zéro entre deux vecteurs orthogonaux reste valide.

- [ ] **Step 2: Vérifier RED des types**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q -k candidate`

Expected: FAIL avec module absent.

- [ ] **Step 3: Implémenter uniquement types, constantes et validations**

Fixer sans lecture d'environnement :

```python
CHANNEL_LIMIT = 50
RRF_DENSE_WEIGHT = Fraction(7, 10)
RRF_LEXICAL_WEIGHT = Fraction(3, 10)
RRF_K = 60
RERANK_THRESHOLD = 1.90
MMR_LAMBDA = 0.7
EMBED_MODEL = "intfloat/multilingual-e5-large"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
EMBED_DIMENSION = 1024
```

Créer `RetrievalPipelineError(ValueError)` pour tous les refus contrôlés.

- [ ] **Step 4: Vérifier GREEN des types**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q -k candidate`

Expected: PASS.

- [ ] **Step 5: Écrire les tests RED RRF numériques**

Avec rangs démarrant à 1 et canal absent égal à zéro, exiger exactement :

```python
assert scores["A"] == Fraction(7, 10) / 61 + Fraction(3, 10) / 63
assert scores["B"] == Fraction(7, 10) / 62 + Fraction(3, 10) / 61
assert scores["C"] == Fraction(7, 10) / 63
assert scores["D"] == Fraction(3, 10) / 62
assert [item.candidate.chunk_id for item in fused] == ["A", "B", "C", "D"]
```

Paramétrer un test sur chaque champ substantif d'un même `chunk_id` : `doc_id`,
trois provenances, `type_doc`, `text`, `page_start`, `vector` et
`review_status`. Toute divergence entre canaux lève l'erreur au lieu de choisir
selon l'ordre ; seuls `dense_score` et `lexical_score` peuvent différer. Les
égalités RRF tranchent `chunk_id ASC`.

- [ ] **Step 6: Vérifier RED RRF**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q -k rrf`

Expected: FAIL sur `reciprocal_rank_fusion` absent.

- [ ] **Step 7: Implémenter RRF minimal et vérifier GREEN**

Construire les maps de rang par `enumerate(channel, start=1)`, fusionner par
`chunk_id`, calculer uniquement avec `Fraction`, puis trier par
`(-rrf_score, chunk_id)`. Ne convertir en float qu'au `HybridHit`.

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q -k rrf`

Expected: PASS.

- [ ] **Step 8: Écrire les tests RED rerank/MMR numériques**

Exiger cardinalité identique, logits finis et seuil inclusif
`logit >= 1.90`. Pour chaque itération :

```python
relevance = 1.0 / (1.0 + math.exp(-logit))
max_cosine = 0.0 if not selected else max(cosine(vector, hit.vector) for hit in selected)
mmr_raw = 0.7 * relevance - 0.3 * max_cosine
score_final = (mmr_raw + 0.3) / 1.3
```

Tester la valeur `pytest.approx` du premier A à logit 2, l'ordre `[A,C,B]`, la
borne `[0,1]`, et le tie-break
`(-mmr_raw, -logit, -float(rrf), chunk_id)`. Dans la fixture
`A1/A2(doc-X),B(doc-Y),C(doc-Z)`, exiger retrait de A2 immédiatement après A1,
avant calcul de l'itération suivante, puis trois documents pour `top_k=3`.

- [ ] **Step 9: Vérifier RED MMR**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q -k 'rerank or mmr'`

Expected: FAIL sur fonctions absentes.

- [ ] **Step 10: Implémenter rerank/MMR et vérifier GREEN**

Utiliser sigmoïde numériquement stable, `math.isfinite`, cosinus pur et aucun
ré-embedding. Après sélection, reconstruire le pool sans le `doc_id` choisi
avant de calculer le prochain maximum.

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q -k 'rerank or mmr'`

Expected: PASS.

- [ ] **Step 11: Écrire les tests RED des Protocols/orchestration**

Figer les interfaces :

```python
class CandidateStore(Protocol):
    def dense(self, *, query_vector: Sequence[float], collection: str,
              limit: int) -> Sequence[RetrievalCandidate]:
        raise NotImplementedError
    def lexical(self, *, raw_query: str, collection: str,
                limit: int) -> Sequence[RetrievalCandidate]:
        raise NotImplementedError

class Embedder(Protocol):
    def encode(self, text: str, *, normalize_embeddings: bool) -> Sequence[float]:
        raise NotImplementedError

class Reranker(Protocol):
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        raise NotImplementedError

class RetrieveFunction(Protocol):
    def __call__(self, query: str, collection: str, top_k: int, *,
                 store: CandidateStore, embedder: Embedder,
                 reranker: Reranker) -> list[HybridHit]:
        raise NotImplementedError
```

Tester cette séquence : valider query, collection et `1 <= top_k <= 50`;
appeler `format_query(raw_query)` et vérifier
le seul préfixe `query:`; encoder normalisé et exiger 1024; appeler dense avec
le vecteur et lexical avec la requête brute, tous deux limit 50; RRF; reranker
sur `(raw_query, candidate.text)`; seuil inclusif; MMR; top-k. Canal exécuté
mais vide reste valide; exception d'un canal ou modèle ferme toute la requête.

- [ ] **Step 12: Vérifier RED orchestration**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q -k pipeline`

Expected: FAIL sur `retrieve_hybrid` absent.

- [ ] **Step 13: Implémenter l'orchestrateur exact et vérifier GREEN**

`retrieve_hybrid(query, collection, top_k, *, store, embedder, reranker)` suit
strictement la séquence précédente. Il attrape les erreurs externes et les
chaîne dans `RetrievalPipelineError` sans inclure query, DSN ou texte source.

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q`

Expected: PASS.

- [ ] **Step 14: Vérifier qualité ciblée et commit**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_hybrid_v2.py -q && .venv/bin/ruff check src/ingestor/retrieval_hybrid_v2.py tests/test_retrieval_hybrid_v2.py && .venv/bin/mypy src/ingestor/retrieval_hybrid_v2.py`

Expected: PASS.

```bash
git add services/rag-engine/src/ingestor/retrieval_hybrid_v2.py \
  services/rag-engine/tests/test_retrieval_hybrid_v2.py
git commit -m "rag-engine: classer les candidats avec RRF et MMR"
```

### Task 5: Implémenter les deux canaux SQL déterministes

**Files:**
- Create: `services/rag-engine/src/ingestor/retrieval_pg_v2.py`
- Create: `services/rag-engine/tests/test_retrieval_pg_v2.py`

- [ ] **Step 1: Écrire les tests RED des deux SQL exacts**

Normaliser les espaces du SQL capturé et exiger les fragments complets :

```sql
-- commun aux deux canaux
collection = %s AND review_status = 'reviewed'
AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
AND btrim(source_label) <> '' AND btrim(source_uri) <> '' AND btrim(rights) <> ''

-- dense
1 - (vector <=> %s::vector) AS dense_score
ORDER BY vector <=> %s::vector ASC, chunk_id ASC LIMIT %s

-- lexical : la tsquery est calculée une seule fois
WITH lexical_query AS (SELECT plainto_tsquery('french', %s) AS value)
ts_rank_cd(text_tsv, lexical_query.value, 32) AS lexical_score
CROSS JOIN lexical_query
AND text_tsv @@ lexical_query.value
ORDER BY lexical_score DESC, chunk_id ASC LIMIT %s
```

Exiger `vector::text`, `page_start` et toute provenance dans le SELECT, les
paramètres exacts `(vec, collection, vec, 50)` et `(raw_query, collection, 50)`,
et aucune interpolation query/collection. Une `tsquery` vide retourne `[]`
sans fallback ni erreur.

- [ ] **Step 2: Vérifier RED**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_pg_v2.py -q`

Expected: FAIL avec module absent.

- [ ] **Step 3: Implémenter seulement les requêtes paramétrées**

Le constructeur reçoit un `Callable` retournant un context manager de
connexion. `dense(query_vector, collection, limit)` et
`lexical(raw_query, collection, limit)` retournent des
`RetrievalCandidate`; les colonnes sélectionnées incluent `page_start`, le
vecteur stocké sous `vector::text`, et le score du canal. Parser exactement
1024 floats et normaliser `page_start <= 0` à `None`. Rejeter toute autre ligne
malformée ou score non fini avec `RetrievalPipelineError`.

- [ ] **Step 4: Vérifier GREEN des requêtes**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_pg_v2.py -q -k sql`

Expected: PASS.

- [ ] **Step 5: Écrire RED avant la frontière 50**

Faire retourner 51 lignes de score égal et prouver que le store demande 50 et
refuse si le cursor en rend plus de 50. Prouver le mapping `dense_score|None`
et `lexical_score|None`, la tsquery vide, fermeture des cursors et restitution
de la connexion même en erreur. Le vrai tie SQL au rang 50 sera prouvé Chunk 3.

- [ ] **Step 6: Vérifier RED frontière/erreurs**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_pg_v2.py -q -k 'limit or empty or error'`

Expected: FAIL sur les protections encore absentes.

- [ ] **Step 7: Implémenter les protections et vérifier GREEN**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_pg_v2.py -q`

Expected: PASS.

- [ ] **Step 8: Vérifier qualité et commit**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_pg_v2.py tests/test_retrieval_hybrid_v2.py -q && .venv/bin/ruff check src/ingestor/retrieval_pg_v2.py tests/test_retrieval_pg_v2.py && .venv/bin/mypy src/ingestor/retrieval_pg_v2.py`

Expected: PASS.

```bash
git add services/rag-engine/src/ingestor/retrieval_pg_v2.py \
  services/rag-engine/tests/test_retrieval_pg_v2.py
git commit -m "rag-engine: interroger les canaux dense et lexical"
```

### Task 6: Faire déléguer tous les endpoints au pipeline unique

**Files:**
- Modify: `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`
- Modify: `services/rag-engine/tests/test_retrieval_v2_endpoint.py`
- Modify: `services/rag-engine/tests/test_retrieval_v2_gate.py`
- Modify: `services/rag-engine/tests/test_review_visibility.py`

- [ ] **Step 1: Écrire les tests RED de mapping/constants**

Construire un `HybridHit` et exiger que `/search/v2` expose `page`,
`dense_score`, `lexical_score`, `rrf_score`, `rerank_score` et `score_final`.
Exiger que `_to_retrieval_result` mappe `score_final`, `Citation.page` positive
et les quatre scores d'étape dans `metadata`. Dense/lexical valent `None` si le
canal n'a pas trouvé le chunk. Une provenance vide doit être refusée. Exiger
`SearchV2Response.seuil == 1.90` et les noms de modèles/limite/RRF/MMR importés
du noyau, sans `os.environ` pour les modifier.

- [ ] **Step 2: Vérifier RED mapping/constants**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py -q -k 'mapping or constants'`

Expected: FAIL sur champs et constantes historiques.

- [ ] **Step 3: Implémenter uniquement mapping/constants**

Étendre le DTO local et ses mappers, supprimer les overrides actifs
`RERANK_SCORE_THRESHOLD`/`RERANK_CANDIDATES`, puis utiliser exclusivement les
constantes du noyau.

- [ ] **Step 4: Vérifier GREEN mapping/constants**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py -q -k 'mapping or constants'`

Expected: PASS.

- [ ] **Step 5: Écrire les tests RED de délégation search**

Injecter `_retrieve_hybrid_hits` et appeler `/search/v2`; prouver gates avant
retrieval, paramètres bruts exacts, mapping, HTTP 503 générique sur chaque
erreur pool/dense/lexicale/embed/rerank/MMR, et aucune utilisation
`psycopg.connect` ou `_cache_get`. Adapter les anciens patches psycopg.

- [ ] **Step 6: Vérifier RED search**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py tests/test_retrieval_v2_gate.py tests/test_review_visibility.py -q -k search`

Expected: FAIL sur la délégation unique et les 503.

- [ ] **Step 7: Implémenter uniquement la délégation search**

La fabrique compose modèles canoniques, `PgCandidateStore` et
`pool_connection`; `search_v2` ne contient plus SQL, embedding ou rerank.

- [ ] **Step 8: Vérifier GREEN search**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py tests/test_retrieval_v2_gate.py tests/test_review_visibility.py -q -k search`

Expected: PASS.

- [ ] **Step 9: Écrire les tests RED `/chat` verrouillé**

Avec zéro hit puis assez de hits, clé OpenRouter définie et client réseau qui
lève, exiger après retrieval réussi le même refus déterministe
`answer_generation_locked`, jamais `insufficient_reviewed_evidence`, réponse
non grounded et citations vides. Avec `include_retrieval=True`, conserver les
hits mappés ; avec `False`, retourner `[]`. Gates rôles/collections restent
avant retrieval.

- [ ] **Step 10: Vérifier RED chat**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py tests/test_review_visibility.py -q -k chat`

Expected: FAIL sur le refus conditionné par la substance ou l'appel réseau.

- [ ] **Step 11: Implémenter uniquement le refus chat**

Supprimer l'appel actif OpenRouter et retourner le refus immédiatement après
retrieval/mapping, sans condition de substance.

- [ ] **Step 12: Vérifier GREEN chat**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py tests/test_review_visibility.py -q -k chat`

Expected: PASS.

- [ ] **Step 13: Écrire les tests RED warmup fail-closed**

Injecter succès puis erreur à chaque étage pool/dense/lexicale/embed/rerank/MMR.
Exiger HTTP 503 générique, zéro `_cache_put` et cache antérieur inchangé : les
résultats sont staged puis publiés seulement si toutes les requêtes terminent.
Prouver qu'un search public n'appelle jamais `_cache_get` et relit donc la DB.

- [ ] **Step 14: Vérifier RED warmup**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py tests/test_review_visibility.py -q -k 'warmup or cache'`

Expected: FAIL sur les `continue` et publications partielles historiques.

- [ ] **Step 15: Implémenter uniquement le warmup atomique**

Remplacer la boucle SQL historique par le pipeline unique. Accumuler les
entrées dans un dict local, transformer toute erreur en 503, puis prendre le
verrou cache et publier le batch seulement après succès total.

- [ ] **Step 16: Vérifier GREEN warmup**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py tests/test_review_visibility.py -q -k 'warmup or cache'`

Expected: PASS.

- [ ] **Step 17: Vérifier endpoint et non-régression élargie**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_endpoint.py tests/test_retrieval_v2_gate.py tests/test_review_visibility.py tests/test_catalogue_v2_auth.py -q`

Run: `cd services/rag-engine && .venv/bin/ruff check src/ingestor/retrieval_v2_endpoint.py tests/test_retrieval_v2_endpoint.py tests/test_retrieval_v2_gate.py tests/test_review_visibility.py && .venv/bin/mypy src/ingestor/retrieval_v2_endpoint.py`

Expected: PASS.

- [ ] **Step 18: Commit atomique**

```bash
git add services/rag-engine/src/ingestor/retrieval_v2_endpoint.py \
  services/rag-engine/tests/test_retrieval_v2_endpoint.py \
  services/rag-engine/tests/test_retrieval_v2_gate.py \
  services/rag-engine/tests/test_review_visibility.py
git commit -m "rag-engine: unifier le retrieval des endpoints v2"
```

### Task 7: Faire du CLI un consommateur du même noyau

**Files:**
- Modify: `services/rag-engine/scripts/retrieval_v2.py`
- Create: `services/rag-engine/tests/test_retrieval_v2_cli.py`

- [ ] **Step 1: Écrire les tests RED parsing/gate du CLI**

Tester que `--help` reste utilisable sans DSN, que l'absence de DSN après
parsing sort 1, et `top_k` borné à 1..50. `PoolSettings.from_env` conserve la
priorité commune. La signature injectée est :

```python
def search(
    query: str,
    collection: str,
    top_k: int,
    *,
    settings: PoolSettings,
    store_factory: Callable[[PoolSettings], CandidateStore] = _build_pg_store,
    embedder_factory: Callable[[], Embedder] = _load_canonical_embedder,
    reranker_factory: Callable[[], Reranker] = _load_canonical_reranker,
    retrieve_fn: RetrieveFunction = retrieve_hybrid,
) -> list[HybridHit]:
```

Exiger que `_check_retrievable` précède les trois factories. Interdire SQL,
`psycopg.connect`, `HYBRID_ENABLED`, seuil/modèles locaux et overrides env.

- [ ] **Step 2: Vérifier RED parsing/DSN/bornes**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_cli.py -q -k 'help or dsn or top_k'`

Expected: FAIL car le CLI contient encore le chemin dense historique.

- [ ] **Step 3: Implémenter uniquement parsing/DSN/bornes**

Conserver argparse, valider `top_k` par type borné, puis appeler
`PoolSettings.from_env()` après parsing afin que `--help` ne demande pas de
DSN. Ne charger encore aucun modèle ni connexion.

- [ ] **Step 4: Vérifier GREEN parsing/DSN/bornes**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_cli.py -q -k 'help or dsn or top_k'`

Expected: PASS.

- [ ] **Step 5: Vérifier RED gate/factories**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_cli.py -q -k 'gate or factory'`

Expected: FAIL sur ordre du gate et pipeline historique.

- [ ] **Step 6: Implémenter uniquement gate/factories/orchestration**

Après le gate, construire store, embedder canonique et reranker canonique, puis
appeler `retrieve_fn`. Les defaults de factories sont des fonctions nommées
qui utilisent le pool et les modèles fixes du noyau, jamais des objets chargés
à la définition.

- [ ] **Step 7: Vérifier GREEN gate/factories**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_cli.py -q -k 'help or gate or factory'`

Expected: PASS.

- [ ] **Step 8: Écrire les tests RED sortie/cleanup**

Prouver affichage score final + quatre scores d'étape. Faire réussir puis lever
`RetrievalPipelineError` après ouverture du pool ; dans les deux cas exiger
`close_pool()` exactement une fois via `finally`, message sans DSN/query et exit
non nul sur erreur. `search` retourne les hits ; `main` possède le cleanup.

- [ ] **Step 9: Vérifier RED sortie/cleanup**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_cli.py -q -k 'output or cleanup or error'`

Expected: FAIL sur sortie dense-only et cleanup incomplet.

- [ ] **Step 10: Implémenter uniquement sortie/cleanup**

Afficher les cinq scores sans contenu source. Encadrer l'appel `search` de
`try/except RetrievalPipelineError/finally close_pool()` dans `main`; fermer
exactement une fois même si une factory ou le pipeline lève.

- [ ] **Step 11: Vérifier GREEN sortie/cleanup**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_cli.py -q -k 'output or cleanup or error'`

Expected: PASS.

- [ ] **Step 12: Vérifier et commit**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_retrieval_v2_cli.py tests/test_retrieval_hybrid_v2.py -q && .venv/bin/ruff check scripts/retrieval_v2.py tests/test_retrieval_v2_cli.py`

Expected: PASS.

```bash
git add services/rag-engine/scripts/retrieval_v2.py \
  services/rag-engine/tests/test_retrieval_v2_cli.py
git commit -m "rag-engine: brancher le CLI sur le retrieval hybride"
```

## Chunk 3: Preuves réelles, CI et livraison

### Task 8: Prouver migrations, GIN, retrieval et HTTP sur pgvector réel

**Files:**
- Create: `services/rag-engine/infra/scripts/test_hybrid_integration.sh`
- Create: `services/rag-engine/tests/test_hybrid_integration_runner.py`
- Create: `services/rag-engine/tests/integration/test_lot40_hybrid_pgvector.py`
- Modify: `services/rag-engine/Makefile`

- [ ] **Step 1: Écrire le test RED du cycle de vie Docker**

Dans `test_hybrid_integration_runner.py`, placer un faux `docker` en tête de
PATH. Il journalise les noms exacts, échoue toujours à `pg_isready`, accepte les
deux suppressions du cleanup et refuse toute cible ne commençant pas par
`lot40-pg-`/`lot40-pg-volume-`. Lancer avec
`LOT40_PG_READY_ATTEMPTS=2`, `LOT40_PG_READY_DELAY_S=0`; exiger sortie non nulle,
diagnostic `LOT40_DB_READINESS_TIMEOUT` sans DSN, puis exactement un
`docker rm -f <container>` et un `docker volume rm <volume>`.

- [ ] **Step 2: Vérifier RED lifecycle**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_hybrid_integration_runner.py -q`

Expected: FAIL car le runner n'existe pas.

- [ ] **Step 3: Implémenter uniquement démarrage, timeout et trap**

Utiliser exactement l'image immuable :

```text
pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc
```

Le script utilise `set -euo pipefail`, des noms PID+aléa sous les préfixes
ci-dessus, `POSTGRES_HOST_AUTH_METHOD=trust` dans ce seul conteneur, et publie
uniquement `127.0.0.1::5432`. Installer `trap cleanup EXIT INT TERM` avant le
premier `docker volume create`. Cleanup valide les deux regex puis supprime
uniquement ces noms et le `mktemp -d`. Boucler au plus
`${LOT40_PG_READY_ATTEMPTS:-30}` fois avec délai
`${LOT40_PG_READY_DELAY_S:-1}`; refuser valeurs hors bornes `1..120` et
`0..10`. Après readiness seulement, résoudre le port et exporter un DSN sans
mot de passe vers `127.0.0.1`.

- [ ] **Step 4: Vérifier syntaxe et GREEN lifecycle**

Run: `bash -n services/rag-engine/infra/scripts/test_hybrid_integration.sh`

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_hybrid_integration_runner.py -q`

Expected: PASS, cleanup exact également sur timeout.

- [ ] **Step 5: Ajouter la cible Make dédiée**

```make
test-integration-hybrid: install-dev
	bash infra/scripts/test_hybrid_integration.sh
```

- [ ] **Step 6: Ajouter le contrôle négatif puis le cycle nominal migrations**

Sur la base fraîche, exécuter l'assertion `head=002` et exiger son échec
contrôlé (preuve RED de sensibilité). Ensuite, avec `PGVECTOR_CONTAINER/DB/USER`
et `BACKUP_ROOT` explicites : apply canonique, assertion registre 001+002 et
SHA des deux fichiers, down 002, assertion registre seulement 001 et absence
colonne/index, nouvel apply, assertion head 002 et présence exacte des objets.
Chaque assertion est une commande `psql -v ON_ERROR_STOP=1` qui lève sur compte
ou définition différente.

Le helper shell `expect_failure LABEL COMMAND...` désactive temporairement
`set -e`, capture le statut, le réactive, et échoue si le statut capturé vaut
zéro ; une erreur attendue ne peut donc ni arrêter le runner ni être confondue
avec un succès.

- [ ] **Step 7: Exécuter le cycle nominal**

Run: `cd services/rag-engine && make test-integration-hybrid`

Expected: le contrôle négatif head frais échoue comme prévu, puis
`MIGRATION_CYCLE_001_002_001_002=PASS`; aucun reliquat Docker.

- [ ] **Step 8: Ajouter la preuve RED d'atomicité up réelle**

Après un down canonique vers 001, copier `infra/` sous le répertoire temporaire
du runner et ajouter `SELECT 1 / 0;` **après** le DDL dans la copie de 002.
Exécuter le runner up copié et exiger un statut non nul. Interroger ensuite la
vraie base : aucune `text_tsv`, aucun GIN, aucune ligne version 2, ligne 001/SHA
intacte. Si un artefact 002 existe, le test échoue.

- [ ] **Step 9: Ajouter la preuve RED d'atomicité down réelle**

Réappliquer 002 canonique, copier `infra/` proprement puis ajouter
`SELECT 1 / 0;` après les deux DROP dans la copie du rollback. Exiger l'échec
du runner down copié, puis prouver que `text_tsv`, le GIN et la ligne 002/SHA
sont tous conservés. Les deux échecs attendus restent sous le trap principal.

- [ ] **Step 10: Vérifier atomicité up/down**

Run: `cd services/rag-engine && make test-integration-hybrid`

Expected: `ATOMIC_UP_ROLLBACK=PASS`, `ATOMIC_DOWN_ROLLBACK=PASS`, état final
002 et cleanup vert.

- [ ] **Step 11: Écrire les tests DB RED rang 50 et GIN**

Marquer le module `pytest.mark.integration`, exiger `LOT40_PG_DSN`, puis créer
52 chunks synthétiques reviewed à scores égaux et des `needs_review`. Les
helpers d'assertion possèdent des contrôles négatifs : ordre attendu inversé
doit lever ; dans une transaction, supprimer temporairement le GIN puis exiger
que l'assertion de plan lève, avant rollback. L'assertion positive exige
`chunk_id ASC` aux deux rangs 50, puis `ANALYZE`, transaction,
`SET LOCAL enable_seqscan=off` et `EXPLAIN` contenant le nom exact du GIN.

- [ ] **Step 12: Vérifier RED puis GREEN rang/GIN**

Run: `cd services/rag-engine && make test-integration-hybrid`

Expected: contrôles négatifs observés et
`RANK_50_DETERMINISTIC=PASS`, `GIN_PLAN=PASS`.

- [ ] **Step 13: Écrire le test pipeline réel**

Injecter embedder/reranker déterministes, mais utiliser `PgCandidateStore` et
les deux SQL réels. Exiger union dense/lexicale, reviewed-only, exclusion des
provenances incomplètes, page non positive normalisée, dédup document, ordre et
scores exacts. Contrôle négatif : embedder à dimension 2 doit lever
`RetrievalPipelineError` sans requête SQL de fallback.

- [ ] **Step 14: Vérifier pipeline réel**

Run: `cd services/rag-engine && make test-integration-hybrid`

Expected: `HYBRID_REAL_DB=PASS` et contrôle négatif dimension observé.

- [ ] **Step 15: Écrire le smoke HTTP `/search/v2`**

Monter un FastAPI/TestClient avec auth/config de test, modèles déterministes et
pool vers la vraie base. Un premier appel avec store forcé en erreur doit
retourner 503 générique ; l'appel réel doit retourner 200, scores/citation/page
attendus, uniquement reviewed et ordre stable.

- [ ] **Step 16: Vérifier smoke search**

Run: `cd services/rag-engine && make test-integration-hybrid`

Expected: `HTTP_SEARCH_V2=PASS`.

- [ ] **Step 17: Écrire le smoke HTTP `/chat`**

Définir une clé OpenRouter factice et remplacer tout appel réseau par une
fonction qui lève. Avec zéro puis plusieurs hits réels, exiger toujours
`answer_generation_locked`, aucune citation générée et mapping retrieval selon
`include_retrieval`.

- [ ] **Step 18: Vérifier smoke chat et stabilité**

Run deux fois: `cd services/rag-engine && make test-integration-hybrid`

Expected deux fois: `HTTP_CHAT_LOCKED=PASS`, head 002 et zéro conteneur/volume
résiduel. Un échec déclenche @superpowers:systematic-debugging ; ne pas
assouplir seuil, assertions, filtres ou digest.

- [ ] **Step 19: Vérifier explicitement le cleanup**

Run:

```bash
set -o pipefail
if leftovers="$(docker ps -a --format '{{.Names}}' | rg '^lot40-pg-')"; then
  printf '%s\n' "$leftovers" >&2
  exit 1
fi
if leftovers="$(docker volume ls --format '{{.Name}}' | rg '^lot40-pg-volume-')"; then
  printf '%s\n' "$leftovers" >&2
  exit 1
fi
```

Expected: aucune sortie après succès, timeout et les deux échecs SQL attendus.

- [ ] **Step 20: Commit atomique**

```bash
git add services/rag-engine/Makefile \
  services/rag-engine/infra/scripts/test_hybrid_integration.sh \
  services/rag-engine/tests/test_hybrid_integration_runner.py \
  services/rag-engine/tests/integration/test_lot40_hybrid_pgvector.py
git commit -m "rag-engine: prouver le retrieval sur pgvector réel"
```

### Task 9: Rendre l'intégration obligatoire dans les deux CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci-local.sh`
- Modify: `scripts/tests/test-ci-local-topology.sh`
- Modify: `scripts/tests/test-ci-local-failsafe.sh`

- [ ] **Step 1: Écrire les assertions topologiques RED**

Dans le test de topologie, parser le YAML avec Python. Dans
`jobs["rag-engine"]["steps"]`, exiger un unique mapping ayant exactement
`working-directory: services/rag-engine` et `run: make test-integration-hybrid`,
placé après le step exact `run: make test`. Ce mapping ne doit avoir ni `if`, ni
`continue-on-error`, ni `shell`; la chaîne `run` exacte rejette aussi `|| true`,
`; true` et les shells tolérants. Le step ne peut appartenir à un autre job.

Pour `ci-local.sh`, extraire `run_engine` avec le helper awk existant et exiger
après le bloc `make test` le bloc exact :

```bash
if ! make test-integration-hybrid; then
    echo "FAIL: rag-engine hybrid integration failed"
    deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
fi
```

- [ ] **Step 2: Vérifier RED**

Run: `bash scripts/tests/test-ci-local-topology.sh && bash scripts/tests/test-ci-local-failsafe.sh`

Expected: FAIL car les deux CI n'appellent pas encore la cible.

- [ ] **Step 3: Écrire les mutations RED anti-contournement GitHub**

Le test crée six copies YAML et applique séparément : `if: false`,
`continue-on-error: true`, `shell: bash {0}`, suffixe `|| true`, déplacement du
step vers `repository-controls`, et placement avant `make test`. Appeler le même
validateur sur chaque copie et exiger six statuts non nuls, puis un statut nul
sur une fixture canonique minimale.

- [ ] **Step 4: Écrire le fail-safe local avec faux `make`**

Construire un repo temporaire minimal et mettre un faux `make` dans PATH. Sur
`install`, il crée `.venv/bin/activate`; sur lint/typecheck/test il retourne 0;
sur `test-integration-hybrid` il retourne 23 et journalise l'appel exact.
Sourcer **uniquement** la fonction `run_engine` extraite, avec `REPO_ROOT`
pointant vers ce repo, l'appeler directement, puis exiger retour 1, message
`FAIL: rag-engine hybrid integration failed`, et un seul appel de la cible.
Aucune autre cible de `ci-local.sh` n'est exécutée.

- [ ] **Step 5: Vérifier RED des mutations/fail-safe**

Run: `bash scripts/tests/test-ci-local-topology.sh && bash scripts/tests/test-ci-local-failsafe.sh`

Expected: FAIL avant raccordement, et les contrôles mutants eux-mêmes sont
sensibles (la fixture canonique seule est acceptée).

- [ ] **Step 6: Raccorder explicitement les deux CI**

Dans `.github/workflows/ci.yml`, ajouter après `make test` un step
working-directory `services/rag-engine` exécutant
`make test-integration-hybrid`. Dans `run_engine`, ajouter le même appel avec
un bloc d'erreur distinct avant désactivation du venv. Ne pas imbriquer
`ci-local.sh` dans un autre audit.

- [ ] **Step 7: Vérifier topologie, mutations et fail-safe**

Run: `YAML_PYTHON_BIN=services/rag-engine/.venv/bin/python bash scripts/tests/test-ci-local-topology.sh`

Run: `YAML_PYTHON_BIN=services/rag-engine/.venv/bin/python NEXUS_CI_LOCAL_RUNNING=1 bash scripts/tests/test-ci-local-failsafe.sh`

Expected: PASS.

- [ ] **Step 8: Commit atomique**

```bash
git add .github/workflows/ci.yml scripts/ci-local.sh \
  scripts/tests/test-ci-local-topology.sh scripts/tests/test-ci-local-failsafe.sh
git commit -m "rag-engine: imposer le smoke hybride dans la CI"
```

### Task 10: Vérifier exhaustivement et rédiger le rapport de lot

**Files:**
- Create: `docs/reports/lot_40_hybrid_retrieval.md`
- Modify only if a verified defect requires it: files already listed in Tasks 1-9

- [ ] **Step 1: Exécuter les suites ciblées fraîches**

```bash
cd services/rag-engine
PYTHONPATH=src .venv/bin/pytest \
  tests/test_pgvector_v2_schema.py tests/test_pg_pool.py \
  tests/test_retrieval_hybrid_v2.py tests/test_retrieval_pg_v2.py \
  tests/test_retrieval_v2_endpoint.py tests/test_retrieval_v2_gate.py \
  tests/test_review_visibility.py tests/test_retrieval_v2_cli.py -q
make test-integration-hybrid
```

Expected: PASS, head final 002, smoke HTTP PASS, aucun reliquat Docker.

- [ ] **Step 2: Exécuter la qualité complète du service**

Run: `cd services/rag-engine && make lint && make typecheck && make test`

Expected: PASS sans régression par rapport à la baseline verte.

- [ ] **Step 3: Exécuter les garde-fous racine**

Depuis la racine du worktree :

```bash
bash scripts/check-governance-locks.sh
bash scripts/check-repository-hygiene.sh
bash scripts/tests/test-ci-local-topology.sh
bash scripts/tests/test-ci-local-failsafe.sh
git diff --check main...HEAD
```

Expected: PASS et aucun verrou activé.

- [ ] **Step 4: Exécuter la CI locale intégrale**

Run: `bash scripts/ci-local.sh`

Expected: résumé entièrement PASS, incluant explicitement
`make test-integration-hybrid`. Si le Python système relocalisé est cassé,
appliquer @superpowers:systematic-debugging et utiliser un `PATH` temporaire
pointant vers le Python 3.11 géré par uv ; ne modifier ni ignorer la CI.

- [ ] **Step 5: Produire le rapport factuel**

Créer `docs/reports/lot_40_hybrid_retrieval.md` en français. Inclure : périmètre
et hors-périmètre, SHAs de base/candidat obtenus par `git rev-parse`, image OCI,
head/checksums obtenus par le runner, commandes et comptes exacts, matrice de
preuve `{contrôle, responsable, environnement, artefact, digest/SHA, verdict}`,
preuve de cleanup Docker, revue indépendante, risques résiduels LOT41-43 et
verdict `GO_LIVE: NO_GO`. À ce stade écrire exactement
`REVUE_INDÉPENDANTE: PENDING`, sans verdict de revue ; la Task 11 la mettra à
jour après exécution. Ne jamais inscrire PASS avant la preuve associée.

- [ ] **Step 6: Vérifier rapport, secrets et diff**

```bash
git diff --check
git status --short
added_lines="$({
  git diff --unified=0 main -- services/rag-engine
} | sed -n '/^+++ /d; /^+/s/^+//p')"
if matches="$({
  printf '%s\n' "$added_lines"
  cat docs/reports/lot_40_hybrid_retrieval.md
} | \
  rg -n '/home/|OPENROUTER_API_KEY=.+|postgresql://[^[:space:]]+:[^@[:space:]]+@')"
then
  printf '%s\n' "$matches" >&2
  exit 1
fi
```

Expected: aucune fuite ou chemin absolu machine-local **dans les lignes
ajoutées**. Les en-têtes/contextes historiques du diff ne sont pas scannés et
aucun `|| true` ne neutralise le verdict.

- [ ] **Step 7: Commit du rapport**

```bash
git add docs/reports/lot_40_hybrid_retrieval.md
git commit -m "rag-engine: consigner les preuves du LOT40"
```

### Task 11: Revue indépendante, PR, checks et fusion

**Files:**
- Modify only for findings verified: files in the reviewed diff
- Finalize: `docs/reports/lot_40_hybrid_retrieval.md`

- [ ] **Step 1: Vérification avant publication**

Utiliser @superpowers:verification-before-completion sur des sorties fraîches.
Exiger worktree propre, branche en avance uniquement des commits LOT40, stashes
historiques inchangés, et `git diff --stat main...HEAD` limité au lot.

- [ ] **Step 2: Revue de code indépendante**

Utiliser @superpowers:requesting-code-review puis la skill `code-review` sur
`main...HEAD`. Corriger chaque P0/P1 en TDD et faire re-relire. Documenter les
P2 acceptés avec justification dans le rapport ; ne pas masquer un finding.
Remplacer alors `REVUE_INDÉPENDANTE: PENDING` par le verdict, le reviewer, le
SHA relu et la liste exacte des findings.

- [ ] **Step 3: Rejouer toutes les preuves après la dernière correction**

Rejouer Tasks 10.1 à 10.4 sur le SHA candidat final, mettre à jour le rapport,
commit puis vérifier que le SHA reporté correspond à `git rev-parse HEAD` ou au
commit de code explicitement identifié sans circularité documentaire.

- [ ] **Step 4: Publier une draft PR**

Utiliser la skill `github:yeet` : pousser `lot-40-hybrid-retrieval`, ouvrir une
draft PR vers `main`, inclure périmètre, preuves, head 002, digest OCI et
`GO_LIVE: NO_GO`. Aucun push direct vers `main`.

- [ ] **Step 5: Attendre et vérifier les checks GitHub**

Sur le SHA exact de la PR, exiger les six contextes protégés, notamment le job
`services/rag-engine` contenant l'intégration réelle. Tout échec déclenche
@superpowers:systematic-debugging et une nouvelle vérification complète.

- [ ] **Step 6: Finaliser puis fusionner**

Passer la PR ready uniquement après checks et revue verts. Utiliser squash merge
conforme à l'historique linéaire, vérifier le SHA de merge, le run post-merge de
`main`, les protections et `origin/main`. Supprimer branche/worktree seulement
après preuve d'équivalence des arbres ; préserver les stashes.

- [ ] **Step 7: Verdict de lot**

LOT40 peut être `MERGED/PASS` lorsque `main` contient le tree vérifié. Le projet
global demeure explicitement `GO_LIVE: NO_GO` tant que LOT41, LOT41A, LOT42,
LOT43 et les autres barrières du design canonique ne sont pas clos.
