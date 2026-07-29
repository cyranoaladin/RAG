#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
BUILD_TREE="${COCKPIT_BUILD_TREE:-HEAD}"

if ! TREE_OID="$(
  git -C "$REPO_ROOT" rev-parse \
    --verify --quiet --end-of-options "${BUILD_TREE}^{tree}"
)"; then
  echo "COCKPIT_BUILD_TREE ne désigne pas un arbre Git valide: ${BUILD_TREE}" >&2
  exit 2
fi

ARCHIVE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/nexus-cockpit-clean-build.XXXXXX")"
cleanup() {
  rm -rf -- "$ARCHIVE_ROOT"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

git -C "$REPO_ROOT" archive "$TREE_OID" | tar -x -C "$ARCHIVE_ROOT"

find_python() {
  local candidate
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
      command -v "$PYTHON_BIN"
      return 0
    fi
    echo "Interpréteur Python introuvable: ${PYTHON_BIN}" >&2
    return 1
  fi

  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  echo "Interpréteur Python introuvable (essayé: python3, python)." >&2
  return 1
}

PYTHON_CMD="$(find_python)"
"$PYTHON_CMD" - \
  "$ARCHIVE_ROOT/services/cockpit/src/data/sources.json" \
  "$ARCHIVE_ROOT/services/rag-pedago/configs/eduscol_sources.yml" <<'PY'
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print(
        "PyYAML est requis pour vérifier la concordance des sources cockpit.",
        file=sys.stderr,
    )
    raise SystemExit(2)

json_path = Path(sys.argv[1])
yaml_path = Path(sys.argv[2])
errors: list[str] = []


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Lecture JSON impossible ({path.name}): {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"Lecture YAML impossible ({path.name}): {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def index_sources(entries: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(entries, list):
        errors.append(f"{label}: une liste de sources est requise")
        return {}

    indexed: dict[str, dict[str, Any]] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"{label}[{position}]: une entrée objet est requise")
            continue
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{label}[{position}]: id non vide requis")
            continue
        if source_id in indexed:
            errors.append(f"{label}: id dupliqué: {source_id}")
            continue
        indexed[source_id] = entry
    return indexed


json_document = load_json(json_path)
yaml_document = load_yaml(yaml_path)
yaml_entries = yaml_document.get("sources") if isinstance(yaml_document, dict) else None
json_sources = index_sources(json_document, "JSON")
yaml_sources = index_sources(yaml_entries, "YAML")

json_ids = set(json_sources)
yaml_ids = set(yaml_sources)
for source_id in sorted(yaml_ids - json_ids):
    errors.append(f"JSON: entrée manquante: {source_id}")
for source_id in sorted(json_ids - yaml_ids):
    errors.append(f"JSON: entrée surnuméraire: {source_id}")

field_mapping = (
    ("id", "id"),
    ("url", "url"),
    ("status", "status"),
    ("matiere", "matiere"),
    ("niveaux", "niveaux"),
    ("collections", "collections_cibles"),
)
for source_id in sorted(json_ids & yaml_ids):
    json_source = json_sources[source_id]
    yaml_source = yaml_sources[source_id]
    for json_field, yaml_field in field_mapping:
        if json_field not in json_source:
            errors.append(f"{source_id}: champ JSON manquant: {json_field}")
            continue
        if yaml_field not in yaml_source:
            errors.append(f"{source_id}: champ YAML manquant: {yaml_field}")
            continue
        json_value = json_source[json_field]
        yaml_value = yaml_source[yaml_field]
        if json_value != yaml_value:
            errors.append(
                f"{source_id}.{json_field}: "
                f"JSON={json.dumps(json_value, ensure_ascii=False, sort_keys=True)} "
                f"YAML={json.dumps(yaml_value, ensure_ascii=False, sort_keys=True)}"
            )

if errors:
    print(
        f"Concordance sources cockpit/Eduscol: ÉCHEC ({len(errors)} divergence(s))",
        file=sys.stderr,
    )
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print(f"Concordance sources cockpit/Eduscol: PASS ({len(json_sources)} sources)")
PY

cd "$ARCHIVE_ROOT/services/cockpit"
npm ci
npm run build
