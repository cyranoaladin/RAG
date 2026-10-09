"""Verdict déterministe de l'usage étudiant d'un PDF déjà revu.

Ce module n'accorde aucun droit à partir d'un domaine, d'une ancienne zone
``officiel_public`` ou de la prose libre d'un modèle. Les observations sont
validées séparément ; toute preuve manquante mène à EXCLUDE.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import secrets
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CFTR_SHA256 = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"

REQUIRED_TRUE = (
    "exact_bytes_match",
    "full_document_scan_complete",
    "annexes_scan_complete",
    "explicit_rights_basis_present",
    "reuse_scope_covers_student_retrieval_excerpt",
    "source_exact_document_match",
    "pii_gate_pass",
    "currentness_gate_pass",
    "revocation_gate_pass",
    "student_suitability_pass",
)
REQUIRED_FALSE = (
    "restrictive_notice_detected",
    "teacher_only_detected",
    "non_disclosure_instruction_detected",
    "unlicensed_third_party_content_detected",
)
SUPPORTED_RIGHTS_BASES = frozenset(
    {
        "NEXUS_FIRST_PARTY_OWNED_WITH_REGISTRY_PROOF",
        "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE",
        "EXPLICIT_REUSE_TERMS_COVERING_THE_AUTHORIZED_USE",
        "PUBLIC_DOMAIN_OR_EQUIVALENT_WITH_VERIFIABLE_BASIS",
    }
)
DECISION_EXECUTOR = "nexus-delegated-student-rights-adjudicator-v1"
DELEGATION_ID = "nexus-student-public-rights-abenrhouma-20261009-v1"
TEXT_ASSEMBLY_PROTOCOL = "NEXUS_REVIEW_TEXT_ASSEMBLY_V5"
SHEET_COLUMNS = (
    "content_sha256", "source_release", "collections", "source_path",
    "source_listing_url", "page_count", "source_pii_status",
    "source_currentness_disposition", "automated_signal_pages",
    "explicit_student_exclusion_signal", "rights_review", "student_suitability",
    "third_party_exception_review", "pii_recheck", "currentness_recheck",
    "revocation_recheck", "student_public_disposition", "rights_evidence_ref",
    "decision_evidence_pages", "decision_reason", "human_reviewer", "reviewed_at_utc",
    "decision_executor", "delegation_id", "evidence_sha256",
)
SOURCE_MANIFESTS = (
    ("v4_non_hggsp", "services/rag-pedago/data/releases/prerentree_2026_2027/"
     "profile_gate_v4/release-024f8625ebfeb7ce/profile_gate"),
    ("v5_hggsp", "services/rag-pedago/data/releases/prerentree_2026_2027/"
     "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate"),
)


def source_population_refs(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Relit l'union exacte V4 hors HGGSP et V5 HGGSP, sans l'altérer."""
    refs: list[dict[str, Any]] = []
    counts: dict[str, dict[str, Any]] = {}
    for release, relative in SOURCE_MANIFESTS:
        folder = root / relative
        artifacts_path = folder / "artifacts.release.json"
        artifact_bytes = artifacts_path.read_bytes()
        artifacts = json.loads(artifact_bytes)["artifacts"]
        by_id = {row["artifact_id"]: row for row in artifacts}
        if len(by_id) != len(artifacts):
            raise ValueError("SOURCE_ARTIFACT_DUPLICATE")
        subject_refs: list[dict[str, str]] = []
        selected: set[str] = set()
        for path in sorted((folder / "subjects").glob("*.release.json")):
            is_hggsp = "hggsp" in path.name
            if is_hggsp != (release == "v5_hggsp"):
                continue
            raw = path.read_bytes()
            subject = json.loads(raw)
            collection = subject["collection"]
            placements = subject["placements"]
            if len(placements) != subject["expected_counts"]["placements"]:
                raise ValueError("SOURCE_PLACEMENT_COUNT_MISMATCH")
            subject_refs.append({
                "path": str(path.relative_to(root)),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            for placement in placements:
                sha = placement["artifact_id"]
                if placement["collection"] != collection or sha not in by_id:
                    raise ValueError("SOURCE_PLACEMENT_INVALID")
                selected.add(sha)
                entry = counts.setdefault(sha, {
                    "source_placement_count": 0,
                    "source_chunk_count": 0,
                    "collections": set(),
                })
                entry["source_placement_count"] += 1
                entry["collections"].add(collection)
        if len(subject_refs) != (2 if release == "v5_hggsp" else 9):
            raise ValueError("SOURCE_SUBJECT_COUNT_MISMATCH")
        for sha in selected:
            counts[sha]["source_chunk_count"] += len(by_id[sha]["chunks"])
        refs.append({
            "source_release": release,
            "artifacts_path": str(artifacts_path.relative_to(root)),
            "artifacts_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "subjects": subject_refs,
        })
    return refs, counts


def final_population(
    records: list[Mapping[str, Any]], source_counts: Mapping[str, Mapping[str, Any]]
) -> dict[str, int]:
    """Calcule les comptes servis depuis les seuls SHA explicitement approuvés."""
    decisions = {record["content_sha256"]: record["final_disposition"] for record in records}
    if len(decisions) != len(records) or set(decisions) != set(source_counts):
        raise ValueError("DECISION_INVENTORY_MISMATCH")
    allowed = {"APPROVE_PUBLIC", "EXCLUDE", "REPLACE_WITH_NEW_CONTENT"}
    if any(value not in allowed for value in decisions.values()):
        raise ValueError("DECISION_INVALID")
    approved = [sha for sha, disposition in decisions.items() if disposition == "APPROVE_PUBLIC"]
    return {
        "collections": len({
            name for sha in approved for name in source_counts[sha]["collections"]
        }),
        "artifacts": len(approved),
        "placements": sum(source_counts[sha]["source_placement_count"] for sha in approved),
        "chunks": sum(source_counts[sha]["source_chunk_count"] for sha in approved),
        "approve_public": len(approved),
        "exclude": sum(value == "EXCLUDE" for value in decisions.values()),
        "replace_with_new_content": sum(
            value == "REPLACE_WITH_NEW_CONTENT" for value in decisions.values()
        ),
    }


def build_pack_index(
    root: Path,
    *,
    packet_bytes: bytes,
    records: list[Mapping[str, Any]],
    artifact_digests: Mapping[str, str],
    decision_sheet_bytes: bytes,
    reviewer_pins: Mapping[str, Mapping[str, Any]],
    policy_bytes: bytes,
    mandate_bytes: bytes,
    schema_bytes: bytes,
) -> dict[str, Any]:
    """Scelle la table des preuves et les comptes réels issus des manifests."""
    packet = json.loads(packet_bytes)
    inventory = {row["content_sha256"] for row in packet["artifacts"]}
    if len(packet["artifacts"]) != 315 or len(inventory) != 315:
        raise ValueError("INVENTORY_NOT_315_UNIQUE")
    if set(artifact_digests) != inventory or any(
        not _sha256(value) for value in artifact_digests.values()
    ):
        raise ValueError("ARTIFACT_EVIDENCE_SET_MISMATCH")
    source_refs, counts = source_population_refs(root)
    if set(counts) != inventory:
        raise ValueError("SOURCE_POPULATION_NOT_INVENTORY")
    population = final_population(records, counts)
    policy_sha = hashlib.sha256(policy_bytes).hexdigest()
    mandate_sha = hashlib.sha256(mandate_bytes).hexdigest()
    schema_sha = hashlib.sha256(schema_bytes).hexdigest()
    return {
        "schema_version": "NEXUS_DELEGATED_STUDENT_RIGHTS_EVIDENCE_INDEX_V1",
        "inventory_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "policy_sha256": policy_sha,
        "delegation_sha256": mandate_sha,
        "mandate_sha256": mandate_sha,
        "schema_sha256": schema_sha,
        "engine_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scanner_code_sha256": hashlib.sha256(
            (root / "scripts/go_live/student_rights_pdf_scan.py").read_bytes()
        ).hexdigest(),
        "source_checker_code_sha256": hashlib.sha256(
            (root / "scripts/go_live/student_rights_source_check.py").read_bytes()
        ).hexdigest(),
        "reviewer_code_sha256": hashlib.sha256(
            (root / "scripts/go_live/student_rights_reviewers.py").read_bytes()
        ).hexdigest(),
        "reviewer_a": dict(reviewer_pins["a"]),
        "reviewer_b": dict(reviewer_pins["b"]),
        "source_population": source_refs,
        "artifacts": {
            sha: {
                "path": f"{sha}.json",
                "sha256": artifact_digests[sha],
                "source_placement_count": counts[sha]["source_placement_count"],
                "source_chunk_count": counts[sha]["source_chunk_count"],
            }
            for sha in sorted(inventory)
        },
        "decision_sheet_sha256": hashlib.sha256(decision_sheet_bytes).hexdigest(),
        "final_population": population,
    }


def _canonical_file_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_cas_receipt(source_root: Path, target_root: Path, digest: str) -> None:
    """Copie un reçu CAS vérifié sans suivre un chemin fourni par un modèle."""
    if not _sha256(digest):
        raise ValueError("CAS_RECEIPT_DIGEST_INVALID")
    relative = Path(digest[:2]) / f"{digest}.json"
    source = source_root / relative
    if not source.resolve(strict=True).is_relative_to(source_root.resolve(strict=True)):
        raise ValueError("CAS_RECEIPT_SOURCE_PATH_ESCAPE")
    raw = source.read_bytes()
    if _sha(raw) != digest:
        raise ValueError("CAS_RECEIPT_DIGEST_MISMATCH")
    target = target_root / relative
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("CAS_RECEIPT_TARGET_MISMATCH")
    if not target.exists():
        _write_atomic(target, raw)


def _pin_reviewers(root: Path, mandate: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for label in ("a", "b"):
        config = mandate["automated_reviewers"][f"reviewer_{label}"]
        prompt_path = (root / config["prompt_path"]).resolve()
        if not prompt_path.is_relative_to(root.resolve()):
            raise ValueError("REVIEW_PROMPT_PATH_ESCAPE")
        prompt_sha = _sha(prompt_path.read_bytes())
        if prompt_sha != config["prompt_sha256"]:
            raise ValueError("REVIEW_PROMPT_SHA_MISMATCH")
        parameters = config["deterministic_parameters"]
        if parameters.get("temperature") != 0:
            raise ValueError("REVIEW_PARAMETERS_NOT_DETERMINISTIC")
        result[label] = {
            "identity": config["agent_identity"],
            "model_id": config["model_id"],
            "model_version": config["model_version"],
            "prompt_sha256": prompt_sha,
            "parameters_sha256": _sha(_canonical_file_bytes(parameters).rstrip(b"\n")),
        }
    return result


def materialize_pack(
    root: Path,
    *,
    scan_checkpoints: Path,
    source_checkpoints: Path,
    review_checkpoints: Path,
    decided_at_utc: str,
) -> dict[str, Any]:
    """Génère exactement 315 décisions et la feuille depuis les reçus structurés.

    Cette étape ne donne aucune autorité de publication. Le gate indépendant
    doit ensuite être exécuté depuis un HEAD propre et approuvé.
    """
    import jsonschema
    import yaml

    try:
        decided = datetime.fromisoformat(decided_at_utc.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("DECISION_TIMESTAMP_INVALID") from None
    if decided.tzinfo != timezone.utc or not decided_at_utc.endswith("Z"):
        raise ValueError("DECISION_TIMESTAMP_NOT_UTC")
    packet_path = root / "docs/reports/go_live/student_public_rights_individual_review_packet_20261009.json"
    policy_path = root / "governance/student_public_rights/delegated_review_policy_v1.yml"
    mandate_path = root / "governance/student_public_rights/delegation_abenrhouma_20261009.yml"
    schema_path = root / "governance/student_public_rights/schemas/automated_artifact_review_v1.schema.json"
    scanner_path = root / "scripts/go_live/student_rights_pdf_scan.py"
    packet_bytes, policy_bytes = packet_path.read_bytes(), policy_path.read_bytes()
    mandate_bytes, schema_bytes = mandate_path.read_bytes(), schema_path.read_bytes()
    packet = json.loads(packet_bytes)
    policy, mandate = yaml.safe_load(policy_bytes), yaml.safe_load(mandate_bytes)
    schema = json.loads(schema_bytes)
    if (policy.get("status") != "SEALED_PENDING_FINAL_APPROVAL"
            or mandate.get("status") != "SEALED_PENDING_FINAL_APPROVAL"
            or mandate.get("effective_authority") is not False):
        raise ValueError("POLICY_OR_MANDATE_NOT_SEALED_FOR_FINAL_APPROVAL")
    hashes = {
        "inventory_sha256": _sha(packet_bytes),
        "policy_sha256": _sha(policy_bytes),
        "mandate_sha256": _sha(mandate_bytes),
        "schema_sha256": _sha(schema_bytes),
        "engine_code_sha256": _sha(Path(__file__).read_bytes()),
        "scanner_code_sha256": _sha(scanner_path.read_bytes()),
        "source_checker_code_sha256": _sha(
            (root / "scripts/go_live/student_rights_source_check.py").read_bytes()
        ),
        "reviewer_code_sha256": _sha(
            (root / "scripts/go_live/student_rights_reviewers.py").read_bytes()
        ),
    }
    binding = mandate["source_binding"]
    for name in ("inventory_file_sha256", "policy_sha256", "schema_sha256",
                 "engine_code_sha256", "scanner_code_sha256",
                 "source_checker_code_sha256", "reviewer_code_sha256"):
        expected = hashes["inventory_sha256"] if name == "inventory_file_sha256" else hashes[name]
        if binding.get(name) != expected:
            raise ValueError(f"MANDATE_BINDING_INVALID:{name}")
    reviewers = _pin_reviewers(root, mandate)
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    artifacts = packet["artifacts"]
    if len(artifacts) != 315 or len({a["content_sha256"] for a in artifacts}) != 315:
        raise ValueError("INVENTORY_NOT_315_UNIQUE")
    evidence_dir = root / "docs/reports/go_live/student_rights_evidence"
    prepared: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
    review_receipt_digests: set[str] = set()
    source_receipt_digests: set[str] = set()
    for artifact in artifacts:
        sha = artifact["content_sha256"]
        scan = json.loads((scan_checkpoints / f"{sha}.json").read_bytes())
        source_checkpoint = json.loads((source_checkpoints / f"{sha}.json").read_bytes())
        review = json.loads((review_checkpoints / f"{sha}.json").read_bytes())
        pages = list(range(1, artifact["page_count"] + 1))
        if scan.get("full_document_scan_complete") is not True:
            raise ValueError(f"PDF_SCAN_INCOMPLETE:{sha[:12]}")
        for label in ("a", "b"):
            actual = review.get(f"reviewer_{label}") or {}
            if any(actual.get(key) != value for key, value in reviewers[label].items()):
                raise ValueError(f"REVIEWER_PIN_MISMATCH:{sha[:12]}:{label}")
            if actual.get("complete") is not True or actual.get("pages_covered") != pages:
                raise ValueError(f"REVIEW_INCOMPLETE:{sha[:12]}:{label}")
            if not actual.get("evidence_refs"):
                raise ValueError(f"REVIEW_RECEIPTS_MISSING:{sha[:12]}:{label}")
        record = build_artifact_record(
            artifact, scan, source_checkpoint["rights_check"], review, policy,
            hashes, decided_at_utc=decided_at_utc,
        )
        validation_errors = list(validator.iter_errors(record))
        if validation_errors:
            raise ValueError(f"EVIDENCE_SCHEMA_INVALID:{sha[:12]}:{validation_errors[0].json_path}")
        for label in ("a", "b"):
            review_receipt_digests.update(
                ref[7:] for ref in record[f"reviewer_{label}"]["evidence_refs"]
            )
        for replay in record["candidate_replays"]:
            for label in ("a", "b"):
                review_receipt_digests.update(
                    ref[7:] for ref in replay[f"reviewer_{label}_evidence_refs"]
                )
        if record.get("source_receipt_sha256"):
            source_receipt_digests.add(record["source_receipt_sha256"])
        prepared.append((record, artifact, _canonical_file_bytes(record)))
    entries = [(record, artifact, _sha(raw)) for record, artifact, raw in prepared]
    sheet_bytes = render_decision_sheet(entries)
    index = build_pack_index(
        root, packet_bytes=packet_bytes, records=[row[0] for row in prepared],
        artifact_digests={row[0]["content_sha256"]: _sha(row[2]) for row in prepared},
        decision_sheet_bytes=sheet_bytes, reviewer_pins=reviewers,
        policy_bytes=policy_bytes, mandate_bytes=mandate_bytes, schema_bytes=schema_bytes,
    )
    for digest in sorted(review_receipt_digests):
        copy_cas_receipt(
            review_checkpoints.parent / "receipts", evidence_dir / "receipts", digest,
        )
    for digest in sorted(source_receipt_digests):
        copy_cas_receipt(
            source_checkpoints / "receipts", evidence_dir / "source_receipts", digest,
        )
    for record, _, raw in prepared:
        _write_atomic(evidence_dir / f"{record['content_sha256']}.json", raw)
    index_bytes = _canonical_file_bytes(index)
    _write_atomic(evidence_dir / "index.json", index_bytes)
    _write_atomic(
        root / "docs/reports/go_live/student_public_rights_individual_review_sheet_20261009.tsv",
        sheet_bytes,
    )
    summary = {
        "report_kind": "NEXUS_DELEGATED_STUDENT_RIGHTS_ADJUDICATION_V1",
        "decided_at_utc": decided_at_utc,
        "inventory_count": 315,
        "final_decisions_count": len(prepared),
        "pending_count": 0,
        "population": index["final_population"],
        "inventory_sha256": hashes["inventory_sha256"],
        "policy_sha256": hashes["policy_sha256"],
        "delegation_sha256": hashes["mandate_sha256"],
        "decision_sheet_sha256": _sha(sheet_bytes),
        "evidence_pack_sha256": _sha(index_bytes),
        "verdict": "AWAITING_INDEPENDENT_GATE_AND_FINAL_EXACT_HEAD_AUTHORITY_APPROVAL",
    }
    report_base = root / "docs/reports/go_live/delegated_student_public_rights_adjudication_20261009"
    _write_atomic(report_base.with_suffix(".json"), _canonical_file_bytes(summary))
    markdown = (
        "# Adjudication déléguée des droits étudiants — 9 octobre 2026\n\n"
        "Ce rapport est préparatoire. Il ne vaut ni approbation humaine exacte du HEAD "
        "ni autorisation de publication.\n\n"
        f"- Horodatage UTC : `{decided_at_utc}`\n"
        f"- Décisions finales : `{len(prepared)}/315`, PENDING : `0`\n"
        f"- Population publique recalculée : `{index['final_population']}`\n"
        f"- SHA-256 du registre de preuves : `{_sha(index_bytes)}`\n"
        "- Gate indépendant et approbation abenrhouma exact-HEAD : requis.\n"
    )
    _write_atomic(report_base.with_suffix(".md"), markdown.encode("utf-8"))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--scan-checkpoints", type=Path, required=True)
    parser.add_argument("--source-checkpoints", type=Path, required=True)
    parser.add_argument("--review-checkpoints", type=Path, required=True)
    parser.add_argument("--decided-at-utc", required=True)
    args = parser.parse_args(argv)
    try:
        result = materialize_pack(
            args.root, scan_checkpoints=args.scan_checkpoints,
            source_checkpoints=args.source_checkpoints,
            review_checkpoints=args.review_checkpoints,
            decided_at_utc=args.decided_at_utc,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"verdict": "FAIL_CLOSED", "reason": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def render_decision_sheet(items: list[tuple[dict, dict, str]]) -> bytes:
    """Génère la feuille #300 uniquement à partir des décisions scellées."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(SHEET_COLUMNS)
    for record, packet, evidence_sha in sorted(items, key=lambda row: row[0]["content_sha256"]):
        checks = _mapping(record.get("checks"))
        signals = packet.get("automated_review_signals") or []
        signal_pages = ",".join(
            f"{signal['kind']}:p{signal['page']}" for signal in signals
        ) if signals else "NONE_DETECTED"
        rights_pass = (
            record.get("rights_basis") in SUPPORTED_RIGHTS_BASES
            and _mapping(record.get("reviewer_a")).get("verdict") == "PASS"
        )
        student_pass = (
            _mapping(record.get("reviewer_b")).get("verdict") == "PASS"
            and checks.get("student_suitability_pass") is True
        )
        writer.writerow((
            record["content_sha256"], packet.get("source_release", ""),
            ",".join(sorted({p["collection"] for p in packet.get("placements", [])})),
            packet.get("source_path", ""), packet.get("source_listing_url", ""),
            packet.get("page_count", ""), packet.get("source_pii_status", ""),
            packet.get("source_currentness_disposition", ""), signal_pages,
            str(packet.get("explicit_student_exclusion_signal", False)).lower(),
            "PUBLIC_RIGHTS_CONFIRMED" if rights_pass else "BLOCKED",
            "STUDENT_APPROVED" if student_pass else "STUDENT_BLOCKED",
            "CLEARED_WITH_EVIDENCE" if record.get("third_party_status") == "CLEARED_WITH_EVIDENCE" else "BLOCKED",
            "PASS_WITH_EVIDENCE" if checks.get("pii_gate_pass") is True else "FAIL",
            "PASS_WITH_EVIDENCE" if checks.get("currentness_gate_pass") is True else "FAIL",
            "PASS_WITH_EVIDENCE" if checks.get("revocation_gate_pass") is True else "FAIL",
            record.get("final_disposition", ""), record.get("rights_evidence_uri") or "",
            ",".join(str(page) for page in sorted(record.get("evidence_pages") or [])),
            ",".join(sorted(record.get("reason_codes") or [])), "",
            record.get("decided_at_utc", ""), record.get("decision_executor", ""),
            record.get("delegation_id", ""), evidence_sha,
        ))
    return output.getvalue().encode("utf-8")


def project_page_scans(scan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Projette les preuves du scanner sans masquer une page ou un rendu absent."""
    source_pages = scan.get("pages")
    count = scan.get("page_count")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or not isinstance(source_pages, list)
        or len(source_pages) != count
    ):
        raise ValueError("PDF_SCAN_PAGE_COUNT_MISMATCH")
    result: list[dict[str, Any]] = []
    for number, source in enumerate(source_pages, 1):
        if not isinstance(source, Mapping) or source.get("page_number") != number:
            raise ValueError("PDF_SCAN_PAGE_SEQUENCE_INVALID")
        graphic = any(
            isinstance(source.get(key), int) and source[key] > 0
            for key in ("raster_image_count", "vector_drawing_count", "annotation_count")
        )
        if (
            not _sha256(source.get("text_sha256"))
            or (graphic and (not _sha256(source.get("render_sha256"))
                             or not _sha256(source.get("ocr_sha256"))
                             or source.get("ocr_required") is not True
                             or source.get("ocr_complete") is not True))
        ):
            raise ValueError("PDF_SCAN_PAGE_INCOMPLETE")
        result.append({
            "page_number": number,
            "text_sha256": source["text_sha256"],
            "render_sha256": source.get("render_sha256"),
            "ocr_sha256": source.get("ocr_sha256"),
            "graphics_detected": graphic,
            "render_required": graphic,
            "render_inspected": graphic,
            "annex_page": source.get("annex_page") is True,
            "scan_complete": True,
        })
    return result


def build_artifact_record(
    packet_artifact: Mapping[str, Any],
    pdf_scan: Mapping[str, Any],
    rights_check: Mapping[str, Any],
    dual_review: Mapping[str, Any],
    policy: Mapping[str, Any],
    bindings: Mapping[str, Any],
    *,
    decided_at_utc: str,
) -> dict[str, Any]:
    """Construit une décision individuelle à partir de preuves, sans présomption.

    Les inconnus restent ``None`` ou ``UNVERIFIABLE``. Seuls les modules de
    vérification, puis le gate indépendant, peuvent établir les preuves.
    """
    sha = packet_artifact["content_sha256"]
    if pdf_scan.get("content_sha256") != sha or (
        pdf_scan.get("page_count") != packet_artifact.get("page_count")
    ):
        raise ValueError("PDF_SCAN_IDENTITY_MISMATCH")
    page_scans = project_page_scans(pdf_scan)
    assembly = dual_review.get("text_assembly")
    if (
        dual_review.get("assembly_protocol") != TEXT_ASSEMBLY_PROTOCOL
        or not isinstance(assembly, list)
        or len(assembly) != pdf_scan["page_count"]
        or any(
            not isinstance(page, Mapping)
            or page.get("page_number") != number
            or page.get("assembly_protocol") != TEXT_ASSEMBLY_PROTOCOL
            for number, page in enumerate(assembly, 1)
        )
    ):
        raise ValueError("REVIEW_TEXT_ASSEMBLY_INCOMPLETE")
    source = dict(_mapping(rights_check.get("source_verification")))
    source_uri = source.get("exact_pdf_uri") or packet_artifact["source_listing_url"]
    a = dict(_mapping(dual_review.get("reviewer_a")))
    b = dict(_mapping(dual_review.get("reviewer_b")))
    signals = list(dual_review.get("restriction_signals") or [])
    if sha == CFTR_SHA256 and not any(
        isinstance(signal, Mapping)
        and signal.get("code") == "TEACHER_NON_DISCLOSURE_INSTRUCTION"
        for signal in signals
    ):
        signals.append({"code": "TEACHER_NON_DISCLOSURE_INSTRUCTION", "pages": [3]})
    signal_codes = {signal.get("code") for signal in signals if isinstance(signal, Mapping)}
    full_review = (
        a.get("complete") is True
        and b.get("complete") is True
        and a.get("pages_covered") == list(range(1, pdf_scan["page_count"] + 1))
        and b.get("pages_covered") == list(range(1, pdf_scan["page_count"] + 1))
    )
    rights_basis = rights_check.get("rights_basis", "NONE")
    rights_pages = list(rights_check.get("evidence_pages") or [])
    reviewed_rights_pages = dual_review.get("rights_evidence_pages") or []
    if rights_basis != "NONE" and reviewed_rights_pages:
        rights_pages = sorted(set(rights_pages) | set(reviewed_rights_pages))
    explicit_rights = bool(
        rights_basis in SUPPORTED_RIGHTS_BASES
        and rights_check.get("rights_evidence_uri")
        and rights_check.get("license_or_terms_excerpt_hash")
        and rights_pages
    )
    source_match = (
        source.get("status") == "VERIFIED"
        and source.get("remote_pdf_sha256") == sha
        and source.get("exact_pdf_uri") == source_uri
    )
    pii_status = dual_review.get("pii_status", "UNVERIFIABLE")
    student_status = "PASS" if b.get("verdict") == "PASS" and full_review else "FAIL"
    third_party_status = dual_review.get("third_party_status", "UNVERIFIABLE")

    def restriction(code: str) -> bool | None:
        if code in signal_codes:
            return True
        return False if full_review and a.get("verdict") == "PASS" and b.get("verdict") == "PASS" else None

    checks = {
        "exact_bytes_match": pdf_scan.get("exact_bytes_match") is True,
        "full_document_scan_complete": pdf_scan.get("full_document_scan_complete") is True,
        "annexes_scan_complete": pdf_scan.get("annexes_scan_complete") is True,
        "explicit_rights_basis_present": explicit_rights,
        "reuse_scope_covers_student_retrieval_excerpt": rights_check.get("reuse_scope_covers_student_retrieval_excerpt") is True,
        "source_exact_document_match": source_match,
        "pii_gate_pass": pii_status == "PASS" and full_review,
        "currentness_gate_pass": rights_check.get("currentness_status") == "PASS",
        "revocation_gate_pass": rights_check.get("revocation_status") == "PASS",
        "student_suitability_pass": student_status == "PASS",
        "restrictive_notice_detected": restriction("RESTRICTIVE_NOTICE_DETECTED"),
        "teacher_only_detected": restriction("TEACHER_ONLY_DETECTED"),
        "non_disclosure_instruction_detected": restriction("TEACHER_NON_DISCLOSURE_INSTRUCTION"),
        "unlicensed_third_party_content_detected": restriction("UNLICENSED_THIRD_PARTY_CONTENT"),
    }
    record: dict[str, Any] = {
        "record_kind": "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V1",
        "artifact_id": sha,
        "content_sha256": sha,
        "source_uri": source_uri,
        "page_count": pdf_scan["page_count"],
        "byte_size": pdf_scan["file_size_bytes"],
        "scan_complete": pdf_scan.get("full_document_scan_complete") is True,
        "images_and_annexes_checked": pdf_scan.get("images_and_annexes_checked") is True,
        "page_scans": page_scans,
        "assembly_protocol": TEXT_ASSEMBLY_PROTOCOL,
        "text_assembly": [dict(page) for page in assembly],
        "pdf_scan_evidence": dict(pdf_scan),
        "source_verification": source,
        "source_receipt_sha256": rights_check.get("source_receipt_sha256"),
        "rights_basis": rights_basis,
        "rights_evidence_uri": rights_check.get("rights_evidence_uri"),
        "license_or_terms_excerpt_hash": rights_check.get("license_or_terms_excerpt_hash"),
        "evidence_pages": rights_pages,
        "third_party_status": third_party_status,
        "pii_status": pii_status,
        "currentness_status": rights_check.get("currentness_status", "UNVERIFIABLE"),
        "revocation_status": rights_check.get("revocation_status", "UNVERIFIABLE"),
        "student_suitability": "FAIL" if sha == CFTR_SHA256 else student_status,
        "restriction_signals": signals,
        "checks": checks,
        "reviewer_a": a,
        "reviewer_b": b,
        "candidate_replays": list(dual_review.get("candidate_replays") or []),
        "decision_executor": DECISION_EXECUTOR,
        "delegation_id": DELEGATION_ID,
        "individual_human_review_claimed": False,
        "bindings": {**bindings, "pdf_sha256": sha},
        "decided_at_utc": decided_at_utc,
    }
    verdict = adjudicate_artifact(record, policy)
    record.update(verdict)
    record["reason_codes"] = sorted(set(record["reason_codes"]) | set(
        rights_check.get("reason_codes") or []
    ))
    if record["reason_codes"] and record["final_disposition"] == "APPROVE_PUBLIC":
        record["final_disposition"] = "EXCLUDE"
        record["deterministic_policy_verdict"] = "FAIL"
        record["deterministic_rules_passed"] = []
    return record


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _result(reason_codes: list[str]) -> dict[str, Any]:
    return {
        "deterministic_policy_verdict": "FAIL" if reason_codes else "PASS",
        "deterministic_rules_passed": [] if reason_codes else [*REQUIRED_TRUE, *REQUIRED_FALSE],
        "final_disposition": "EXCLUDE" if reason_codes else "APPROVE_PUBLIC",
        "reason_codes": sorted(set(reason_codes)),
    }


def adjudicate_artifact(
    evidence: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Calcule une disposition conservatrice sur une preuve structurée.

    Le vérificateur indépendant doit ensuite valider le schéma, les empreintes
    des pièces et la provenance des deux revues ; cette fonction ne les invente
    ni ne les récupère sur le réseau.
    """
    if evidence.get("content_sha256") == CFTR_SHA256:
        return {
            **_result(["TEACHER_NON_DISCLOSURE_INSTRUCTION"]),
            "student_suitability": "FAIL",
            "evidence_pages": [3],
        }

    reasons: list[str] = []
    if (
        policy.get("authorized_use") != "student_retrieval_excerpt_only"
        or policy.get("full_pdf_redistribution_allowed") is not False
        or policy.get("answer_generation_allowed") is not False
    ):
        reasons.append("POLICY_SCOPE_INVALID")

    policy_bases = _mapping(policy.get("rights_bases"))
    accepted = policy_bases.get("accepted")
    required_basis = policy.get("approve_public_requires_rights_basis_in")
    if (
        not isinstance(accepted, list)
        or not isinstance(required_basis, list)
        or any(not isinstance(value, str) for value in accepted + required_basis)
        or not set(accepted) <= SUPPORTED_RIGHTS_BASES
        or not set(required_basis) <= set(accepted)
    ):
        reasons.append("POLICY_RIGHTS_BASES_INVALID")
        required_basis = []
    if evidence.get("rights_basis") not in required_basis:
        reasons.append("RIGHTS_BASIS_NOT_ALLOWED")

    checks = _mapping(evidence.get("checks"))
    reasons.extend(key.upper() for key in REQUIRED_TRUE if checks.get(key) is not True)
    reasons.extend(key.upper() for key in REQUIRED_FALSE if checks.get(key) is not False)

    source = _mapping(evidence.get("source_verification"))
    if (
        not _sha256(evidence.get("content_sha256"))
        or evidence.get("artifact_id") != evidence.get("content_sha256")
        or source.get("remote_pdf_sha256") != evidence.get("content_sha256")
        or source.get("exact_pdf_uri") != evidence.get("source_uri")
    ):
        reasons.append("SOURCE_IDENTITY_NOT_PROVEN")
    if not source.get("observed_at_utc") or not source.get("source_last_updated_at_utc"):
        reasons.append("SOURCE_CURRENTNESS_NOT_PROVEN")
    if (
        source.get("status") != "VERIFIED"
        or source.get("terms_uri") != evidence.get("rights_evidence_uri")
        or not _sha256(source.get("terms_sha256"))
        or not source.get("terms_observed_at_utc")
        or not source.get("revocation_evidence_uri")
    ):
        reasons.append("SOURCE_TERMS_OR_REVOCATION_NOT_PROVEN")
    if not _sha256(evidence.get("source_receipt_sha256")):
        reasons.append("SOURCE_RECEIPT_MISSING")
    if evidence.get("third_party_status") != "CLEARED_WITH_EVIDENCE":
        reasons.append("THIRD_PARTY_NOT_CLEARED")
    for key in ("pii_status", "currentness_status", "revocation_status", "student_suitability"):
        if evidence.get(key) != "PASS":
            reasons.append(f"{key.upper()}_NOT_PASS")
    if (
        not evidence.get("rights_evidence_uri")
        or not _sha256(evidence.get("license_or_terms_excerpt_hash"))
        or not isinstance(evidence.get("evidence_pages"), list)
        or not evidence["evidence_pages"]
        or not isinstance(evidence.get("page_count"), int)
        or evidence["page_count"] < 1
        or any(
            not isinstance(page, int) or not 1 <= page <= evidence["page_count"]
            for page in evidence["evidence_pages"]
        )
    ):
        reasons.append("RIGHTS_EVIDENCE_INCOMPLETE")

    reviewers = (_mapping(evidence.get("reviewer_a")), _mapping(evidence.get("reviewer_b")))
    expected_pages = list(range(1, evidence.get("page_count", 0) + 1)) if isinstance(
        evidence.get("page_count"), int
    ) else []
    for label, reviewer in zip(("A", "B"), reviewers, strict=True):
        if reviewer.get("verdict") != "PASS":
            reasons.append(f"REVIEWER_{label}_NOT_PASS")
        if (
            not reviewer.get("identity")
            or not reviewer.get("model_version")
            or not _sha256(reviewer.get("prompt_sha256"))
            or not _sha256(reviewer.get("context_sha256"))
            or not _sha256(reviewer.get("observation_sha256"))
            or reviewer.get("complete") is not True
            or reviewer.get("confidence") != "HIGH"
            or reviewer.get("pages_covered") != expected_pages
        ):
            reasons.append(f"REVIEWER_{label}_EVIDENCE_INCOMPLETE")
    if (
        reviewers[0].get("identity") == reviewers[1].get("identity")
        or reviewers[0].get("context_sha256") == reviewers[1].get("context_sha256")
    ):
        reasons.append("REVIEWS_NOT_INDEPENDENT")
    replays = evidence.get("candidate_replays")
    def replay_refs(row: Mapping[str, Any], label: str) -> list[str] | None:
        refs = row.get(f"reviewer_{label.lower()}_evidence_refs")
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, str) or not ref.startswith("sha256:") or not _sha256(ref[7:])
            for ref in refs
        ):
            return None
        return refs

    if (
        not isinstance(replays, list)
        or len(replays) != 2
        or any(not isinstance(row, Mapping) for row in replays)
        or [row.get("run_index") for row in replays] != [1, 2]
        or [row.get("run_nonce") for row in replays] != [0, 1]
        or any(row.get("candidate_verdict") != "PASS" for row in replays)
        or any(
            row.get("reviewer_a_observation_sha256") != reviewers[0].get("observation_sha256")
            or row.get("reviewer_b_observation_sha256") != reviewers[1].get("observation_sha256")
            for row in replays
        )
        or any(
            replay_refs(row, label) is None
            or not _sha256(row.get(f"reviewer_{label.lower()}_context_sha256"))
            for row in replays for label in ("A", "B")
        )
        or any(
            replays[0].get(f"reviewer_{label}_context_sha256")
            != reviewers[index].get("context_sha256")
            or replays[0].get(f"reviewer_{label}_evidence_refs")
            != reviewers[index].get("evidence_refs")
            or replays[1].get(f"reviewer_{label}_context_sha256")
            == replays[0].get(f"reviewer_{label}_context_sha256")
            or bool(set(replays[1].get(f"reviewer_{label}_evidence_refs") or [])
                    & set(replays[0].get(f"reviewer_{label}_evidence_refs") or []))
            for index, label in enumerate(("a", "b"))
        )
    ):
        reasons.append("CANDIDATE_REPLAY_DIVERGENCE")
    return _result(reasons)


if __name__ == "__main__":
    sys.exit(main())
