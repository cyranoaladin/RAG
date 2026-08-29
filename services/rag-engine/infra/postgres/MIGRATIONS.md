# Procédure de migration pgvector — convergence vers le HEAD 004

> Objectif : qu'un `docker compose up -d` converge vers le HEAD canonique
> `004_artifact_placements`, **aussi bien sur un volume neuf que sur un volume
> existant**. Ces deux cas empruntent des chemins différents ; c'est la source
> des dérives constatées le 27 août 2026.

## 1. Le HEAD et son contrat

Le HEAD est déclaré dans `postgres/migrations/HEAD` (`004_artifact_placements`)
et vérifié par trois validateurs partagés :

| Fichier | Rôle |
|---|---|
| `scripts/lib/pgvector_migration_state.sh` | validateurs SQL `validate_001..004_sql`, `validate_registry_sql` — **source de vérité** |
| `postgres/healthcheck.sh` | healthcheck du conteneur : rejoue les validateurs, sans mutation |
| `postgres/schema_head_004_columns.tsv` / `..._fingerprints.env` | matrice de colonnes et empreintes MD5 des contraintes/index |

Ces validateurs sont **exacts, pas permissifs** : ils comparent le catalogue
PostgreSQL colonne par colonne, contrainte par contrainte, index par index, et
refusent tout objet hors de la liste attendue. Une colonne en trop, un `DEFAULT`
absent ou une contrainte `CHECK` ajoutée à la main suffisent à faire échouer le
healthcheck.

Le registre des migrations appliquées est la table **`rag_schema_migrations`**
`(version, file_name, sha256, applied_at)`.

> ⚠️ Ne pas confondre avec la table héritée `schema_migrations`
> `(version, applied_at, checksum, note)`, qu'aucun code du contrat ne lit. Elle
> subsiste, vide et inerte, dans les bases anciennes. Ne pas s'y fier.

**Checksum** : `sha256sum <fichier> | cut -d' ' -f1`, calculé sur le fichier de
migration tel quel. C'est la seule méthode admise — `validate_registry_sql`
compare le registre au manifest recalculé et lève `MIGRATION_CHECKSUM_MISMATCH`
à la moindre divergence.

## 2. Cas A — volume neuf

Chemin automatique, aucune action manuelle. PostgreSQL exécute
`docker-entrypoint-initdb.d/` dans l'ordre lexicographique :

| Ordre | Fichier | Effet |
|---|---|---|
| `00_init.sql` | `postgres/init.sql` | extensions, `rag_chunks` complète (001+002 fusionnées), tables auxiliaires |
| `01_003_…` | migration 003 | colonnes de profil + contraintes LOT41 + index partiel |
| `02_004_…` | migration 004 | `rag_artifacts`, `rag_artifact_placements`, `artifact_id` |
| `03_register_bootstrap_migrations.sh` | | crée `rag_schema_migrations` et y inscrit les versions 1 à 4 |
| `04_provision_runtime_roles.sh` | | crée `rag_reader`, `rag_reviewer`, `rag_publisher` au moindre privilège |

Au premier healthcheck, le contrat est satisfait.

> `init.sql` porte déjà `text_tsv` et les `DEFAULT` attendus par 001 : un volume
> neuf ne reproduit **pas** les dérives décrites au §4.

## 3. Cas B — volume existant

`docker-entrypoint-initdb.d/` n'est **jamais** rejoué sur un volume déjà
initialisé. Une base créée avant l'introduction de 003/004 y reste donc
indéfiniment : le healthcheck échoue, `ingestor` ne démarre pas, et rien ne
corrige la situation tout seul. C'est le chemin de rattrapage :

> **Cibler la bonne base.** Le conteneur pgvector dépend du projet Compose, et
> le projet décide du volume atteint (ADR-0051). La pile canonique est
> `nexusrag`. Résoudre le conteneur par son étiquette Compose plutôt que par un
> nom codé en dur — un nom codé en dur atteint la mauvaise base sans le dire.

```bash
cd services/rag-engine/infra

# Conteneur pgvector du projet canonique, résolu par étiquette.
PGC=$(docker ps --filter label=com.docker.compose.project=nexusrag \
                --filter label=com.docker.compose.service=pgvector \
                --format '{{.Names}}')
test -n "$PGC" || { echo "pile canonique non demarree" >&2; exit 1; }

# 1. Sauvegarder — obligatoire, aucune écriture avant que le dump existe.
mkdir -p ~/sauvegardes-rag && chmod 700 ~/sauvegardes-rag
TS=$(date +%Y%m%d_%H%M%S)
docker exec "$PGC" pg_dump -U raguser -d ragdb \
    --format=custom --file=/tmp/ragdb_$TS.dump
docker cp "$PGC":/tmp/ragdb_$TS.dump ~/sauvegardes-rag/
docker exec "$PGC" rm -f /tmp/ragdb_$TS.dump

# 2. Vérifier que le dump se RESTAURE (le lister ne suffit pas).
docker cp ~/sauvegardes-rag/ragdb_$TS.dump "$PGC":/tmp/verif.dump
docker exec "$PGC" psql -U raguser -d postgres \
    -c "DROP DATABASE IF EXISTS ragdb_verif;" -c "CREATE DATABASE ragdb_verif;"
docker exec "$PGC" pg_restore -U raguser -d ragdb_verif \
    --exit-on-error /tmp/verif.dump

# 3. Répéter la remédiation sur la copie jetable, puis la valider
#    contre le healthcheck réel.
PGVECTOR_DB=ragdb_verif ./scripts/remediate-pgvector-to-head-004.sh
docker exec -e POSTGRES_DB=ragdb_verif -e POSTGRES_USER=raguser \
    "$PGC" bash /docker-entrypoint-healthcheck.sh && echo "contrat OK"

# 4. Répétition à blanc sur la vraie base, puis application.
./scripts/remediate-pgvector-to-head-004.sh --dry-run
./scripts/remediate-pgvector-to-head-004.sh

# 5. Provisionner les rôles runtime s'ils manquent (script idempotent).
docker exec "$PGC" bash \
    /docker-entrypoint-initdb.d/04_provision_runtime_roles.sh

# 6. Nettoyer la base jetable.
docker exec "$PGC" psql -U raguser -d postgres \
    -c "DROP DATABASE IF EXISTS ragdb_verif;"

# 7. Relancer la pile.
./scripts/rag-stack.sh up -d   # jamais de -p : cf. ADR-0051
```

`remediate-pgvector-to-head-004.sh` est **idempotent** : un second passage sur
une base déjà convergée ne fait rien (`INSERT 0 0`, migrations « déjà
appliquée, ignorée ») et laisse le healthcheck vert. Il peut donc être rejoué
sans risque, y compris dans un script de déploiement.

Toutes les écritures tiennent dans **une seule transaction**, protégée par le
même verrou consultatif que l'outillage de migration
(`pg_advisory_xact_lock(hashtext('nexus-rag-schema-migrations'))`). Aucune
migration 001→004 ne contient `CREATE INDEX CONCURRENTLY` — la transaction
unique est donc légitime. **Toute migration future qui en introduirait une
casserait cette propriété** et devrait être sortie de la transaction
explicitement.

## 4. Dérives connues d'une base « bricolée » et leur traitement

Constatées sur `ragdb` le 27 août 2026, toutes traitées par le script de
remédiation. Aucune ne provenait des migrations : toutes avaient été introduites
hors du système de migrations.

| # | Dérive | Symptôme | Traitement |
|---|---|---|---|
| 1 | `DEFAULT` absents sur `audience`, `statut_enseignement`, `source_kind` | `SCHEMA_HEAD_001_INVALID: exact column catalog matrix` | `ALTER COLUMN … SET DEFAULT` |
| 2 | Colonne générée `tsv` + `idx_rag_chunks_tsv`, doublon exact de `text_tsv` | `SCHEMA_HEAD_001_INVALID: unexpected columns` | `DROP INDEX` puis `DROP COLUMN` |
| 3 | 4 contraintes `CHECK` hors contrat, absentes du dépôt | `SCHEMA_HEAD_001_INVALID: unexpected constraints` | `DROP CONSTRAINT` nominatif |
| 4 | Migrations 003 et 004 jamais appliquées | colonnes et tables manquantes | application gardée |
| 5 | `rag_schema_migrations` inexistante | `MIGRATION_REGISTRY_MISSING` | création + inscription 1→4 |
| 6 | Rôles runtime non provisionnés | `password authentication failed for user "rag_reader"` | `04_provision_runtime_roles.sh` |

**Piège de vérification.** Pour comparer un `DEFAULT` au contrat, comparer la
valeur *rendue par le catalogue*, pas celle qu'on écrit : PostgreSQL normalise
`'{tous}'` en `'{tous}'::text[]`. Les validateurs retirent le suffixe de type
avant de comparer :

```sql
regexp_replace(lower(pg_get_expr(d.adbin, d.adrelid)),
               '(::text\[\]|::text|[[:space:]])', '', 'g')
```

## 5. Ajouter une migration 005

1. Créer `postgres/migrations/005_<nom_en_snake_case>.sql`. Le nom doit vérifier
   `^[0-9]{3}_[a-z0-9_]+\.sql$` et la numérotation être **sans trou** —
   `discover_manifest` refuse `MIGRATION_GAP`.
2. Mettre `005_<nom>` dans `postgres/migrations/HEAD`.
3. Étendre `validate_005_sql` (et les listes d'autorisation de
   `validate_001_sql` si de nouvelles colonnes/index/contraintes apparaissent
   sur `rag_chunks`), puis régénérer `schema_head_004_columns.tsv` et
   `schema_head_004_fingerprints.env` sous leur nom 005.
4. Ajouter la version 5 à `register_bootstrap_migrations.sh` **et** à
   `remediate-pgvector-to-head-004.sh` (garde d'application + inscription).
5. Prévoir le rollback dans `postgres/rollbacks/`.
6. Vérifier les deux chemins : volume neuf (`down -v` sur une pile jetable,
   jamais sur `infra_rag_pgvector_data`) **et** volume existant (script de
   remédiation).

> ⚠️ Ne jamais supprimer ni recréer le volume `infra_rag_pgvector_data`.
