#!/usr/bin/env bash
# Signature LOCALE par le détenteur de la clé, après fusion de l'activation.
# Usage : ... --private-key-file /chemin/hors/depot/seed --output-dir /chemin/local
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"

TARGET="$($PYTHON - <<'PY'
import json
import sys
sys.path.insert(0, "scripts/go_live")
import check_staging_authorization as auth
print(json.dumps(auth.OPERATIONS_HGGSP["successor_readiness_sign"]["cible"]))
PY
)"
"$PYTHON" scripts/go_live/check_staging_authorization.py \
  --operation successor_readiness_sign --cible "$TARGET" >/dev/null
"$PYTHON" scripts/go_live/hggsp_successor_readiness.py sign "$@"
