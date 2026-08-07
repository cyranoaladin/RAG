#!/usr/bin/env bash
# Bootstrap/catch-up automatique du schéma ingestion_control (LOT44b).
#
# Applique, dans l'ordre, les migrations numérotées de
# infra/postgres/ingestion_control/migrations/*.sql sur le schéma logique
# dédié "ingestion_control" — décision D1 : même instance PostgreSQL/pgvector
# que le reste du projet, jamais mélangé au schéma "public"/rag_chunks.
#
# Différence assumée par rapport à bootstrap_pgvector_schema.sh /
# pgvector_migration_state.sh : ce script ne réutilise pas la bibliothèque
# rag_chunks (validate_001_sql, etc. y encodent en dur des colonnes/index
# spécifiques à rag_chunks — non généralisable sans dupliquer 1000+ lignes
# de validation de catalogue pour un schéma différent). Ce script applique
# une version proportionnée du même principe : registre versionné, checksum
# par migration, verrou pour éviter une double application concurrente, et
# revalidation explicite après application — mais sans le fingerprint
# exhaustif de catalogue Postgres (colonnes/contraintes/index un par un)
# que pgvector_migration_state.sh applique pour rag_chunks. Documenté comme
# réserve dans le rapport LOT44b.
#
# Usage : PGHOST=... PGPORT=... PGUSER=... PGPASSWORD=... PGDATABASE=... \
#         ./scripts/bootstrap_ingestion_control_schema.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$INFRA_DIR/postgres/ingestion_control/migrations"
HEAD_FILE="$MIGRATIONS_DIR/HEAD"

: "${PGHOST:?PGHOST must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"

[[ -f "$HEAD_FILE" ]] || { echo "FATAL: HEAD file missing: $HEAD_FILE" >&2; exit 1; }
declared_head_name="$(<"$HEAD_FILE")"

CONNECT_RETRIES="${BOOTSTRAP_CONNECT_RETRIES:-30}"
CONNECT_DELAY_SECONDS="${BOOTSTRAP_CONNECT_DELAY_SECONDS:-1}"

wait_for_connection() {
    local attempt
    for ((attempt = 1; attempt <= CONNECT_RETRIES; attempt++)); do
        if psql -X -q -A -t -v ON_ERROR_STOP=1 -c 'SELECT 1;' >/dev/null 2>&1; then
            return 0
        fi
        sleep "$CONNECT_DELAY_SECONDS"
    done
    echo "FATAL: cannot reach PostgreSQL at $PGHOST:${PGPORT:-5432} after $CONNECT_RETRIES attempts" >&2
    return 1
}

# Discover the manifest: NNN_description.sql, contiguous from 1, no gaps,
# no duplicates — same discipline as pgvector_migration_state.sh, kept
# local here since it is a handful of lines, not worth a shared dependency
# for a single caller.
discover_manifest() {
    local entry basename number stem expected
    local -a candidates=()
    MIGRATION_VERSIONS=()
    MIGRATION_NAMES=()
    MIGRATION_FILES=()
    MIGRATION_SHA256=()

    # Remédiation revue PR#90 (Cubic P2) : découvre TOUS les fichiers .sql
    # (pas seulement ceux déjà nommés correctement) — un glob restreint au
    # motif attendu laisse passer silencieusement un fichier mal nommé
    # (extension .SQL, préfixe à 2 chiffres, caractère interdit) : il
    # n'apparaît jamais dans $candidates, donc jamais rejeté par la
    # vérification stricte ci-dessous, et le bootstrap peut réussir en
    # laissant le schéma en retard sans le moindre avertissement. Élargir
    # la découverte garantit que la vérification stricte s'applique
    # réellement à tout fichier .sql présent dans le répertoire.
    # Remédiation revue PR#90 (Cubic P3, revue incrémentale) : `-name` est
    # sensible à la casse sur Linux — malgré le commentaire ci-dessus
    # annonçant explicitement la découverte d'un fichier `.SQL`, seul
    # `-iname` le garantit réellement ; `-name '*.sql'` seul laissait
    # passer silencieusement un fichier `.SQL` (majuscules), exactement le
    # scénario que ce garde-fou prétend couvrir.
    mapfile -t candidates < <(
        find "$MIGRATIONS_DIR" -maxdepth 1 -type f \
            -iname '*.sql' -print | LC_ALL=C sort
    )
    [[ ${#candidates[@]} -gt 0 ]] || { echo "FATAL: no migration files found in $MIGRATIONS_DIR" >&2; exit 1; }

    expected=1
    for entry in "${candidates[@]}"; do
        basename="$(basename "$entry")"
        [[ "$basename" =~ ^([0-9]{3})_([a-z0-9_]+)\.sql$ ]] \
            || { echo "FATAL: invalid migration filename: $basename" >&2; exit 1; }
        number=$((10#${BASH_REMATCH[1]}))
        (( number == expected )) \
            || { echo "FATAL: migration gap/duplicate at $(printf '%03d' "$expected"), found $basename" >&2; exit 1; }
        MIGRATION_VERSIONS+=("$number")
        MIGRATION_NAMES+=("$basename")
        MIGRATION_FILES+=("$entry")
        MIGRATION_SHA256+=("$(sha256sum "$entry" | awk '{print $1}')")
        expected=$((expected + 1))
    done

    stem="${MIGRATION_NAMES[${#MIGRATION_NAMES[@]} - 1]%.sql}"
    [[ "$stem" == "$declared_head_name" ]] \
        || { echo "FATAL: HEAD ($declared_head_name) does not match last migration ($stem)" >&2; exit 1; }
}

registry_schema_sql() {
    cat <<'SQL'
CREATE SCHEMA IF NOT EXISTS ingestion_control;
CREATE TABLE IF NOT EXISTS ingestion_control.schema_migrations (
    version     INTEGER PRIMARY KEY,
    file_name   TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL
}

advisory_lock_sql() {
    # Clé arbitraire mais stable, distincte de celle de pgvector_migration_state.sh
    # (namespace différent : ingestion_control, pas rag_chunks).
    echo "SELECT pg_advisory_xact_lock(72144, 1);"
}

read_registry_state() {
    local output
    APPLIED_VERSIONS=()
    APPLIED_SHA256=()
    output="$(psql -X -q -A -t -F'|' -v ON_ERROR_STOP=1 -c "
        SELECT version, sha256 FROM ingestion_control.schema_migrations
        ORDER BY version;
    " 2>/dev/null || true)"
    while IFS='|' read -r version sha; do
        [[ -z "$version" ]] && continue
        APPLIED_VERSIONS+=("$version")
        APPLIED_SHA256+=("$sha")
    done <<< "$output"
}

verify_no_checksum_drift() {
    local index=0
    for version in "${APPLIED_VERSIONS[@]}"; do
        local declared_sha="${MIGRATION_SHA256[$((version - 1))]}"
        local stored_sha="${APPLIED_SHA256[$index]}"
        if [[ "$declared_sha" != "$stored_sha" ]]; then
            echo "FATAL: MIGRATION_CHECKSUM_MISMATCH version=$version stored=$stored_sha declared=$declared_sha" >&2
            exit 1
        fi
        index=$((index + 1))
    done
}

apply_migration() {
    local version="$1"
    local index=$((version - 1))
    local file="${MIGRATION_FILES[$index]}"
    local name="${MIGRATION_NAMES[$index]}"
    local sha="${MIGRATION_SHA256[$index]}"

    {
        advisory_lock_sql
        registry_schema_sql
        cat "$file"
        printf '\n'
        # Remédiation revue PR#90 (Cubic P2, revue incrémentale) : deux
        # instances de ce script démarrées en concurrence calculent chacune
        # leur propre plage de versions à appliquer à partir d'une lecture
        # de schema_migrations faite AVANT que le verrou advisory ne soit
        # jamais pris (read_registry_state, au tout début du script) — la
        # seconde instance, bloquée le temps que la première committe sa
        # propre transaction pour cette version, reste programmée pour
        # rejouer cette MÊME version dès que le verrou se libère. Le corps
        # de chaque migration est déjà idempotent (IF NOT EXISTS partout,
        # documenté comme tel), donc le rejeu du DDL lui-même est sans
        # danger — seul cet INSERT ne l'était pas (échouait sur une
        # violation de clé primaire au lieu d'un no-op silencieux).
        # ``ON CONFLICT (version) DO NOTHING`` aligne l'enregistrement sur
        # la même idempotence que le reste de cette migration.
        printf '%s\n' \
            "INSERT INTO ingestion_control.schema_migrations (version, file_name, sha256)" \
            "VALUES (:'migration_version'::integer, :'migration_file', :'migration_sha')" \
            "ON CONFLICT (version) DO NOTHING;"
    } | psql -X -q --single-transaction \
        -v ON_ERROR_STOP=1 \
        -v "migration_version=$version" \
        -v "migration_file=$name" \
        -v "migration_sha=$sha" >/dev/null
}

verify_expected_tables_exist() {
    psql -X -q -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
DO $$
BEGIN
    IF to_regclass('ingestion_control.ingestion_runs') IS NULL
       OR to_regclass('ingestion_control.resources') IS NULL
       OR to_regclass('ingestion_control.resource_candidates') IS NULL
       OR to_regclass('ingestion_control.artifacts') IS NULL
       OR to_regclass('ingestion_control.workflow_events') IS NULL
       OR to_regclass('ingestion_control.jobs') IS NULL THEN
        RAISE EXCEPTION 'INGESTION_CONTROL_SCHEMA_INCOMPLETE';
    END IF;
END
$$;
SQL
}

wait_for_connection
discover_manifest
# Remédiation revue PR#90 (Cubic P2, revue incrémentale) : cette création
# initiale du schéma/registre s'exécutait auparavant hors de toute
# protection — deux instances de ce script démarrant en concurrence (ex.
# conteneur migrateur relancé/dupliqué) pouvaient toutes deux voir
# "n'existe pas encore" (CREATE SCHEMA/TABLE IF NOT EXISTS n'est pas
# atomique contre une création concurrente en READ COMMITTED, comportement
# documenté PostgreSQL) et tenter chacune la création, l'une des deux
# échouant alors sur une erreur de clé dupliquée au lieu du no-op attendu.
# Protégée désormais par le même verrou advisory transactionnel que
# ``apply_migration`` (même clé, même transaction unique) — une seconde
# instance concurrente attend simplement la fin de la première au lieu de
# tenter la même création en parallèle.
{
    advisory_lock_sql
    registry_schema_sql
} | psql -X -q --single-transaction -v ON_ERROR_STOP=1 >/dev/null
read_registry_state
verify_no_checksum_drift

declared_head="${#MIGRATION_VERSIONS[@]}"
current_head="${#APPLIED_VERSIONS[@]}"

applied_count=0
for ((version = current_head + 1; version <= declared_head; version++)); do
    apply_migration "$version"
    applied_count=$((applied_count + 1))
done

# Revalidation : ne jamais faire confiance à sa propre comptabilité.
read_registry_state
verify_no_checksum_drift
if (( ${#APPLIED_VERSIONS[@]} != declared_head )); then
    echo "FATAL: schema head after bootstrap (${#APPLIED_VERSIONS[@]}) does not match declared head ($declared_head)" >&2
    exit 1
fi
verify_expected_tables_exist

echo "MIGRATIONS_APPLIED=$applied_count"
echo "SCHEMA_VERIFICATION=OK"
echo "BOOTSTRAP_COMPLETE"
echo "SCHEMA_HEAD=$declared_head"
