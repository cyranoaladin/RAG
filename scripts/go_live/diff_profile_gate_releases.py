#!/usr/bin/env python3
"""Diff machine entre deux releases profile-gate (par exemple V2 → V3).

Compare deux répertoires `profile_gate/` déjà construits, sans rien juger :
champs du manifeste, autorités, octets de chaque fichier, artefacts (et
identité de leurs chunks, que l'adoption d'ADR-0059 § 5 exige égale),
placements, statuts PII et décisions d'actualité par contenu. La sortie est un
JSON canonique ; la lecture de ce qui est acceptable reste au relecteur.

    python3 scripts/go_live/diff_profile_gate_releases.py \\
        --base <release-v2>/profile_gate --head <release-v3>/profile_gate \\
        --output <diff>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

KIND = "NEXUS-PROFILE-GATE-RELEASE-DIFF-V1"
MANIFEST = "production-profile-gate.release.json"
_CHUNK_FIELDS = ("chunk_id_set_digest", "chunk_sha256_set_digest", "chunks")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _by_content(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["content_sha256"]): row for row in rows}


def _placements(root: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for subject in sorted((root / "subjects").glob("*.release.json")):
        for placement in _json(subject).get("placements", []):
            found.add((str(placement["collection"]), str(placement["artifact_id"])))
    return found


def _status_diff(base: dict[str, str], head: dict[str, str]) -> dict[str, Any]:
    common = sorted(set(base) & set(head))
    return {
        "transitions": dict(sorted(Counter(f"{base[k]}->{head[k]}" for k in common).items())),
        "added": {k: head[k] for k in sorted(set(head) - set(base))},
        "removed": {k: base[k] for k in sorted(set(base) - set(head))},
        "base_counts": dict(sorted(Counter(base.values()).items())),
        "head_counts": dict(sorted(Counter(head.values()).items())),
    }


def _describe(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        raise SystemExit(f"NOT_A_PROFILE_GATE_RELEASE: {root} has no {MANIFEST}")
    return {
        "manifest": _json(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "files": _files(root),
        "artifacts": _by_content(_json(root / "artifacts.release.json")["artifacts"]),
        "placements": _placements(root),
        "pii": {k: str(v["status"]) for k, v in _by_content(_json(root / "pii_evidence.json")["results"]).items()},
        "currentness": {
            k: str(v["decision"])
            for k, v in _by_content(_json(root / "currentness_evidence.json")["artifacts"]).items()
        },
    }


def diff_releases(base_root: Path, head_root: Path) -> dict[str, Any]:
    base, head = _describe(base_root), _describe(head_root)
    bm, hm = base["manifest"], head["manifest"]

    scalar_fields = sorted(
        k for k in set(bm) | set(hm)
        if not isinstance(bm.get(k), (dict, list)) and not isinstance(hm.get(k), (dict, list))
    )
    manifest_fields = {
        k: {"base": bm.get(k), "head": hm.get(k)} for k in scalar_fields if bm.get(k) != hm.get(k)
    }

    ba, ha = bm.get("authorities", {}), hm.get("authorities", {})
    authorities = {
        "added": {k: ha[k] for k in sorted(set(ha) - set(ba))},
        "removed": {k: ba[k] for k in sorted(set(ba) - set(ha))},
        "changed": {
            k: {"base": ba[k], "head": ha[k]} for k in sorted(set(ba) & set(ha)) if ba[k] != ha[k]
        },
    }

    bf, hf = base["files"], head["files"]
    files = {
        "added": sorted(set(hf) - set(bf)),
        "removed": sorted(set(bf) - set(hf)),
        "changed": sorted(k for k in set(bf) & set(hf) if bf[k] != hf[k]),
        "unchanged_count": sum(1 for k in set(bf) & set(hf) if bf[k] == hf[k]),
    }

    bart, hart = base["artifacts"], head["artifacts"]
    common = sorted(set(bart) & set(hart))
    changed_fields = {
        sha: sorted(k for k in set(bart[sha]) | set(hart[sha]) if bart[sha].get(k) != hart[sha].get(k))
        for sha in common
    }
    changed_fields = {sha: fields for sha, fields in changed_fields.items() if fields}
    artifacts = {
        "base_count": len(bart),
        "head_count": len(hart),
        "added": sorted(set(hart) - set(bart)),
        "removed": sorted(set(bart) - set(hart)),
        "changed_fields": changed_fields,
        "chunk_identity_changed": sorted(
            sha for sha, fields in changed_fields.items() if set(fields) & set(_CHUNK_FIELDS)
        ),
        "base_chunk_count": sum(len(a.get("chunks", [])) for a in bart.values()),
        "head_chunk_count": sum(len(a.get("chunks", [])) for a in hart.values()),
    }

    bp, hp = base["placements"], head["placements"]
    placements = {
        "base_count": len(bp),
        "head_count": len(hp),
        "added": [list(p) for p in sorted(hp - bp)],
        "removed": [list(p) for p in sorted(bp - hp)],
    }

    return {
        "kind": KIND,
        "base": {"release_id": bm.get("release_id"), "manifest_sha256": base["manifest_sha256"]},
        "head": {"release_id": hm.get("release_id"), "manifest_sha256": head["manifest_sha256"]},
        "manifest_fields": manifest_fields,
        "authorities": authorities,
        "files": files,
        "artifacts": artifacts,
        "placements": placements,
        "pii": _status_diff(base["pii"], head["pii"]),
        "currentness": _status_diff(base["currentness"], head["currentness"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", type=Path, required=True, help="répertoire profile_gate de référence")
    parser.add_argument("--head", type=Path, required=True, help="répertoire profile_gate comparé")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    diff = diff_releases(args.base, args.head)
    args.output.write_text(
        json.dumps(diff, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "sha256": _sha256(args.output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
