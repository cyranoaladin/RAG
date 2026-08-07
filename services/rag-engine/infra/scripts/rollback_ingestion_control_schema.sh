#!/usr/bin/env bash
# Runner officiel de rollback du schéma ingestion_control (LOT44f,
# remédiation revue PR#90, item E — revue incrémentale).
#
# Avant ce script, un rollback s'exécutait via `psql -f rollback.sql`
# fichier par fichier, sans garantie d'atomicité globale : sans
# `--single-transaction`, chaque instruction (y compris `LOCK TABLE ...
# ACCESS EXCLUSIVE`) est committée séparément par psql (mode autocommit
# par défaut), donc le verrou posé par une instruction est déjà relâché
# avant que l'instruction suivante (la garde de vacuité, puis le DROP) ne
# s'exécute — une transaction concurrente peut alors s'intercaler entre le
# verrou et la garde, ou entre la garde et le DROP, défaisant
# silencieusement la protection que `LOCK TABLE` est censée fournir. Ce
# script corrige cela en garantissant, sans exception :
#
#   1. Quiescence de l'ingestion : refuse si un job est `running`, ou si
#      une ressource porte un bail actif (lease_token non nul et non
#      expiré) — un rollback ne doit jamais s'exécuter pendant qu'un
#      worker traite activement des données du schéma qu'il détruit.
#   2. Transaction unique : tout le run (verrous + gardes + DROP/ALTER +
#      mise à jour de schema_migrations) s'exécute dans UNE seule
#      transaction psql (`--single-transaction -v ON_ERROR_STOP=1`) —
#      jamais fichier par fichier.
#   3. Ordre de verrouillage canonique : les huit tables du schéma (six
#      LOT44b/e + scope_authorizations/publication_attestations, LOT41A/
#      LOT42, migrations 007/008) sont verrouillées `IN ACCESS EXCLUSIVE
#      MODE`, toutes ensemble, en tête de la transaction unique, dans un
#      ordre alphabétique fixe (artifacts, ingestion_runs, jobs,
#      publication_attestations, resource_candidates, resources,
#      scope_authorizations, workflow_events) — indépendamment du
#      sous-ensemble de tables réellement affecté par la plage de versions
#      annulée. Un ordre toujours identique élimine tout risque
#      d'interblocage avec un autre processus (ex. le worker) qui
#      verrouillerait plusieurs de ces mêmes tables dans un ordre différent.
#   4. Garde de données : chaque fichier `NNN_*.down.sql` porte déjà sa
#      propre vérification de vacuité (`RAISE EXCEPTION` si des données
#      sont présentes) — désormais réellement protégée par le verrou
#      canonique tenu depuis le tout début de la transaction unique.
#   5. DROP/ALTER : contenu inchangé de chaque fichier `.down.sql`.
#   6. Mise à jour de `schema_migrations` : `DELETE FROM
#      ingestion_control.schema_migrations WHERE version > TARGET_VERSION`,
#      dans la même transaction que les DROP/ALTER — jamais une étape
#      séparée qui pourrait diverger du schéma réellement présent.
#   7. Commit seulement si tout réussit : `--single-transaction` +
#      `ON_ERROR_STOP=1` garantissent qu'un ROLLBACK psql implicite se
#      produit à la moindre erreur (aucun COMMIT n'est jamais atteint) —
#      jamais un état partiel où certaines tables seraient déjà
#      supprimées et d'autres non.
#
# Usage : PGHOST=... PGPORT=... PGUSER=<administratif, superutilisateur ou
#                 propriétaire du schéma> PGPASSWORD=... PGDATABASE=... \
#         TARGET_VERSION=<version de schéma cible, ex. 3 pour annuler 006,
#                 005, 004 et revenir à l'état après 003> \
#         ./scripts/rollback_ingestion_control_schema.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROLLBACKS_DIR="$INFRA_DIR/postgres/ingestion_control/rollbacks"

: "${PGHOST:?PGHOST must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"
: "${TARGET_VERSION:?TARGET_VERSION must be set (schema version to roll back to)}"

if [[ ! "$TARGET_VERSION" =~ ^[0-9]+$ ]]; then
    echo "FATAL: TARGET_VERSION must be a non-negative integer, got: $TARGET_VERSION" >&2
    exit 1
fi

# Ordre canonique de verrouillage — alphabétique, fixe, jamais dérivé de
# l'ordre des migrations ni de la plage annulée (cf. point 3 ci-dessus).
readonly CANONICAL_LOCK_ORDER="ingestion_control.artifacts, ingestion_control.ingestion_runs, ingestion_control.jobs, ingestion_control.publication_attestations, ingestion_control.resource_candidates, ingestion_control.resources, ingestion_control.scope_authorizations, ingestion_control.workflow_events"

current_head="$(psql -X -q -A -t -v ON_ERROR_STOP=1 -c \
    "SELECT COALESCE(max(version), 0) FROM ingestion_control.schema_migrations;")"

if (( TARGET_VERSION >= current_head )); then
    echo "FATAL: TARGET_VERSION ($TARGET_VERSION) must be strictly less than the current schema head ($current_head) — nothing to roll back." >&2
    exit 1
fi

# Point 1 : quiescence de l'ingestion — refuse avant tout accès en
# écriture si un job est en cours ou si une ressource porte un bail actif.
# Requête en lecture seule, connexion dédiée, avant l'ouverture de la
# transaction de rollback elle-même.
quiescence_violation="$(psql -X -q -A -t -v ON_ERROR_STOP=1 -c "
    SELECT count(*) FROM ingestion_control.jobs WHERE status = 'running'
    UNION ALL
    SELECT count(*) FROM ingestion_control.resources
    WHERE lease_token IS NOT NULL AND lease_expires_at > now();
" | awk '{sum += $1} END {print sum}')"

if [[ "$quiescence_violation" != "0" ]]; then
    echo "FATAL: INGESTION_NOT_QUIESCENT — refusing to roll back while jobs are running or resources hold an active lease. Wait for completion or let the lease reaper run, then retry." >&2
    exit 1
fi

# Assemble la plage de versions à annuler, ordre décroissant strict.
declare -a versions_to_rollback=()
for ((v = current_head; v > TARGET_VERSION; v--)); do
    versions_to_rollback+=("$v")
done

sql_script="$(mktemp)"
trap 'rm -f "$sql_script"' EXIT

{
    printf '%s\n' "LOCK TABLE $CANONICAL_LOCK_ORDER IN ACCESS EXCLUSIVE MODE;"
    for v in "${versions_to_rollback[@]}"; do
        matches=("$ROLLBACKS_DIR"/"$(printf '%03d' "$v")"_*.down.sql)
        if [[ ! -f "${matches[0]}" ]]; then
            echo "FATAL: no rollback file found for version $v in $ROLLBACKS_DIR" >&2
            exit 1
        fi
        if (( ${#matches[@]} != 1 )); then
            echo "FATAL: expected exactly one rollback file for version $v, found ${#matches[@]}: ${matches[*]}" >&2
            exit 1
        fi
        cat "${matches[0]}"
        printf '\n'
    done
    printf 'DELETE FROM ingestion_control.schema_migrations WHERE version > %d;\n' "$TARGET_VERSION"
} > "$sql_script"

psql -X -q --single-transaction -v ON_ERROR_STOP=1 -f "$sql_script" >/dev/null

# Revalidation post-commit : ne jamais faire confiance à sa propre
# comptabilité (même discipline que bootstrap_ingestion_control_schema.sh).
new_head="$(psql -X -q -A -t -v ON_ERROR_STOP=1 -c \
    "SELECT COALESCE(max(version), 0) FROM ingestion_control.schema_migrations;")"
if [[ "$new_head" != "$TARGET_VERSION" ]]; then
    echo "FATAL: schema head after rollback ($new_head) does not match TARGET_VERSION ($TARGET_VERSION)" >&2
    exit 1
fi

echo "ROLLBACK_COMPLETE"
echo "SCHEMA_HEAD=$new_head"
