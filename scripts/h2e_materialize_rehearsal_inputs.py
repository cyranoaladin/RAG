#!/usr/bin/env python3
"""Matérialise trois entrées H2-E scellées par un transport Drive en lecture."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml

from rag_pedago.imports.corpus_catalog_compiler import (
    compile_governed_sealed_catalog,
    load_routing_config,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = REPOSITORY_ROOT / "services/rag-pedago"
CANONICAL_REMOTE_ROOT = "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY"
MANIFEST_REMOTE_PATH = "00_ADMIN/SHA256SUMS.txt"
PLACEMENT_CATALOG_REMOTE_PATH = (
    "00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES/catalogue-complet.tsv"
)
REAL_SHA256 = "371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d"
REAL_PDF_SUFFIX = "371d0c82ed.pdf"
EXPECTED_REAL_PLACEMENTS = 7
EXPECTED_MANIFEST_SHA256 = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)
EXPECTED_PII_EVIDENCE_SHA256 = (
    "c559891f8f636a5b25fc97e25ab959c143b1e352e36d150139c8737ee33060d6"
)
RCLONE_PROCESS_TIMEOUT_SECONDS = 1800
ROUTING_CONFIG_PATH = SERVICE_ROOT / "configs" / "corpus_zone_routing.yml"
RIGHTS_REGISTRY_PATH = SERVICE_ROOT / "configs" / "rights_evidence_registry.yml"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TMP_ROOT = Path("/tmp").resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_mapping(path: Path, *, kind: str) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError(f"{kind}_DOCUMENT_INVALID")
    return document


def _validate_scratch(scratch_dir: Path, output_manifest_path: Path) -> Path:
    if scratch_dir.is_symlink():
        raise ValueError("scratch must be an existing bounded /tmp/nexus-h2e.* directory")
    scratch = scratch_dir.resolve()
    if scratch.parent != _TMP_ROOT or not scratch.name.startswith("nexus-h2e."):
        raise ValueError("scratch must be an existing bounded /tmp/nexus-h2e.* directory")
    try:
        metadata = scratch.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ValueError(
            "scratch must be an existing bounded /tmp/nexus-h2e.* directory"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("scratch must be an existing bounded /tmp/nexus-h2e.* directory")
    if metadata.st_uid != os.geteuid():
        raise ValueError("scratch must be owned by the current effective user")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError("scratch must have exact mode 0700")
    if output_manifest_path.parent.resolve() != scratch:
        raise ValueError("output manifest must be a direct child of bounded scratch")
    return scratch


def _require_available_direct_child(scratch: Path, target: Path) -> None:
    if target.parent.resolve() != scratch:
        raise RuntimeError("LOCAL_MATERIALIZATION_TARGET_OUTSIDE_SCRATCH")
    if os.path.lexists(target):
        raise RuntimeError("LOCAL_MATERIALIZATION_TARGET_EXISTS")


def _copyto(scratch: Path, relative_remote_path: str, local_path: Path) -> None:
    if relative_remote_path.startswith(("/", "..")) or "\\" in relative_remote_path:
        raise RuntimeError("REMOTE_OBJECT_PATH_INVALID")
    _require_available_direct_child(scratch, local_path)
    completed = subprocess.run(
        [
            "rclone",
            "copyto",
            f"{CANONICAL_REMOTE_ROOT}/{relative_remote_path}",
            str(local_path),
            "--immutable",
            "--retries",
            "10",
            "--low-level-retries",
            "20",
            "--contimeout",
            "60s",
            "--timeout",
            "10m",
        ],
        capture_output=True,
        text=True,
        timeout=RCLONE_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        # Les sorties du transport peuvent contenir du contenu distant ; ne pas
        # les recopier dans le journal ou dans la preuve aseptisée.
        raise RuntimeError(f"READ_ONLY_RCLONE_COPYTO_FAILED:{relative_remote_path}")


def _write_json(scratch: Path, path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    _require_available_direct_child(scratch, path)
    _require_available_direct_child(scratch, temporary)
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _verify_pii_evidence(path: Path, *, manifest_sha256: str) -> dict[str, Any]:
    if _sha256(path) != EXPECTED_PII_EVIDENCE_SHA256:
        raise RuntimeError("PII_SHA256_MISMATCH")
    document = _load_mapping(path, kind="PII_EVIDENCE")
    if document.get("evidence_kind") != "REAL_CORPUS_PII_SCAN":
        raise RuntimeError("PII_EVIDENCE_KIND_INVALID")
    if document.get("corpus_manifest_sha256") != manifest_sha256:
        raise RuntimeError("PII_EVIDENCE_MANIFEST_MISMATCH")
    if (
        document.get("remote_access_mode") != "READ_ONLY"
        or document.get("remote_write_operations") != 0
        or document.get("raw_pii_in_output") is not False
        or document.get("raw_pii_in_logs") is not False
    ):
        raise RuntimeError("PII_EVIDENCE_SAFETY_INVALID")
    results = document.get("results")
    if not isinstance(results, list):
        raise RuntimeError("PII_EVIDENCE_RESULTS_INVALID")
    matching = [
        result
        for result in results
        if isinstance(result, dict) and result.get("content_sha256") == REAL_SHA256
    ]
    if (
        len(matching) != 1
        or matching[0].get("status") != "CLEARED"
        or matching[0].get("pii_detected") is not False
    ):
        raise RuntimeError("REAL_MULTI_PLACEMENT_PII_NOT_CLEARED")
    return document


def _selected_remote_path(catalog: Any) -> str:
    artifact = catalog.artifacts.get(REAL_SHA256)
    if artifact is None:
        raise RuntimeError("REAL_MULTI_PLACEMENT_ARTIFACT_MISSING")
    paths = [
        item.path
        for item in artifact.physical_objects
        if item.path.startswith("01_EDUSCOL_OFFICIEL/")
    ]
    if len(paths) != 1 or not paths[0].endswith(REAL_PDF_SUFFIX):
        raise RuntimeError("REAL_MULTI_PLACEMENT_REMOTE_PATH_INVALID")
    if len(artifact.pedagogical_placements) != EXPECTED_REAL_PLACEMENTS:
        raise RuntimeError("REAL_MULTI_PLACEMENT_CARDINALITY_INVALID")
    return paths[0]


def materialize_rehearsal_inputs(
    *,
    scratch_dir: Path,
    pii_evidence_path: Path,
    output_manifest_path: Path,
    routing_config_path: Path = ROUTING_CONFIG_PATH,
    rights_registry_path: Path = RIGHTS_REGISTRY_PATH,
) -> dict[str, Any]:
    """Télécharge trois objets, vérifie leurs sceaux et compile le catalogue."""
    scratch = _validate_scratch(scratch_dir, output_manifest_path)
    if not pii_evidence_path.is_file():
        raise RuntimeError("PII_EVIDENCE_MISSING")
    if _SHA256.fullmatch(REAL_SHA256) is None:
        raise RuntimeError("REAL_SHA256_INVALID")
    pii_evidence = _verify_pii_evidence(
        pii_evidence_path, manifest_sha256=EXPECTED_MANIFEST_SHA256
    )

    manifest_path = scratch / "SHA256SUMS.txt"
    placement_catalog_path = scratch / "catalogue-complet.tsv"
    pdf_path = scratch / REAL_PDF_SUFFIX
    compiled_catalog_path = scratch / "h2e_governed_catalog.json"
    targets = (
        manifest_path,
        placement_catalog_path,
        pdf_path,
        compiled_catalog_path,
        compiled_catalog_path.with_suffix(compiled_catalog_path.suffix + ".tmp"),
        output_manifest_path,
        output_manifest_path.with_suffix(output_manifest_path.suffix + ".tmp"),
    )
    if len(set(targets)) != len(targets):
        raise RuntimeError("LOCAL_MATERIALIZATION_TARGETS_OVERLAP")
    for target in targets:
        _require_available_direct_child(scratch, target)

    _copyto(scratch, MANIFEST_REMOTE_PATH, manifest_path)
    manifest_sha256 = _sha256(manifest_path)
    if manifest_sha256 != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError("MANIFEST_SHA256_MISMATCH")

    routing_config = load_routing_config(routing_config_path)
    if routing_config.get("manifest_sha256") != manifest_sha256:
        raise RuntimeError("ROUTING_MANIFEST_SHA256_MISMATCH")
    rights_registry = _load_mapping(rights_registry_path, kind="RIGHTS_REGISTRY")

    _copyto(scratch, PLACEMENT_CATALOG_REMOTE_PATH, placement_catalog_path)
    catalog = compile_governed_sealed_catalog(
        manifest_path,
        placement_catalog_path,
        routing_config,
        rights_registry,
        pii_evidence,
    )
    if not catalog.verification_passed:
        raise RuntimeError("GOVERNED_CATALOG_VERIFICATION_FAILED")
    remote_pdf_path = _selected_remote_path(catalog)

    _copyto(scratch, remote_pdf_path, pdf_path)
    if _sha256(pdf_path) != REAL_SHA256:
        raise RuntimeError("PDF_SHA256_MISMATCH")

    _write_json(scratch, compiled_catalog_path, catalog.to_dict(include_objects=True))
    output = {
        "inputs_manifest_kind": "H2E_MATERIALIZED_REHEARSAL_INPUTS",
        "catalog_path": str(compiled_catalog_path),
        "catalog_sha256": _sha256(compiled_catalog_path),
        "manifest_sha256": manifest_sha256,
        "pdf_path": str(pdf_path),
        "pdf_sha256": REAL_SHA256,
        "pii_evidence_path": str(pii_evidence_path.resolve()),
        "pii_evidence_sha256": EXPECTED_PII_EVIDENCE_SHA256,
        "placement_catalog_sha256": catalog.placement_catalog_sha256,
        "remote_write_operations": 0,
    }
    _write_json(scratch, output_manifest_path, output)
    return output


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-dir", required=True, type=Path)
    parser.add_argument("--pii-evidence", required=True, type=Path)
    parser.add_argument("--output-manifest", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    output = materialize_rehearsal_inputs(
        scratch_dir=args.scratch_dir,
        pii_evidence_path=args.pii_evidence,
        output_manifest_path=args.output_manifest,
    )
    print(f"REAL_MULTI_PLACEMENT_SHA={output['pdf_sha256']}")
    print("REMOTE_WRITE_OPERATIONS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
