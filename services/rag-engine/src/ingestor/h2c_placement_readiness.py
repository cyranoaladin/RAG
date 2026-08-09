"""Compilation fail-closed des placements de la première vague H2-C.

Le catalogue scellé reste la source des faits. La politique versionnée ne
contient qu'une liste positive, liée au digest du corpus et à la preuve PII :
tout placement absent ou dont un seul champ source dérive reste
``REVIEW_REQUIRED``. Aucun niveau n'est inféré depuis un titre de document.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from .collection_config import (
    CollectionConfigError,
    resolve_collection_v2,
    resolve_declared_collection_v2,
)

POLICY_FILENAME = "h2_initial_placement_policy.yml"
EXPECTED_POLICY_VERSION = "H2C-INITIAL-PLACEMENTS-V1"
EXPECTED_CORPUS_MANIFEST_SHA256 = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)
EXPECTED_PII_EVIDENCE_SHA256 = (
    "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311"
)
EXPECTED_CATALOG_KIND = "REAL_SEALED_CORPUS"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PlacementReadinessError(ValueError):
    """La politique ou le catalogue n'est pas suffisamment fiable."""


@dataclass(frozen=True)
class ApprovedPlacementRule:
    content_sha256: str
    source_scope: str
    source_subject: str
    source_level: str
    source_status: str
    source_document_type: str
    source_url: str
    collection: str


@dataclass(frozen=True)
class InitialPlacementPolicy:
    policy_version: str
    decision_type: str
    decision_maker: str
    decision_date: str
    corpus_manifest_sha256: str
    pii_evidence_sha256: str
    known_quarantine_sha256: str
    default_decision: str
    approved_artifacts: Mapping[str, ApprovedPlacementRule]

    def as_evidence(self) -> dict[str, object]:
        """Projection non sensible, stable et sérialisable du choix humain."""
        return {
            "policy_version": self.policy_version,
            "decision_type": self.decision_type,
            "decision_maker": self.decision_maker,
            "decision_date": self.decision_date,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "pii_evidence_sha256": self.pii_evidence_sha256,
            "known_quarantine_sha256": self.known_quarantine_sha256,
            "default_decision": self.default_decision,
            "approved_artifacts": {
                sha: asdict(rule) for sha, rule in sorted(self.approved_artifacts.items())
            },
        }


@dataclass(frozen=True)
class PlacementReadinessReport:
    corpus_manifest_sha256: str
    placements_unclassified_total: int
    base_candidate_artifacts: int
    pii_cleared_artifacts: int
    pii_blocked_artifacts: int
    initial_candidate_placements: int
    initial_cleared_placements: int
    initial_candidate_placements_unclassified: int
    initial_cleared_placements_unclassified: int
    initial_candidate_placements_transversal: int
    initial_cleared_placements_transversal: int
    eligible_artifacts: tuple[str, ...]
    eligible_placements: int
    placement_blocked_artifacts: int
    placements_collection_resolved: int
    placements_collection_unresolved: int
    required_collections: tuple[str, ...]
    required_collections_instantiated: int
    required_collections_not_instantiated: tuple[str, ...]
    ingested_placements_with_unknown_scope: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / POLICY_FILENAME


def _read_mapping(source: Path | Mapping[str, object]) -> dict[str, Any]:
    if isinstance(source, Path):
        try:
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PlacementReadinessError(f"Cannot read placement policy: {exc}") from exc
    else:
        data = dict(source)
    if not isinstance(data, dict):
        raise PlacementReadinessError("Placement policy must be a YAML mapping")
    return cast(dict[str, Any], data)


def _required_string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PlacementReadinessError(f"Placement policy field {field!r} is required")
    return value


def load_initial_placement_policy(
    source: Path | Mapping[str, object] | None = None,
) -> InitialPlacementPolicy:
    """Charge et verrouille la décision positive ; aucun fallback permissif."""
    data = _read_mapping(source or _default_policy_path())
    version = _required_string(data, "policy_version")
    if version != EXPECTED_POLICY_VERSION:
        raise PlacementReadinessError(f"Unsupported placement policy version: {version}")

    manifest_sha = _required_string(data, "corpus_manifest_sha256")
    if manifest_sha != EXPECTED_CORPUS_MANIFEST_SHA256:
        raise PlacementReadinessError("Placement policy corpus manifest binding drifted")
    pii_sha = _required_string(data, "pii_evidence_sha256")
    if pii_sha != EXPECTED_PII_EVIDENCE_SHA256:
        raise PlacementReadinessError("Placement policy PII evidence binding drifted")

    quarantine_sha = _required_string(data, "known_quarantine_sha256")
    if _SHA256.fullmatch(quarantine_sha) is None:
        raise PlacementReadinessError("known quarantine SHA256 is malformed")
    if data.get("default_decision") != "REVIEW_REQUIRED":
        raise PlacementReadinessError("default placement decision must remain REVIEW_REQUIRED")

    raw_approved = data.get("approved_artifacts")
    if not isinstance(raw_approved, Mapping) or not raw_approved:
        raise PlacementReadinessError("approved_artifacts must be a non-empty mapping")

    rules: dict[str, ApprovedPlacementRule] = {}
    expected_rule_fields = {
        "source_scope",
        "source_subject",
        "source_level",
        "source_status",
        "source_document_type",
        "source_url",
        "collection",
    }
    for sha, raw_rule in raw_approved.items():
        if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
            raise PlacementReadinessError("approved artifact SHA256 is malformed")
        if sha == quarantine_sha:
            raise PlacementReadinessError("known PII quarantine artifact cannot be approved")
        if not isinstance(raw_rule, Mapping) or set(raw_rule) != expected_rule_fields:
            raise PlacementReadinessError(f"approved placement rule for {sha} has wrong fields")
        values = {field: _required_string(raw_rule, field) for field in expected_rule_fields}
        rules[sha] = ApprovedPlacementRule(content_sha256=sha, **values)

    return InitialPlacementPolicy(
        policy_version=version,
        decision_type=_required_string(data, "decision_type"),
        decision_maker=_required_string(data, "decision_maker"),
        decision_date=_required_string(data, "decision_date"),
        corpus_manifest_sha256=manifest_sha,
        pii_evidence_sha256=pii_sha,
        known_quarantine_sha256=quarantine_sha,
        default_decision="REVIEW_REQUIRED",
        approved_artifacts=rules,
    )


def _candidate_object(artifact: Mapping[str, object]) -> Mapping[str, object] | None:
    objects = artifact.get("physical_objects")
    if not isinstance(objects, list):
        raise PlacementReadinessError("artifact physical_objects is not a list")
    candidates = [
        item
        for item in objects
        if isinstance(item, Mapping) and item.get("base_disposition") == "INGEST"
    ]
    if len(candidates) > 1:
        raise PlacementReadinessError("one artifact has multiple INGEST physical objects")
    return candidates[0] if candidates else None


def _placements(artifact: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = artifact.get("pedagogical_placements")
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise PlacementReadinessError("artifact pedagogical_placements is malformed")
    declared = artifact.get("pedagogical_placement_count")
    if declared != len(raw):
        raise PlacementReadinessError("artifact placement count is inconsistent")
    return cast(list[Mapping[str, object]], raw)


def _matches_rule(placement: Mapping[str, object], rule: ApprovedPlacementRule) -> bool:
    return (
        placement.get("content_sha256") == rule.content_sha256
        and placement.get("scope") == rule.source_scope
        and placement.get("subject") == rule.source_subject
        and placement.get("level") == rule.source_level
        and placement.get("status") == rule.source_status
        and placement.get("document_type") == rule.source_document_type
        and placement.get("source_url") == rule.source_url
    )


def _pii_status(physical: Mapping[str, object]) -> object:
    gates = physical.get("gate_statuses")
    if not isinstance(gates, Mapping):
        return None
    return gates.get("pii")


def _validate_collection(rule: ApprovedPlacementRule, config: Mapping[str, object]) -> bool:
    declared = resolve_declared_collection_v2(rule.collection, config)
    expected = {
        "matiere": "philosophie",
        "niveau": "terminale",
        "voie": "generale",
        "statut": "tronc_commun",
        "domain": "education",
    }
    if any(declared.get(field) != value for field, value in expected.items()):
        raise PlacementReadinessError(
            f"collection {rule.collection!r} does not match its approved placement scope"
        )
    try:
        resolve_collection_v2(rule.collection, config)
    except CollectionConfigError:
        return False
    return True


def compile_initial_placement_readiness(
    catalog: Mapping[str, object],
    policy: InitialPlacementPolicy,
    collection_config: Mapping[str, object],
) -> PlacementReadinessReport:
    """Mesure la totalité de la vague initiale et n'autorise que l'allowlist exacte."""
    if catalog.get("catalog_kind") != EXPECTED_CATALOG_KIND:
        raise PlacementReadinessError("final gate requires the real sealed corpus catalog")
    if catalog.get("manifest_sha256") != policy.corpus_manifest_sha256:
        raise PlacementReadinessError("catalog manifest does not match placement policy manifest")
    artifacts = catalog.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise PlacementReadinessError("catalog artifacts mapping is absent")

    candidate_rows: list[tuple[str, Mapping[str, object], list[Mapping[str, object]]]] = []
    for sha, artifact in artifacts.items():
        if not isinstance(sha, str) or not isinstance(artifact, Mapping):
            raise PlacementReadinessError("catalog artifact entry is malformed")
        physical = _candidate_object(artifact)
        if physical is not None:
            candidate_rows.append((sha, physical, _placements(artifact)))

    candidate_sha = {sha for sha, _, _ in candidate_rows}
    missing_policy_sha = set(policy.approved_artifacts) - candidate_sha
    if missing_policy_sha:
        raise PlacementReadinessError(
            f"approved artifacts absent from candidate set: {sorted(missing_policy_sha)}"
        )

    pii_clear_rows = [
        row
        for row in candidate_rows
        if _pii_status(row[1]) == "PASS"
    ]
    pii_clear_sha = {sha for sha, _, _ in pii_clear_rows}
    if policy.known_quarantine_sha256 in pii_clear_sha:
        raise PlacementReadinessError("known PII quarantine unexpectedly reports PASS")
    if not set(policy.approved_artifacts) <= pii_clear_sha:
        raise PlacementReadinessError("approved placement lacks PASS PII evidence")

    all_candidate_placements = [p for _, _, placements in candidate_rows for p in placements]
    clear_placements = [p for _, _, placements in pii_clear_rows for p in placements]
    eligible_artifacts: list[str] = []
    eligible_placements = 0
    resolved = 0
    unresolved = 0
    required_collections: set[str] = set()
    instantiated: set[str] = set()

    for sha, _, placements in pii_clear_rows:
        rule = policy.approved_artifacts.get(sha)
        if rule is None:
            continue
        matches = [placement for placement in placements if _matches_rule(placement, rule)]
        if len(matches) != 1:
            continue
        required_collections.add(rule.collection)
        if _validate_collection(rule, collection_config):
            instantiated.add(rule.collection)
            resolved += 1
            eligible_placements += 1
            eligible_artifacts.append(sha)
        else:
            unresolved += 1

    required_not_instantiated = tuple(sorted(required_collections - instantiated))
    top_unclassified = catalog.get("eduscol_placements_unclassified")
    if not isinstance(top_unclassified, int) or top_unclassified < 0:
        raise PlacementReadinessError("catalog unclassified placement total is absent")

    eligible_set = set(eligible_artifacts)
    return PlacementReadinessReport(
        corpus_manifest_sha256=policy.corpus_manifest_sha256,
        placements_unclassified_total=top_unclassified,
        base_candidate_artifacts=len(candidate_rows),
        pii_cleared_artifacts=len(pii_clear_rows),
        pii_blocked_artifacts=len(candidate_rows) - len(pii_clear_rows),
        initial_candidate_placements=len(all_candidate_placements),
        initial_cleared_placements=len(clear_placements),
        initial_candidate_placements_unclassified=sum(
            placement.get("classified") is False for placement in all_candidate_placements
        ),
        initial_cleared_placements_unclassified=sum(
            placement.get("classified") is False for placement in clear_placements
        ),
        initial_candidate_placements_transversal=sum(
            placement.get("level") == "multi-niveaux" for placement in all_candidate_placements
        ),
        initial_cleared_placements_transversal=sum(
            placement.get("level") == "multi-niveaux" for placement in clear_placements
        ),
        eligible_artifacts=tuple(sorted(eligible_artifacts)),
        eligible_placements=eligible_placements,
        placement_blocked_artifacts=len(pii_clear_sha - eligible_set),
        placements_collection_resolved=resolved,
        placements_collection_unresolved=unresolved,
        required_collections=tuple(sorted(required_collections)),
        required_collections_instantiated=len(instantiated),
        required_collections_not_instantiated=required_not_instantiated,
        ingested_placements_with_unknown_scope=0,
    )


def write_readiness_evidence(report: PlacementReadinessReport, destination: Path) -> None:
    """Écrit uniquement des compteurs/identifiants non sensibles."""
    destination.write_text(
        json.dumps(report.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


__all__ = [
    "InitialPlacementPolicy",
    "PlacementReadinessError",
    "PlacementReadinessReport",
    "compile_initial_placement_readiness",
    "load_initial_placement_policy",
    "write_readiness_evidence",
]
