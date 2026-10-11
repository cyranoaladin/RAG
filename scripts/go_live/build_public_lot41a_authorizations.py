#!/usr/bin/env python3
"""Proposer onze LOT41A-V2 publics à partir du contenu A scellé.

Ces fichiers sont des décisions à relire dans une PR. Ils ne portent aucune
review, signature, autorisation enregistrée ou capacité de publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2
from nexus_contracts.authorization_set import scope_digest
from nexus_release_chain.public_successor_activation import (
    derive_public_release_scope_placement,
    verify_content_anchor,
    verify_content_currentness,
)

ROOT = Path(__file__).resolve().parents[2]
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
ANCHOR_SHA256 = "159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0"
RELEASE = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)
ATTESTATION = ROOT / "docs/reports/go_live/student_derivative_source_currentness_20261010.json"


def _load_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"sealed file absent or linked: {path.name}")
    document = json.loads(path.read_bytes())
    if not isinstance(document, dict):
        raise ValueError(f"sealed file malformed: {path.name}")
    return document


def build_proposals(
    *,
    anchor_path: Path,
    anchor_sha256: str,
    release_root: Path,
    currentness_attestation_path: Path,
    now_utc: datetime,
) -> dict[str, bytes]:
    """Dériver les seuls octets LOT41A à approuver, sans fabriquer de revue."""
    content = verify_content_anchor(anchor_path, anchor_sha256, release_root)
    expiry = verify_content_currentness(release_root, content, now_utc)
    projection = derive_public_release_scope_placement(release_root, content)
    gate = release_root / "profile_gate"
    index = _load_json(release_root / "preparation-index.json")
    attestation_raw = currentness_attestation_path.read_bytes()
    if hashlib.sha256(attestation_raw).hexdigest() != index.get(
        "source_currentness_attestation_sha256"
    ):
        raise ValueError("currentness attestation differs from A")
    attestation = _load_json(currentness_attestation_path)
    artifact_count = content.expected_counts["unique_artifacts"]
    if attestation.get("status_counts") != {"PASS": artifact_count}:
        raise ValueError("currentness attestation lacks complete passes")
    valid_from = datetime.fromisoformat(attestation["attested_at_utc"].replace("Z", "+00:00"))
    if valid_from.tzinfo is None or valid_from >= expiry:
        raise ValueError("currentness attestation time invalid")

    registry = _load_json(gate / "artifacts.release.json")
    rights = _load_json(gate / "public_rights_registry.json")
    pii = _load_json(gate / "public_pii_registry.json")
    artifacts = registry.get("artifacts")
    rights_rows = rights.get("entries")
    pii_rows = pii.get("entries")
    if not all(
        isinstance(rows, list) and len(rows) == artifact_count
        for rows in (artifacts, rights_rows, pii_rows)
    ):
        raise ValueError("A rights, PII or derivative population incomplete")
    if (
        rights.get("authorized_use") != "student_retrieval_excerpt_only"
        or rights.get("full_pdf_redistribution_allowed") is not False
        or rights.get("answer_generation_allowed") is not False
    ):
        raise ValueError("A rights use differs from student excerpt retrieval")
    by_sha = [{row["content_sha256"]: row for row in rows} for rows in (artifacts, rights_rows, pii_rows)]
    if any(len(indexed) != artifact_count for indexed in by_sha) or not (
        set(by_sha[0]) == set(by_sha[1]) == set(by_sha[2])
    ):
        raise ValueError("A rights or PII identities incomplete")
    for sha, artifact in by_sha[0].items():
        right, pii_fact = by_sha[1][sha], by_sha[2][sha]
        if (
            right.get("rights_basis") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
            or pii_fact.get("pii_gate_status") != "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
            or any(
                fact.get("source_pdf_sha256") != artifact.get("source_pdf_sha256")
                or fact.get("derivative_receipt_sha256") != artifact.get("derivative_receipt_sha256")
                for fact in (right, pii_fact)
            )
        ):
            raise ValueError("A rights or PII proof differs from derivative")
        source_url = artifact.get("source_url")
        if not isinstance(source_url, str) or (
            urlsplit(source_url).scheme,
            urlsplit(source_url).netloc,
        ) != ("https", "eduscol.education.gouv.fr"):
            raise ValueError("A derivative source outside Eduscol authority")

    pii_ref = (
        "profile_gate/public_pii_registry.json@sha256:"
        + _load_json(anchor_path)["preparation_sidecars"]["public_pii_registry.json"]
    )
    entries_by_scope: dict[str, list] = defaultdict(list)
    for entry in projection.placements:
        entries_by_scope[scope_digest(entry.scope)].append(entry)
    if (
        len(entries_by_scope) != content.expected_counts["subjects"]
        or len(projection.placements) != content.expected_counts["placements"]
    ):
        raise ValueError("A does not contain eleven public scope populations")
    proposals: dict[str, bytes] = {}
    for entries in entries_by_scope.values():
        first = entries[0]
        collection = str(first.scope.collection)
        if first.scope.visibility != "public" or any(
            entry.profile_id != collection
            or entry.profile_version != first.profile_version
            or entry.profile_fingerprint != first.profile_fingerprint
            for entry in entries
        ):
            raise ValueError("A public profile identity differs")
        authorization_id = (
            "lot41a-student-public-"
            + collection.removeprefix("rag_nexus_").replace("_", "-")
            + "-v1"
        )
        artifact = ScopeAuthorizationArtifactV2.model_validate(
            {
                "protocol_version": "LOT41A-V2",
                "authorization_id": authorization_id,
                "decision": "AUTHORIZE_INGESTION_SCOPE",
                "scope": first.scope,
                "manifest_digest": projection.profile_manifest_digest,
                "profile_id": collection,
                "profile_version": first.profile_version,
                "profile_fingerprint": first.profile_fingerprint,
                "allowed_domains": ["eduscol.education.gouv.fr"],
                "rights_categories": ["public_allowed"],
                "exclusions": [],
                "pii_absence_attested": True,
                "pii_absence_evidence": pii_ref,
                "valid_from": valid_from,
                "valid_until": expiry,
                "allowed_content_sha256": sorted({entry.content_sha256 for entry in entries}),
            }
        )
        proposals[artifact.canonical_path()] = artifact.canonical_bytes()
    if len(proposals) != content.expected_counts["subjects"]:
        raise ValueError("one distinct LOT41A path per A subject required")
    return dict(sorted(proposals.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Écrire les propositions canoniques dans governance/authorizations")
    mode.add_argument("--check", action="store_true", help="Comparer les onze fichiers gouvernés à A")
    args = parser.parse_args()
    try:
        proposals = build_proposals(
            anchor_path=ANCHOR,
            anchor_sha256=ANCHOR_SHA256,
            release_root=RELEASE,
            currentness_attestation_path=ATTESTATION,
            now_utc=datetime.now(UTC),
        )
        for relative, raw in proposals.items():
            destination = ROOT / relative
            if destination.exists() and destination.read_bytes() != raw:
                raise ValueError(f"existing authorization differs: {relative}")
            if args.check and not destination.is_file():
                raise ValueError(f"authorization missing: {relative}")
        if args.write:
            for relative, raw in proposals.items():
                destination = ROOT / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    destination.write_bytes(raw)
        print(f"PROPOSALS={len(proposals)} REVIEW_BINDINGS=0", flush=True)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"public LOT41A proposals refused: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
