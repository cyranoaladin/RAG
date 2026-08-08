"""Artifact-Placement Model — H2-B.

Implements the 1:N relationship between corpus artifacts and their placements.

Key concepts:
- CorpusArtifact: Unique physical object identified by SHA256. Carries:
  - File properties (size, format, mime type)
  - PII scan status (pii_detected, signal_classes)
  - Rights status (rights_category_candidate)

- CorpusPlacement: Where an artifact appears in the corpus. Carries:
  - Path and zone information
  - Currentness classification
  - Disposition (derived from placement, not artifact)

CRITICAL INVARIANT — FAIL-CLOSED DISPOSITION:
- CORPUS_TOTAL = 2,584 unique artifacts
- PLACEMENT_TOTAL = 2,956 placements (some artifacts have multiple placements)
- Each artifact has >= 1 placement
- Final disposition uses FAIL-CLOSED precedence:
  EXCLUDE > QUARANTINE > UNSUPPORTED > ARCHIVE_ONLY > REVIEW_REQUIRED > INGEST
- Any blocking placement disposition OVERRIDES INGEST
- INGEST requires ALL placements to be INGEST (AND-gate, not priority)

Usage:
    python -m rag_pedago.imports.artifact_placement_model \
        --manifest data/corpus/eduscol_catalog.tsv \
        --config configs/corpus_zone_routing.yml \
        --output data/reports/artifact_placement_catalog.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class Disposition(StrEnum):
    """Mutually exclusive disposition for artifacts."""

    INGEST = "INGEST"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    QUARANTINE = "QUARANTINE"
    ARCHIVE_ONLY = "ARCHIVE_ONLY"
    EXCLUDE = "EXCLUDE"
    UNSUPPORTED = "UNSUPPORTED"


class Currentness(StrEnum):
    """Document regulatory currentness."""

    ACTUEL = "actuel"
    TRANSITION = "transition"
    A_VERIFIER = "a_verifier"
    ARCHIVE = "archive"
    CONFLICT = "conflict"
    UNCLASSIFIED = "unclassified"


# FAIL-CLOSED disposition precedence (lower number = blocks, wins in min())
# CRITICAL: INGEST must have HIGHEST number (lowest priority)
# Any blocking disposition must override INGEST
DISPOSITION_PRECEDENCE = {
    Disposition.EXCLUDE: 0,       # Structural exclusion (admin, metadata)
    Disposition.QUARANTINE: 1,    # Safety block (PII, provenance)
    Disposition.UNSUPPORTED: 2,   # Format block (GGB, etc.)
    Disposition.ARCHIVE_ONLY: 3,  # Currentness block (superseded)
    Disposition.REVIEW_REQUIRED: 4,  # Needs human review
    Disposition.INGEST: 5,        # ONLY if ALL gates pass
}

# Alias for backwards compatibility in tests
DISPOSITION_PRIORITY = DISPOSITION_PRECEDENCE


@dataclass
class CorpusPlacement:
    """A placement of an artifact in the corpus.

    One artifact can have multiple placements (same content, different paths).
    """

    path: str
    zone: str
    currentness: Currentness
    disposition: Disposition
    disposition_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "zone": self.zone,
            "currentness": self.currentness.value,
            "disposition": self.disposition.value,
            "disposition_reason": self.disposition_reason,
        }


@dataclass
class CorpusArtifact:
    """A unique physical artifact in the corpus, identified by SHA256.

    Artifacts carry intrinsic properties (PII, rights) that don't depend on
    where they're placed. Final disposition uses FAIL-CLOSED semantics:
    any blocking placement disposition overrides INGEST.
    """

    sha256: str
    size_bytes: int
    placements: list[CorpusPlacement] = field(default_factory=list)

    # PII scan results (populated after scan)
    pii_scanned: bool = False
    pii_detected: bool = False
    pii_signal_classes: list[str] = field(default_factory=list)
    pii_signal_count: int = 0

    # Rights status (from rights evidence registry)
    rights_status: str | None = None
    rights_category_candidate: str | None = None

    def add_placement(self, placement: CorpusPlacement) -> None:
        """Add a placement for this artifact."""
        self.placements.append(placement)

    @property
    def placement_count(self) -> int:
        return len(self.placements)

    @property
    def final_disposition(self) -> Disposition:
        """Return fail-closed disposition across all placements.

        FAIL-CLOSED PRECEDENCE (blocking wins):
        EXCLUDE > QUARANTINE > UNSUPPORTED > ARCHIVE_ONLY > REVIEW_REQUIRED > INGEST

        INGEST is assigned ONLY if no placement has a blocking disposition.
        """
        if not self.placements:
            return Disposition.REVIEW_REQUIRED

        # min() selects lowest precedence number = most blocking
        controlling = min(
            self.placements,
            key=lambda p: DISPOSITION_PRECEDENCE[p.disposition]
        )
        return controlling.disposition

    # Alias for backwards compatibility
    @property
    def best_disposition(self) -> Disposition:
        """Alias for final_disposition (fail-closed semantics)."""
        return self.final_disposition

    @property
    def controlling_placement(self) -> CorpusPlacement | None:
        """Return the placement that determines final disposition."""
        if not self.placements:
            return None
        return min(
            self.placements,
            key=lambda p: DISPOSITION_PRECEDENCE[p.disposition]
        )

    # Alias for backwards compatibility
    @property
    def best_placement(self) -> CorpusPlacement | None:
        """Alias for controlling_placement."""
        return self.controlling_placement

    @property
    def zones(self) -> set[str]:
        """All zones where this artifact is placed."""
        return {p.zone for p in self.placements}

    @property
    def paths(self) -> list[str]:
        """All paths where this artifact is placed."""
        return [p.path for p in self.placements]

    def to_dict(self, include_placements: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "placement_count": self.placement_count,
            "best_disposition": self.best_disposition.value,
            "pii_scanned": self.pii_scanned,
            "pii_detected": self.pii_detected,
            "rights_status": self.rights_status,
            "rights_category_candidate": self.rights_category_candidate,
        }
        if self.pii_scanned:
            result["pii_signal_classes"] = self.pii_signal_classes
            result["pii_signal_count"] = self.pii_signal_count
        if include_placements:
            result["placements"] = [p.to_dict() for p in self.placements]
        return result


@dataclass
class ArtifactPlacementCatalog:
    """Full catalog with artifact/placement separation."""

    config_id: str
    manifest_path: str
    manifest_sha256: str
    compiled_at: str

    # Totals
    artifact_count: int = 0
    placement_count: int = 0
    expected_artifact_count: int = 2584
    expected_placement_count: int = 2956

    # Artifacts indexed by SHA256
    artifacts: dict[str, CorpusArtifact] = field(default_factory=dict)

    # Disposition breakdown (by artifact's best disposition)
    disposition_counts: dict[str, int] = field(default_factory=dict)

    # Multi-placement stats
    single_placement_count: int = 0
    multi_placement_count: int = 0
    max_placements_per_artifact: int = 0

    # Verification
    verification_passed: bool = False
    verification_errors: list[str] = field(default_factory=list)

    def add_artifact(self, artifact: CorpusArtifact) -> None:
        """Add an artifact to the catalog."""
        self.artifacts[artifact.sha256] = artifact
        self.artifact_count = len(self.artifacts)

    def get_artifact(self, sha256: str) -> CorpusArtifact | None:
        """Get artifact by SHA256."""
        return self.artifacts.get(sha256)

    def compute_stats(self) -> None:
        """Compute catalog statistics."""
        self.artifact_count = len(self.artifacts)
        self.placement_count = sum(a.placement_count for a in self.artifacts.values())

        # Disposition counts (by artifact's best disposition)
        self.disposition_counts = {}
        for artifact in self.artifacts.values():
            disp = artifact.best_disposition.value
            self.disposition_counts[disp] = self.disposition_counts.get(disp, 0) + 1

        # Multi-placement stats
        self.single_placement_count = sum(
            1 for a in self.artifacts.values() if a.placement_count == 1
        )
        self.multi_placement_count = sum(
            1 for a in self.artifacts.values() if a.placement_count > 1
        )
        self.max_placements_per_artifact = max(
            (a.placement_count for a in self.artifacts.values()),
            default=0
        )

    def verify(self) -> None:
        """Verify catalog integrity."""
        self.compute_stats()
        self.verification_errors = []

        # Check artifact count
        if self.artifact_count != self.expected_artifact_count:
            self.verification_errors.append(
                f"artifact_count={self.artifact_count} != "
                f"expected={self.expected_artifact_count}"
            )

        # Check placement count
        if self.placement_count != self.expected_placement_count:
            self.verification_errors.append(
                f"placement_count={self.placement_count} != "
                f"expected={self.expected_placement_count}"
            )

        # Check no orphan artifacts (all have >= 1 placement)
        orphans = [
            sha256 for sha256, a in self.artifacts.items()
            if a.placement_count == 0
        ]
        if orphans:
            self.verification_errors.append(
                f"ORPHAN_ARTIFACTS: {len(orphans)} artifacts have no placements"
            )

        # Check disposition sum equals artifact count
        disp_sum = sum(self.disposition_counts.values())
        if disp_sum != self.artifact_count:
            self.verification_errors.append(
                f"SUM(dispositions)={disp_sum} != artifact_count={self.artifact_count}"
            )

        self.verification_passed = len(self.verification_errors) == 0

    def to_dict(self, include_artifacts: bool = False) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: dict[str, Any] = {
            "config_id": self.config_id,
            "manifest_path": self.manifest_path,
            "manifest_sha256": self.manifest_sha256,
            "compiled_at": self.compiled_at,
            "artifact_count": self.artifact_count,
            "placement_count": self.placement_count,
            "expected_artifact_count": self.expected_artifact_count,
            "expected_placement_count": self.expected_placement_count,
            "disposition_counts": self.disposition_counts,
            "single_placement_count": self.single_placement_count,
            "multi_placement_count": self.multi_placement_count,
            "max_placements_per_artifact": self.max_placements_per_artifact,
            "verification_passed": self.verification_passed,
            "verification_errors": self.verification_errors,
        }
        if include_artifacts:
            result["artifacts"] = {
                sha256: artifact.to_dict(include_placements=True)
                for sha256, artifact in self.artifacts.items()
            }
        return result


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


def _determine_placement_disposition(
    path: str,
    config: dict[str, Any],
) -> tuple[Disposition, str, str, Currentness]:
    """Determine disposition for a placement based on routing rules.

    Returns: (disposition, reason, zone, currentness)
    """
    zone_rules = config.get("zone_rules", [])

    for rule in zone_rules:
        zone_prefix = rule.get("zone_prefix", "")
        if not path.startswith(zone_prefix):
            continue

        # Check sub-zone routing if present
        sub_zone_routing = rule.get("sub_zone_routing")
        if sub_zone_routing:
            for sub_rule in sub_zone_routing:
                sub_zone_suffix = sub_rule.get("sub_zone_suffix")
                if sub_zone_suffix is None or sub_zone_suffix in path:
                    disposition_str = sub_rule.get("disposition")
                    currentness_str = sub_rule.get("currentness", "unclassified")
                    if disposition_str:
                        try:
                            currentness = Currentness(currentness_str)
                        except ValueError:
                            currentness = Currentness.UNCLASSIFIED
                        return (
                            Disposition(disposition_str),
                            sub_rule.get("review_reason")
                            or sub_rule.get("archive_reason")
                            or sub_rule.get("quarantine_reason")
                            or f"Matched sub-zone: {sub_zone_suffix}",
                            zone_prefix,
                            currentness,
                        )

        # Direct disposition on zone
        disposition_str = rule.get("disposition")
        if disposition_str:
            return (
                Disposition(disposition_str),
                rule.get("reason", f"Matched zone: {zone_prefix}"),
                zone_prefix,
                Currentness.UNCLASSIFIED,
            )

    # No rule matched — REVIEW_REQUIRED as fail-safe
    return (
        Disposition.REVIEW_REQUIRED,
        "No zone rule matched — requires review",
        "UNKNOWN",
        Currentness.UNCLASSIFIED,
    )


def compile_artifact_placement_catalog(
    manifest_path: Path,
    config: dict[str, Any],
) -> ArtifactPlacementCatalog:
    """Compile corpus catalog with artifact/placement separation."""
    manifest_sha256 = compute_file_sha256(manifest_path)
    config_id = config.get("config_id", "unknown")

    catalog = ArtifactPlacementCatalog(
        config_id=config_id,
        manifest_path=str(manifest_path),
        manifest_sha256=manifest_sha256,
        compiled_at=datetime.now(UTC).isoformat(),
        expected_artifact_count=config.get("corpus_total_artifacts", 2584),
        expected_placement_count=config.get("corpus_total_placements", 2956),
    )

    # Parse manifest (TSV format)
    with manifest_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for line in reader:
            sha256 = line.get("sha256", "")
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

            if not sha256 or not path:
                continue

            # Determine placement disposition
            disposition, reason, zone, currentness = _determine_placement_disposition(
                path, config
            )

            placement = CorpusPlacement(
                path=path,
                zone=zone,
                currentness=currentness,
                disposition=disposition,
                disposition_reason=reason,
            )

            # Get or create artifact
            artifact = catalog.get_artifact(sha256)
            if artifact is None:
                artifact = CorpusArtifact(
                    sha256=sha256,
                    size_bytes=size_bytes,
                )
                catalog.add_artifact(artifact)

            artifact.add_placement(placement)

    catalog.verify()
    return catalog


def print_summary(catalog: ArtifactPlacementCatalog) -> None:
    """Print catalog summary to stdout."""
    print(f"ARTIFACT-PLACEMENT CATALOG — {catalog.config_id}")
    print("=" * 60)
    print(f"Manifest: {catalog.manifest_path}")
    print(f"Manifest SHA256: {catalog.manifest_sha256}")
    print(f"Compiled at: {catalog.compiled_at}")
    print()
    print("ARTIFACT / PLACEMENT TOTALS:")
    print(f"  Unique artifacts (by SHA256): {catalog.artifact_count:,}")
    print(f"  Total placements:             {catalog.placement_count:,}")
    print(f"  Expected artifacts:           {catalog.expected_artifact_count:,}")
    print(f"  Expected placements:          {catalog.expected_placement_count:,}")
    print()
    print("MULTI-PLACEMENT STATS:")
    print(f"  Single-placement artifacts:   {catalog.single_placement_count:,}")
    print(f"  Multi-placement artifacts:    {catalog.multi_placement_count:,}")
    print(f"  Max placements per artifact:  {catalog.max_placements_per_artifact}")
    print()
    print("DISPOSITION BREAKDOWN (by artifact's best disposition):")
    for disposition, count in sorted(catalog.disposition_counts.items()):
        pct = (count / catalog.artifact_count * 100) if catalog.artifact_count > 0 else 0
        print(f"  {disposition:20} = {count:5} ({pct:5.1f}%)")
    print(f"  {'SUM':20} = {sum(catalog.disposition_counts.values()):5}")
    print()
    if catalog.verification_passed:
        print("VERIFICATION: PASSED")
    else:
        print("VERIFICATION: FAILED")
        for error in catalog.verification_errors:
            print(f"  ERROR: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile artifact-placement catalog."
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
        help="Output path for JSON catalog",
    )
    parser.add_argument(
        "--include-artifacts",
        action="store_true",
        help="Include full artifact list in JSON output",
    )
    args = parser.parse_args()

    config = load_routing_config(args.config)
    catalog = compile_artifact_placement_catalog(args.manifest, config)

    print_summary(catalog)

    if args.output:
        output_data = catalog.to_dict(include_artifacts=args.include_artifacts)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nJSON catalog written to: {args.output}")

    return 0 if catalog.verification_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
