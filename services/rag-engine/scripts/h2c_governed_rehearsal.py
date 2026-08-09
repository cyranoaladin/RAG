#!/usr/bin/env python3
"""Exécute et scelle la répétition H2-C réelle hors production."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

REAL_SHA = "371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d"
CORPUS_MANIFEST_SHA = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)
PII_EVIDENCE_SHA = (
    "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311"
)
RESULT_PREFIX = "H2E_V2_GOVERNED_REHEARSAL_RESULT="
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_MANIFEST_ENTRIES = 2583
EXPECTED_PHYSICAL_OBJECTS = 2584
EXPECTED_EDUSCOL_ARTIFACTS = 2451
EXPECTED_EDUSCOL_PLACEMENTS = 2956
BOUND_REPOSITORY_PATHS = (
    "services/rag-engine/infra/scripts/test_hybrid_integration.sh",
    "services/rag-engine/scripts/h2c_governed_rehearsal.py",
    "services/rag-engine/tests/integration/test_h2c_governed_rehearsal.py",
)


class MaterializedInputs(NamedTuple):
    """Entrées locales liées au manifeste produit par le matérialiseur H2-E."""

    pdf_path: Path
    catalog_path: Path
    pii_evidence_path: Path
    placements: tuple[dict[str, Any], ...]
    inputs_manifest_sha256: str
    placement_catalog_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_output(repository_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("H2E_REPOSITORY_BINDING_FAILED")
    return completed.stdout.strip()


def _git_bytes(repository_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("H2E_REPOSITORY_BINDING_FAILED")
    return completed.stdout


def _verify_tracked_worktree(repository_root: Path) -> tuple[int, str]:
    """Compare chaque octet suivi au blob HEAD, sans faire confiance à l'index.

    ``git status`` et ``git diff`` respectent ``assume-unchanged``. La preuve
    recalcule donc directement l'identité Git de chaque fichier du tree HEAD,
    y compris le contenu des liens symboliques et le bit exécutable.
    """
    object_format = _git_output(
        repository_root, "rev-parse", "--show-object-format"
    )
    if object_format not in {"sha1", "sha256"}:
        raise RuntimeError("H2E_REPOSITORY_OBJECT_FORMAT_INVALID")
    raw_tree = _git_bytes(
        repository_root, "ls-tree", "-rz", "--full-tree", "HEAD"
    )
    aggregate = hashlib.sha256()
    verified = 0
    for entry in raw_tree.split(b"\0"):
        if not entry:
            continue
        metadata, separator, relative_bytes = entry.partition(b"\t")
        fields = metadata.split()
        if separator != b"\t" or len(fields) != 3 or fields[1] != b"blob":
            raise RuntimeError("H2E_REPOSITORY_TRACKED_OBJECT_INVALID")
        mode, _, expected_object = fields
        relative = relative_bytes.decode("utf-8", errors="surrogateescape")
        path = repository_root / relative
        try:
            file_stat = path.lstat()
        except FileNotFoundError as exc:
            raise RuntimeError("H2E_TRACKED_WORKTREE_DRIFT") from exc
        if mode == b"120000":
            if not stat.S_ISLNK(file_stat.st_mode):
                raise RuntimeError("H2E_TRACKED_WORKTREE_DRIFT")
            content = os.readlink(path).encode("utf-8", errors="surrogateescape")
        elif mode in {b"100644", b"100755"}:
            if not stat.S_ISREG(file_stat.st_mode) or path.is_symlink():
                raise RuntimeError("H2E_TRACKED_WORKTREE_DRIFT")
            executable = bool(file_stat.st_mode & stat.S_IXUSR)
            expected_executable = mode == b"100755"
            if executable != expected_executable:
                raise RuntimeError("H2E_TRACKED_WORKTREE_DRIFT")
            content = path.read_bytes()
        else:
            raise RuntimeError("H2E_REPOSITORY_TRACKED_OBJECT_INVALID")
        object_header = b"blob " + str(len(content)).encode("ascii") + b"\0"
        actual_object = hashlib.new(object_format, object_header + content).hexdigest()
        if actual_object.encode("ascii") != expected_object:
            raise RuntimeError("H2E_TRACKED_WORKTREE_DRIFT")
        aggregate.update(relative_bytes)
        aggregate.update(b"\0")
        aggregate.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        aggregate.update(b"\n")
        verified += 1
    if verified == 0:
        raise RuntimeError("H2E_REPOSITORY_TRACKED_OBJECT_INVALID")
    return verified, aggregate.hexdigest()


def _repository_binding(
    repository_root: Path,
    *,
    bound_paths: tuple[str, ...] = BOUND_REPOSITORY_PATHS,
) -> dict[str, Any]:
    """Lie la preuve à un HEAD propre et aux exécutables H2-E exacts."""
    if _git_output(repository_root, "status", "--porcelain"):
        raise RuntimeError("H2E_REPOSITORY_NOT_CLEAN")
    head_sha = _git_output(repository_root, "rev-parse", "HEAD")
    tree_sha = _git_output(repository_root, "rev-parse", "HEAD^{tree}")
    if re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
        raise RuntimeError("H2E_REPOSITORY_HEAD_INVALID")
    if re.fullmatch(r"[0-9a-f]{40}", tree_sha) is None:
        raise RuntimeError("H2E_REPOSITORY_TREE_INVALID")
    verified_tracked_files, tracked_worktree_sha256 = _verify_tracked_worktree(
        repository_root
    )

    canonical_paths = tuple(sorted(bound_paths))
    if not canonical_paths or len(canonical_paths) != len(set(canonical_paths)):
        raise RuntimeError("H2E_BOUND_REPOSITORY_PATHS_INVALID")
    digests: dict[str, str] = {}
    for relative in canonical_paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RuntimeError("H2E_BOUND_REPOSITORY_PATH_INVALID")
        _git_output(repository_root, "ls-files", "--error-unmatch", "--", relative)
        path = repository_root / candidate
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("H2E_BOUND_REPOSITORY_FILE_INVALID")
        digests[relative] = _sha256(path)
    return {
        "git_head_sha": head_sha,
        "git_tree_sha": tree_sha,
        "verified_tracked_files": verified_tracked_files,
        "tracked_worktree_sha256": tracked_worktree_sha256,
        "bound_files_sha256": digests,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Valide les octets et preuves scellés, lance deux PostgreSQL "
            "jetables, puis scelle les métriques de la répétition LOT41A/LOT42."
        )
    )
    parser.add_argument("--inputs-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _load_mapping(path: Path, *, diagnostic: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(diagnostic) from error
    if not isinstance(document, dict):
        raise RuntimeError(diagnostic)
    return document


def _catalog_placements(document: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = document.get("artifacts")
    if isinstance(artifacts, dict):
        entry = artifacts.get(REAL_SHA)
    elif isinstance(artifacts, list):
        entry = next((item for item in artifacts if item.get("sha256") == REAL_SHA), None)
    else:
        raise RuntimeError("REAL_CATALOG_ARTIFACTS_MISSING")
    if not isinstance(entry, dict):
        raise RuntimeError("REAL_MULTI_PLACEMENT_ARTIFACT_MISSING")
    placements = entry.get("pedagogical_placements")
    if not isinstance(placements, list) or len(placements) != 7:
        raise RuntimeError("REAL_MULTI_PLACEMENT_CARDINALITY_INVALID")
    if any(
        not isinstance(item, dict)
        or item.get("content_sha256") != REAL_SHA
        or item.get("classified") is not True
        or item.get("status") != "actuel"
        for item in placements
    ):
        raise RuntimeError("REAL_MULTI_PLACEMENT_SEMANTICS_INVALID")
    return placements


def _materialized_path(
    document: dict[str, Any], *, path_field: str, digest_field: str, diagnostic: str
) -> Path:
    raw_path = document.get(path_field)
    expected_digest = document.get(digest_field)
    if not isinstance(raw_path, str) or not isinstance(expected_digest, str):
        raise RuntimeError(diagnostic)
    path = Path(raw_path).resolve()
    if not path.is_file() or _sha256(path) != expected_digest:
        raise RuntimeError(diagnostic)
    return path


def _load_materialized_inputs(path: Path) -> MaterializedInputs:
    """Vérifie le manifeste matérialisé et la nature réelle du catalogue."""
    document = _load_mapping(path, diagnostic="INPUTS_MANIFEST_INVALID")
    if document.get("inputs_manifest_kind") != "H2E_MATERIALIZED_REHEARSAL_INPUTS":
        raise RuntimeError("INPUTS_MANIFEST_KIND_INVALID")
    if document.get("remote_write_operations") != 0:
        raise RuntimeError("REMOTE_WRITE_OPERATIONS_INVALID")
    if document.get("manifest_sha256") != CORPUS_MANIFEST_SHA:
        raise RuntimeError("INPUTS_MANIFEST_DIGEST_MISMATCH")

    pdf_path = _materialized_path(
        document,
        path_field="pdf_path",
        digest_field="pdf_sha256",
        diagnostic="MATERIALIZED_PDF_SHA256_MISMATCH",
    )
    if document.get("pdf_sha256") != REAL_SHA:
        raise RuntimeError("MATERIALIZED_PDF_SHA256_MISMATCH")
    catalog_path = _materialized_path(
        document,
        path_field="catalog_path",
        digest_field="catalog_sha256",
        diagnostic="MATERIALIZED_CATALOG_SHA256_MISMATCH",
    )
    pii_path = _materialized_path(
        document,
        path_field="pii_evidence_path",
        digest_field="pii_evidence_sha256",
        diagnostic="MATERIALIZED_PII_SHA256_MISMATCH",
    )
    if document.get("pii_evidence_sha256") != PII_EVIDENCE_SHA:
        raise RuntimeError("MATERIALIZED_PII_SHA256_MISMATCH")

    catalog = _load_mapping(catalog_path, diagnostic="REAL_CATALOG_INVALID")
    if catalog.get("catalog_kind") != "REAL_SEALED_CORPUS":
        raise RuntimeError("REAL_CATALOG_KIND_INVALID")
    if catalog.get("manifest_sha256") != CORPUS_MANIFEST_SHA:
        raise RuntimeError("REAL_CATALOG_MANIFEST_MISMATCH")
    if (
        catalog.get("verification_passed") is not True
        or catalog.get("verification_errors") != []
    ):
        raise RuntimeError("REAL_CATALOG_VERIFICATION_FAILED")
    expected_counts = {
        "manifest_entries": EXPECTED_MANIFEST_ENTRIES,
        "physical_object_count": EXPECTED_PHYSICAL_OBJECTS,
        "eduscol_unique_artifacts": EXPECTED_EDUSCOL_ARTIFACTS,
        "eduscol_placement_count": EXPECTED_EDUSCOL_PLACEMENTS,
        "unclassified": 0,
        "multiple_primary_disposition": 0,
    }
    if any(catalog.get(key) != value for key, value in expected_counts.items()):
        raise RuntimeError("REAL_CATALOG_COUNTS_INVALID")
    placement_catalog_sha256 = document.get("placement_catalog_sha256")
    if (
        not isinstance(placement_catalog_sha256, str)
        or _SHA256.fullmatch(placement_catalog_sha256) is None
        or catalog.get("placement_catalog_sha256") != placement_catalog_sha256
    ):
        raise RuntimeError("PLACEMENT_CATALOG_DIGEST_MISMATCH")
    placements = _catalog_placements(catalog)
    return MaterializedInputs(
        pdf_path=pdf_path,
        catalog_path=catalog_path,
        pii_evidence_path=pii_path,
        placements=tuple(placements),
        inputs_manifest_sha256=_sha256(path),
        placement_catalog_sha256=placement_catalog_sha256,
    )


def _pii_binding(path: Path) -> dict[str, Any]:
    if _sha256(path) != PII_EVIDENCE_SHA:
        raise RuntimeError("PII_EVIDENCE_SHA256_MISMATCH")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("corpus_manifest_sha256") != CORPUS_MANIFEST_SHA:
        raise RuntimeError("PII_EVIDENCE_MANIFEST_MISMATCH")
    results = document.get("results")
    if not isinstance(results, list):
        raise RuntimeError("PII_EVIDENCE_RESULTS_MISSING")
    result = next(
        (item for item in results if item.get("content_sha256") == REAL_SHA),
        None,
    )
    if not isinstance(result, dict) or result.get("status") != "CLEARED":
        raise RuntimeError("REAL_MULTI_PLACEMENT_PII_NOT_CLEARED")
    if result.get("pii_detected") is not False:
        raise RuntimeError("REAL_MULTI_PLACEMENT_PII_RESULT_INVALID")
    return {
        "content_sha256": REAL_SHA,
        "evidence_sha256": PII_EVIDENCE_SHA,
        "pages_scanned": result.get("pages_scanned"),
        "status": "CLEARED",
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _is_exact_int(value: object, *, expected: int) -> bool:
    """Refuse notamment ``bool``, sous-classe de ``int`` en Python."""
    return type(value) is int and value == expected


def _validate_rehearsal_result(result: dict[str, Any]) -> None:
    negative = result.get("negative_same_domain_unlisted")
    valid = (
        result.get("real_multi_placement_sha") == REAL_SHA
        and _is_exact_int(result.get("real_multi_placement_placements"), expected=7)
        and _is_exact_int(result.get("artifact_rows_for_sha"), expected=1)
        and _is_exact_int(result.get("placement_rows"), expected=7)
        and _is_exact_int(result.get("chunk_set_count"), expected=1)
        and _is_exact_int(result.get("duplicate_vector_sets"), expected=0)
        and _is_exact_int(result.get("duplicate_chunk_sets"), expected=0)
        and _is_exact_int(result.get("duplicate_result_chunks"), expected=0)
        and result.get("full_governed_rehearsal_pass") is True
        and result.get("lot41a_v2_content_bound") is True
        and result.get("lot42_pipeline_path_implemented") is True
        and result.get("scope_a_retrieval_pass") is True
        and result.get("scope_b_retrieval_pass") is True
        and result.get("wrong_scope_retrieval_blocked") is True
        and result.get("citation_traceability_pass") is True
        and result.get("placement_traceability_pass") is True
        and result.get("positive_content_allowlist_gate") == "PASS"
        and _is_exact_int(result.get("positive_blob_readbacks"), expected=1)
        and _is_exact_int(result.get("positive_control_artifact_rows"), expected=7)
        and _is_exact_int(result.get("positive_extractor_calls"), expected=1)
        and _is_exact_int(result.get("positive_fetched_events"), expected=7)
        and _is_exact_int(result.get("positive_network_fetches"), expected=7)
        and _is_exact_int(result.get("positive_physical_blob_writes"), expected=1)
        and _is_exact_int(result.get("positive_quality_agent_calls"), expected=7)
        and _is_exact_int(result.get("positive_rights_agent_calls"), expected=7)
        and _is_exact_int(result.get("positive_store_callbacks"), expected=7)
        and _is_exact_int(result.get("positive_stored_events"), expected=7)
        and _is_exact_int(result.get("positive_unique_content_sha"), expected=1)
        and isinstance(negative, dict)
        and negative.get("domain_gate") == "PASS"
        and negative.get("content_allowlist_gate") == "DENY"
        and negative.get("store_called") is False
        and negative.get("extractor_called") is False
        and negative.get("rights_agent_called") is False
        and negative.get("quality_agent_called") is False
        and negative.get("resource_state") == "CANDIDATE"
        and negative.get("retrieval_eligible") is False
        and _is_exact_int(negative.get("control_artifact_rows"), expected=0)
        and _is_exact_int(negative.get("pgvector_rows_created"), expected=0)
    )
    if not valid:
        raise RuntimeError("H2E_V2_REHEARSAL_NOT_GREEN")


def main() -> int:
    args = _arguments()
    service_root = Path(__file__).resolve().parents[1]
    repository_root = service_root.parents[1]
    repository_before = _repository_binding(repository_root)
    inputs = _load_materialized_inputs(args.inputs_manifest)
    pii = _pii_binding(inputs.pii_evidence_path)

    runner = service_root / "infra" / "scripts" / "test_hybrid_integration.sh"
    environment = os.environ.copy()
    environment.update(
        {
            "NEXUS_H2C_REAL_REHEARSAL": "1",
            "NEXUS_H2C_REHEARSAL_ONLY": "1",
            "NEXUS_H2C_REAL_PDF_PATH": str(inputs.pdf_path),
            "NEXUS_H2C_REAL_CATALOG_PATH": str(inputs.catalog_path),
        }
    )
    completed = subprocess.run(
        ["bash", str(runner)],
        cwd=service_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        return completed.returncode
    result_lines = [
        line.split(RESULT_PREFIX, 1)[1]
        for line in completed.stdout.splitlines()
        if RESULT_PREFIX in line
    ]
    if len(result_lines) != 1:
        raise RuntimeError("H2C_REHEARSAL_RESULT_MISSING_OR_DUPLICATED")
    result = json.loads(result_lines[0])
    if not isinstance(result, dict):
        raise RuntimeError("H2E_V2_REHEARSAL_RESULT_INVALID")
    _validate_rehearsal_result(result)
    repository_after = _repository_binding(repository_root)
    if repository_after != repository_before:
        raise RuntimeError("H2E_REPOSITORY_CHANGED_DURING_REHEARSAL")

    evidence = {
        "corpus_manifest_sha256": CORPUS_MANIFEST_SHA,
        "evidence_kind": "H2E_V2_REAL_GOVERNED_REHEARSAL",
        "generated_at": datetime.now(UTC).isoformat(),
        "github_boundary": "LOCAL_HTTP_REHEARSAL_WITH_CANONICAL_LIVE_VERIFIERS",
        "materializer_inputs_manifest_sha256": inputs.inputs_manifest_sha256,
        "pii_binding": pii,
        "placement_catalog_sha256": inputs.placement_catalog_sha256,
        "product_database": "DISPOSABLE_POSTGRESQL_PGVECTOR",
        "production_database_touched": False,
        "production_publication_attestation": False,
        "rehearsal_authority": "STAGING_TEST_LOT41A_V2",
        "real_catalog_sha256": _sha256(inputs.catalog_path),
        "real_pdf_sha256": REAL_SHA,
        "real_placement_count": len(inputs.placements),
        "repository_binding": repository_before,
        "rehearsal": result,
        "runner_output_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
    }
    _write_json(args.output, evidence)
    print(f"H2E_V2_GOVERNED_REHEARSAL_EVIDENCE_SHA256={_sha256(args.output)}")
    print("PRODUCTION_DATABASE_TOUCHED=false")
    print("REAL_PRODUCTION_PUBLICATION_ATTESTATIONS=DEFERRED_TO_P4_BY_DESIGN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
