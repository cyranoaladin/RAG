#!/usr/bin/env bash
# Orchestration complète du provisioning du plan de contrôle ingestion_control
# pour un déploiement réel (LOT44f, ADR-0029) : enchaîne les deux scripts
# LOT44b existants (non modifiés) dans le bon ordre.
#
# Ordre nécessaire, déterminé empiriquement en rejouant les deux scripts
# contre un PostgreSQL jetable (l'ordre inverse échoue explicitement,
# documenté ici pour ne pas être redécouvert en incident) :
#   1. bootstrap_ingestion_control_schema.sh, connecté en tant que
#      superutilisateur (mêmes identifiants que le service `migrator`
#      pgvector existant — cohérent avec le seul autre migrateur du
#      dépôt) : applique les migrations 001..HEAD, crée le schéma et les
#      tables s'ils n'existent pas encore.
#   2. provision_ingestion_control_roles.sh, connecté en tant que ce même
#      superutilisateur (seul habilité CREATEROLE) : crée les rôles
#      ingestion_control_migrator/ingestion_control_app, transfère la
#      propriété du schéma au rôle de migration, et accorde au rôle
#      applicatif exactement les privilèges nécessaires table par table.
#      Ses instructions GRANT référencent des tables qui doivent déjà
#      exister — condition nécessaire pour que l'ordre inverse échoue
#      explicitement plutôt que silencieusement.
#
# Limite assumée et documentée (pas résolue ici, hors périmètre LOT44f) :
# ALTER SCHEMA ... OWNER TO (étape 2) ne transfère jamais la propriété des
# tables déjà créées par le superutilisateur à l'étape 1 — seulement celle
# du schéma. Une future migration numérotée qui modifierait une table
# existante (ALTER TABLE, comme la migration 005 elle-même) doit donc
# continuer d'être appliquée avec les identifiants superutilisateur, jamais
# avec le rôle ingestion_control_migrator seul, tant qu'aucun script de
# reprise de propriété (REASSIGN OWNED / ALTER TABLE ... OWNER TO par
# table) n'a été ajouté. Ce script utilise donc systématiquement le
# superutilisateur pour l'étape 1, à chaque exécution, jamais le rôle de
# migration — cohérent avec le comportement actuel, pas un raccourci
# nouveau.
#
# Usage : PGHOST=... PGPORT=... PGDATABASE=... \
#         PGUSER=<superutilisateur> PGPASSWORD=<mot de passe superutilisateur> \
#         INGESTION_CONTROL_MIGRATOR_PASSWORD=... \
#         INGESTION_CONTROL_APP_PASSWORD=... \
#         ./scripts/provision_and_bootstrap_ingestion_control.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

: "${PGHOST:?PGHOST must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"
: "${PGPASSWORD:?PGPASSWORD must be set}"
: "${INGESTION_CONTROL_MIGRATOR_PASSWORD:?INGESTION_CONTROL_MIGRATOR_PASSWORD must be set}"
: "${INGESTION_CONTROL_APP_PASSWORD:?INGESTION_CONTROL_APP_PASSWORD must be set}"

echo "STEP=bootstrap_schema"
"$SCRIPT_DIR/bootstrap_ingestion_control_schema.sh"

echo "STEP=provision_roles"
"$SCRIPT_DIR/provision_ingestion_control_roles.sh"

echo "PROVISION_AND_BOOTSTRAP_COMPLETE"
