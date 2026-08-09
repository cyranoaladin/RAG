#!/usr/bin/env python3
"""Matérialise en lecture seule les PDF PII avant le scan local rag-pedago."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath

CANONICAL_REMOTE_ROOT = "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY"
_MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")


class PIIMirrorMaterializationError(RuntimeError):
    """Erreur de transport expurgée, sans chemin distant ni contenu brut."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_pdf_paths(manifest_path: Path) -> set[str]:
    paths: set[str] = set()
    for line_number, raw in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = _MANIFEST_LINE.fullmatch(raw)
        if match is None:
            raise ValueError(f"invalid sealed manifest row {line_number}")
        object_path = match.group(2)
        parsed = PurePosixPath(object_path)
        if parsed.is_absolute() or ".." in parsed.parts or not object_path:
            raise ValueError(f"unsafe sealed manifest path at row {line_number}")
        if object_path.lower().endswith(".pdf"):
            paths.add(object_path)
    if not paths:
        raise ValueError("sealed manifest PDF perimeter must not be empty")
    return paths


def _validated_mirror(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    tmp_root = Path("/tmp").resolve()
    if (
        resolved == tmp_root
        or tmp_root not in resolved.parents
        or not resolved.name.startswith("nexus-h2b-pii.")
        or not resolved.is_dir()
    ):
        raise ValueError("local mirror must be a dedicated /tmp/nexus-h2b-pii.* directory")
    if stat.S_IMODE(resolved.stat().st_mode) != 0o700:
        raise ValueError("local mirror must use mode 0700")
    if any(resolved.iterdir()):
        raise ValueError("local mirror must be empty before materialization")
    return resolved


def materialize_pii_mirror(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    remote_root: str,
    local_mirror: Path,
    required_pdf_paths: set[str] | None = None,
) -> dict[str, object]:
    """Copie une liste positive issue du manifest vers un miroir local borné."""
    if remote_root != CANONICAL_REMOTE_ROOT:
        raise ValueError("remote root is not the canonical read-only corpus remote")
    if re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None:
        raise ValueError("expected manifest SHA256 must be canonical")
    manifest_sha256 = _sha256(manifest_path)
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError("corpus manifest SHA256 mismatch")
    mirror = _validated_mirror(local_mirror)
    available_paths = _manifest_pdf_paths(manifest_path)
    selected = available_paths if required_pdf_paths is None else set(required_pdf_paths)
    if not selected or not selected <= available_paths:
        raise ValueError("required PDF paths must be a non-empty manifest subset")
    ordered = sorted(selected)
    file_list = ("\n".join(ordered) + "\n").encode()

    try:
        subprocess.run(
            [
                "rclone",
                "copy",
                "--immutable",
                "--files-from-raw",
                "-",
                "--transfers",
                "4",
                "--checkers",
                "1",
                "--tpslimit",
                "4",
                "--tpslimit-burst",
                "4",
                "--retries",
                "10",
                "--low-level-retries",
                "20",
                remote_root,
                str(mirror),
            ],
            capture_output=True,
            check=True,
            input=file_list,
            text=False,
            timeout=7200,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PIIMirrorMaterializationError(
            "read-only corpus materialization failed"
        ) from error

    return {
        "evidence_kind": "H2B_PII_LOCAL_MIRROR_MATERIALIZATION",
        "corpus_manifest_sha256": manifest_sha256,
        "pdf_path_count": len(ordered),
        "pdf_path_set_digest": hashlib.sha256(file_list).hexdigest(),
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--remote-root", default=CANONICAL_REMOTE_ROOT)
    parser.add_argument("--local-mirror", type=Path, required=True)
    parser.add_argument(
        "--required-paths",
        type=Path,
        help="Fichier local contenant un chemin PDF autorisé par ligne.",
    )
    args = parser.parse_args()
    required = None
    if args.required_paths is not None:
        required = {
            line.strip()
            for line in args.required_paths.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    try:
        receipt = materialize_pii_mirror(
            manifest_path=args.manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
            remote_root=args.remote_root,
            local_mirror=args.local_mirror,
            required_pdf_paths=required,
        )
    except KeyboardInterrupt:
        print("PII_MIRROR_MATERIALIZATION_INTERRUPTED=true")
        return 130
    except Exception:
        print("PII_MIRROR_MATERIALIZATION_FAILED=true")
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
