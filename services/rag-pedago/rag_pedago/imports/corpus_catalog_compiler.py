"""Corpus Catalog Compiler — H2-B.

Assigns exactly ONE disposition to each corpus object based on zone routing rules.
Proves SUM(dispositions) = CORPUS_TOTAL with zero overlap and zero gap.

Usage:
    python -m rag_pedago.imports.corpus_catalog_compiler \
        --manifest data/corpus/eduscol_catalog.tsv \
        --config configs/corpus_zone_routing.yml \
        --output data/reports/corpus_disposition_catalog.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from rag_pedago.imports.artifact_placement_model import (
    ContentArtifact,
    Disposition,
    PedagogicalPlacement,
    PhysicalCorpusObject,
    SealedCorpusCatalog,
)

_GNU_SHA256_LINE = re.compile(r"([0-9a-f]{64})  (.*)\Z")
_MANIFEST_SELF_PATH = "00_ADMIN/SHA256SUMS.txt"


@dataclass(frozen=True)
class CorpusObject:
    """A single object in the corpus with its disposition."""

    sha256: str
    path: str
    size_bytes: int
    disposition: Disposition
    disposition_reason: str
    zone: str
    currentness: str | None = None
    rights_category_candidate: str | None = None


@dataclass
class DispositionTotals:
    """Aggregated disposition counts."""

    ingest: int = 0
    review_required: int = 0
    quarantine: int = 0
    archive_only: int = 0
    exclude: int = 0
    unsupported: int = 0

    def total(self) -> int:
        return (
            self.ingest
            + self.review_required
            + self.quarantine
            + self.archive_only
            + self.exclude
            + self.unsupported
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "INGEST": self.ingest,
            "REVIEW_REQUIRED": self.review_required,
            "QUARANTINE": self.quarantine,
            "ARCHIVE_ONLY": self.archive_only,
            "EXCLUDE": self.exclude,
            "UNSUPPORTED": self.unsupported,
        }


@dataclass
class CompilationReport:
    """Full compilation result with verification."""

    config_id: str
    manifest_path: str
    manifest_sha256: str
    corpus_total_objects: int
    expected_total: int
    totals: DispositionTotals
    objects: list[CorpusObject] = field(default_factory=list)
    verification_passed: bool = False
    verification_errors: list[str] = field(default_factory=list)
    compiled_at: str = ""

    def verify(self) -> None:
        """Verify SUM(dispositions) = corpus_total_objects."""
        self.verification_errors = []

        actual_total = self.totals.total()
        if actual_total != self.expected_total:
            self.verification_errors.append(
                f"SUM(dispositions)={actual_total} != expected_total={self.expected_total}"
            )

        if actual_total != len(self.objects):
            self.verification_errors.append(
                f"totals.total()={actual_total} != len(objects)={len(self.objects)}"
            )

        # Check for duplicates (overlap)
        seen_sha256 = set()
        duplicates = []
        for obj in self.objects:
            if obj.sha256 in seen_sha256:
                duplicates.append(obj.sha256)
            seen_sha256.add(obj.sha256)

        if duplicates:
            self.verification_errors.append(
                f"OVERLAP: {len(duplicates)} duplicate SHA256 values"
            )

        self.verification_passed = len(self.verification_errors) == 0


def load_routing_config(path: Path) -> dict[str, Any]:
    """Load zone routing configuration."""
    content = path.read_text(encoding="utf-8")
    config = yaml.safe_load(content)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid routing config: {path}")
    return config


def compute_file_sha256(path: Path) -> str:
    """Compute SHA256 of a file."""
    sha = hashlib.sha256()
    sha.update(path.read_bytes())
    return sha.hexdigest()


def _match_zone_prefix(path: str, zone_prefix: str) -> bool:
    """Check if path starts with zone prefix."""
    return path.startswith(zone_prefix)


def _match_sub_zone(path: str, sub_zone_suffix: str | None) -> bool:
    """Check if path contains sub-zone suffix."""
    if sub_zone_suffix is None:
        return True  # Default catch-all
    return sub_zone_suffix in path


def _determine_disposition(
    path: str,
    config: dict[str, Any],
) -> tuple[Disposition, str, str, str | None, str | None]:
    """Determine disposition for a path based on routing rules.

    Returns: (disposition, reason, zone, currentness, rights_category_candidate)
    """
    zone_rules = config.get("zone_rules", [])

    for rule in zone_rules:
        zone_prefix = rule.get("zone_prefix", "")
        if not _match_zone_prefix(path, zone_prefix):
            continue

        # Check sub-zone routing if present
        sub_zone_routing = rule.get("sub_zone_routing")
        if sub_zone_routing:
            for sub_rule in sub_zone_routing:
                sub_zone_suffix = sub_rule.get("sub_zone_suffix")
                if _match_sub_zone(path, sub_zone_suffix):
                    disposition_str = sub_rule.get("disposition")
                    if disposition_str:
                        return (
                            Disposition(disposition_str),
                            sub_rule.get("review_reason")
                            or sub_rule.get("archive_reason")
                            or sub_rule.get("quarantine_reason")
                            or f"Matched sub-zone: {sub_zone_suffix}",
                            zone_prefix,
                            sub_rule.get("currentness"),
                            sub_rule.get("rights_category_candidate"),
                        )

        # Direct disposition on zone
        disposition_str = rule.get("disposition")
        if disposition_str:
            return (
                Disposition(disposition_str),
                rule.get("reason", f"Matched zone: {zone_prefix}"),
                zone_prefix,
                None,
                rule.get("rights_category"),
            )

    # No rule matched — REVIEW_REQUIRED as fail-safe
    return (
        Disposition.REVIEW_REQUIRED,
        "No zone rule matched — requires review",
        "UNKNOWN",
        None,
        None,
    )


def _parse_manifest_line(
    line: dict[str, str],
) -> tuple[str, str, int]:
    """Parse a manifest line into (sha256, path, size_bytes)."""
    sha256 = line.get("sha256", "")
    # Try different path column names
    path = (
        line.get("chemin_technique_existant")
        or line.get("path")
        or line.get("objet_source")
        or ""
    )
    size_str = line.get("taille_octets", "0")
    try:
        size_bytes = int(size_str) if size_str else 0
    except ValueError:
        size_bytes = 0

    return sha256, path, size_bytes


def compile_catalog(
    manifest_path: Path,
    config: dict[str, Any],
) -> CompilationReport:
    """Compile corpus catalog with disposition assignments."""
    manifest_sha256 = compute_file_sha256(manifest_path)
    config_id = config.get("config_id", "unknown")
    expected_total = config.get("corpus_total_objects", 0)

    totals = DispositionTotals()
    objects: list[CorpusObject] = []

    # Parse manifest (TSV format)
    with manifest_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for line in reader:
            sha256, path, size_bytes = _parse_manifest_line(line)
            if not sha256 or not path:
                continue

            disposition, reason, zone, currentness, rights_cat = _determine_disposition(
                path, config
            )

            obj = CorpusObject(
                sha256=sha256,
                path=path,
                size_bytes=size_bytes,
                disposition=disposition,
                disposition_reason=reason,
                zone=zone,
                currentness=currentness,
                rights_category_candidate=rights_cat,
            )
            objects.append(obj)

            # Update totals
            match disposition:
                case Disposition.INGEST:
                    totals.ingest += 1
                case Disposition.REVIEW_REQUIRED:
                    totals.review_required += 1
                case Disposition.QUARANTINE:
                    totals.quarantine += 1
                case Disposition.ARCHIVE_ONLY:
                    totals.archive_only += 1
                case Disposition.EXCLUDE:
                    totals.exclude += 1
                case Disposition.UNSUPPORTED:
                    totals.unsupported += 1

    report = CompilationReport(
        config_id=config_id,
        manifest_path=str(manifest_path),
        manifest_sha256=manifest_sha256,
        corpus_total_objects=len(objects),
        expected_total=expected_total,
        totals=totals,
        objects=objects,
        compiled_at=datetime.now(UTC).isoformat(),
    )
    report.verify()

    return report


def _validate_manifest_path(path: str) -> None:
    """Reject paths that cannot name a bounded object in the sealed corpus."""
    candidate = PurePosixPath(path)
    if (
        not path
        or candidate.is_absolute()
        or "\\" in path
        or "//" in path
        or "\x00" in path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError(f"unsafe manifest path: {path!r}")


def _parse_sealed_manifest(path: Path) -> list[tuple[str, str]]:
    """Parse a GNU SHA256 manifest while allowing identical bytes at N paths."""
    entries: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            match = _GNU_SHA256_LINE.fullmatch(line)
            if match is None:
                raise ValueError(f"invalid SHA256 manifest line {line_number}")
            content_sha256, object_path = match.groups()
            _validate_manifest_path(object_path)
            if object_path in seen_paths:
                raise ValueError(f"duplicate manifest path: {object_path}")
            seen_paths.add(object_path)
            entries.append((content_sha256, object_path))
    return entries


def _pedagogical_placement_from_row(row: dict[str, str]) -> PedagogicalPlacement:
    return PedagogicalPlacement(
        content_sha256=row["sha256"],
        scope=row["scope"],
        family=row["famille"],
        subject=row["matiere_ou_rubrique"],
        level=row["niveau"],
        document_type=row["type_document"],
        year=row["annee"],
        status=row["statut"],
        title=row["titre"],
        source_url=row["url_source"],
        source_object=row["objet_source"],
        technical_path=row["chemin_technique_existant"],
        level_path=row["chemin_par_niveau"],
        scope_path=row["chemin_par_scope"],
    )


def _attach_eduscol_placements(
    catalog: SealedCorpusCatalog,
    placement_catalog_path: Path,
) -> None:
    required_columns = {
        "sha256",
        "scope",
        "famille",
        "matiere_ou_rubrique",
        "niveau",
        "type_document",
        "annee",
        "statut",
        "titre",
        "url_source",
        "objet_source",
        "chemin_technique_existant",
        "chemin_par_niveau",
        "chemin_par_scope",
    }
    with placement_catalog_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        columns = set(reader.fieldnames or ())
        missing = sorted(required_columns - columns)
        if missing:
            raise ValueError(
                "placement catalog missing required columns: " + ", ".join(missing)
            )
        for line_number, row in enumerate(reader, start=2):
            content_sha256 = row.get("sha256", "")
            artifact = catalog.artifacts.get(content_sha256)
            if artifact is None or not any(
                item.path.startswith("01_EDUSCOL_OFFICIEL/")
                for item in artifact.physical_objects
            ):
                raise ValueError(
                    "unknown Eduscol content SHA256 at placement line "
                    f"{line_number}: {content_sha256}"
                )
            artifact.pedagogical_placements.append(
                _pedagogical_placement_from_row(row)
            )


def _apply_mandatory_ingest_gates(
    base_disposition: Disposition,
    content_sha256: str,
    rights_cleared_sha256: set[str] | frozenset[str],
    pii_cleared_sha256: set[str] | frozenset[str],
) -> tuple[Disposition, str, dict[str, str]]:
    if base_disposition is not Disposition.INGEST:
        return base_disposition, "", {}

    gate_statuses = {
        "rights": (
            "PASS"
            if content_sha256 in rights_cleared_sha256
            else "BLOCKED_NOT_CLEARED"
        ),
        "pii": (
            "PASS"
            if content_sha256 in pii_cleared_sha256
            else "BLOCKED_NOT_CLEARED"
        ),
    }
    blocked = [name for name, status in gate_statuses.items() if status != "PASS"]
    if blocked:
        return (
            Disposition.REVIEW_REQUIRED,
            "Mandatory gates not cleared: " + ", ".join(blocked),
            gate_statuses,
        )
    return Disposition.INGEST, "", gate_statuses


def compile_sealed_catalog(
    manifest_path: Path,
    placement_catalog_path: Path,
    config: dict[str, Any],
    *,
    rights_cleared_sha256: set[str] | frozenset[str] = frozenset(),
    pii_cleared_sha256: set[str] | frozenset[str] = frozenset(),
) -> SealedCorpusCatalog:
    """Compile the real physical corpus and join every Eduscol placement by SHA."""
    manifest_sha256 = compute_file_sha256(manifest_path)
    expected_manifest_sha256 = config.get("manifest_sha256")
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError(
            "manifest SHA256 mismatch: "
            f"expected={expected_manifest_sha256}, actual={manifest_sha256}"
        )

    entries = _parse_sealed_manifest(manifest_path)
    if any(object_path == _MANIFEST_SELF_PATH for _, object_path in entries):
        raise ValueError("sealed manifest must not contain its own path")

    catalog = SealedCorpusCatalog(
        config_id=str(config.get("config_id", "unknown")),
        manifest_path=str(manifest_path),
        manifest_sha256=manifest_sha256,
        placement_catalog_path=str(placement_catalog_path),
        placement_catalog_sha256=compute_file_sha256(placement_catalog_path),
        compiled_at=datetime.now(UTC).isoformat(),
        manifest_entries=len(entries),
    )

    for content_sha256, object_path in entries:
        base, routing_reason, zone, currentness, rights_category = (
            _determine_disposition(object_path, config)
        )
        disposition, gate_reason, gate_statuses = _apply_mandatory_ingest_gates(
            base,
            content_sha256,
            rights_cleared_sha256,
            pii_cleared_sha256,
        )
        physical_object = PhysicalCorpusObject(
            content_sha256=content_sha256,
            path=object_path,
            base_disposition=base,
            disposition=disposition,
            disposition_reason=gate_reason or routing_reason,
            zone=zone,
            currentness=currentness,
            rights_category_candidate=rights_category,
            gate_statuses=gate_statuses,
        )
        catalog.physical_objects.append(physical_object)
        artifact = catalog.artifacts.setdefault(
            content_sha256,
            ContentArtifact(sha256=content_sha256),
        )
        artifact.physical_objects.append(physical_object)

    manifest_self = PhysicalCorpusObject(
        content_sha256=manifest_sha256,
        path=_MANIFEST_SELF_PATH,
        base_disposition=Disposition.EXCLUDE,
        disposition=Disposition.EXCLUDE,
        disposition_reason="MANIFEST_SELF_OBJECT",
        zone="00_ADMIN/",
        currentness=None,
        rights_category_candidate=None,
        is_manifest_self=True,
    )
    catalog.physical_objects.append(manifest_self)
    catalog.artifacts.setdefault(
        manifest_sha256,
        ContentArtifact(sha256=manifest_sha256),
    ).physical_objects.append(manifest_self)

    _attach_eduscol_placements(catalog, placement_catalog_path)
    catalog.verify()
    return catalog


def _report_to_json(report: CompilationReport, include_objects: bool = False) -> dict[str, Any]:
    """Convert report to JSON-serializable dict."""
    result = {
        "config_id": report.config_id,
        "manifest_path": report.manifest_path,
        "manifest_sha256": report.manifest_sha256,
        "corpus_total_objects": report.corpus_total_objects,
        "expected_total": report.expected_total,
        "totals": report.totals.to_dict(),
        "totals_sum": report.totals.total(),
        "verification_passed": report.verification_passed,
        "verification_errors": report.verification_errors,
        "compiled_at": report.compiled_at,
    }

    if include_objects:
        result["objects"] = [
            {
                "sha256": obj.sha256,
                "path": obj.path,
                "size_bytes": obj.size_bytes,
                "disposition": obj.disposition.value,
                "disposition_reason": obj.disposition_reason,
                "zone": obj.zone,
                "currentness": obj.currentness,
                "rights_category_candidate": obj.rights_category_candidate,
            }
            for obj in report.objects
        ]

    return result


def print_summary(report: CompilationReport) -> None:
    """Print compilation summary to stdout."""
    print(f"CORPUS CATALOG COMPILATION — {report.config_id}")
    print("=" * 60)
    print(f"Manifest: {report.manifest_path}")
    print(f"Manifest SHA256: {report.manifest_sha256}")
    print(f"Compiled at: {report.compiled_at}")
    print()
    print("DISPOSITION TOTALS:")
    for disposition, count in report.totals.to_dict().items():
        pct = (count / report.corpus_total_objects * 100) if report.corpus_total_objects > 0 else 0
        print(f"  {disposition:20} = {count:5} ({pct:5.1f}%)")
    print(f"  {'SUM':20} = {report.totals.total():5}")
    print()
    print(f"Expected total: {report.expected_total}")
    print(f"Actual total:   {report.corpus_total_objects}")
    print()
    if report.verification_passed:
        print("VERIFICATION: PASSED")
        print("  SUM(dispositions) = corpus_total_objects")
        print("  No overlap (duplicate SHA256)")
        print("  No gap (unassigned objects)")
    else:
        print("VERIFICATION: FAILED")
        for error in report.verification_errors:
            print(f"  ERROR: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile corpus catalog with disposition assignments."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to corpus manifest (TSV format)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/corpus_zone_routing.yml"),
        help="Path to zone routing config",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for JSON report",
    )
    parser.add_argument(
        "--include-objects",
        action="store_true",
        help="Include full object list in JSON output",
    )
    args = parser.parse_args()

    config = load_routing_config(args.config)
    report = compile_catalog(args.manifest, config)

    print_summary(report)

    if args.output:
        output_data = _report_to_json(report, include_objects=args.include_objects)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nJSON report written to: {args.output}")

    return 0 if report.verification_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
