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
DERIVATIVE_SHEET_COLUMNS = SHEET_COLUMNS + (
    "source_disposition", "derivative_disposition", "derivative_content_sha256",
    "derivative_receipt_sha256", "rights_authority_id", "rights_authority_sha256",
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
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--review-checkpoints", type=Path)
    input_group.add_argument("--derivative-checkpoints", type=Path)
    parser.add_argument("--private-candidate-root", type=Path)
    parser.add_argument("--decided-at-utc", required=True)
    args = parser.parse_args(argv)
    try:
        if args.derivative_checkpoints is not None:
            if args.private_candidate_root is None:
                raise ValueError("PRIVATE_CANDIDATE_ROOT_REQUIRED")
            result = materialize_derivative_pack(
                args.root, scan_checkpoints=args.scan_checkpoints,
                source_checkpoints=args.source_checkpoints,
                derivative_checkpoints=args.derivative_checkpoints,
                private_candidate_root=args.private_candidate_root,
                decided_at_utc=args.decided_at_utc,
            )
        else:
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


def render_derivative_decision_sheet(items: list[tuple[dict, dict, str]]) -> bytes:
    """Feuille 315 PDF : la colonne historique est un alias de la source privée."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(DERIVATIVE_SHEET_COLUMNS)
    for record, packet, evidence_sha in sorted(items, key=lambda item: item[0]["content_sha256"]):
        source_disposition = record.get("source_disposition")
        derivative_disposition = record.get("derivative_disposition")
        if (source_disposition not in {"EXCLUDE", "REPLACE_WITH_NEW_CONTENT"}
                or derivative_disposition not in {"EXCLUDE", "APPROVE_PUBLIC"}
                or record.get("final_disposition") != source_disposition):
            raise ValueError("SHEET_SOURCE_DERIVATIVE_DISPOSITION_INVALID")
        positive = (source_disposition == "REPLACE_WITH_NEW_CONTENT"
                    and derivative_disposition == "APPROVE_PUBLIC")
        signals = packet.get("automated_review_signals") or []
        signal_pages = ",".join(
            f"{signal['kind']}:p{signal['page']}" for signal in signals
        ) if signals else "NONE_DETECTED"
        evidence_ref = (
            "https://eduscol.education.gouv.fr/4656/mentions-legales"
            if record.get("rights_authority_id") == "EDUSCOL_ETALAB_2_0_SITEWIDE"
            else ""
        )
        writer.writerow((
            record["content_sha256"], packet.get("source_release", ""),
            ",".join(sorted({p["collection"] for p in packet.get("placements", [])})),
            packet.get("source_path", ""), packet.get("source_listing_url", ""),
            packet.get("page_count", ""), packet.get("source_pii_status", ""),
            packet.get("source_currentness_disposition", ""), signal_pages,
            str(packet.get("explicit_student_exclusion_signal", False)).lower(),
            "PUBLIC_DERIVATIVE_RIGHTS_CONFIRMED" if positive else "BLOCKED",
            "STUDENT_DERIVATIVE_APPROVED" if positive else "STUDENT_BLOCKED",
            "CLEARED_WITH_EVIDENCE" if positive else "BLOCKED",
            "PASS_WITH_EVIDENCE" if positive else "FAIL",
            "PASS_WITH_EVIDENCE" if positive else "FAIL",
            "PASS_WITH_EVIDENCE" if positive else "FAIL",
            source_disposition, evidence_ref,
            ",".join(str(page) for page in sorted(record.get("evidence_pages") or [])),
            ",".join(sorted(record.get("reason_codes") or [])), "",
            record.get("decided_at_utc", ""), record.get("decision_executor", ""),
            record.get("delegation_id", ""), evidence_sha,
            source_disposition, derivative_disposition,
            record.get("derivative_content_sha256") or "",
            record.get("derivative_receipt_sha256") or "",
            record.get("rights_authority_id") or "NONE",
            record.get("rights_authority_sha256") or "NONE",
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


def adjudicate_derivative_candidate(
    packet_artifact: Mapping[str, Any],
    pdf_scan: Mapping[str, Any],
    provenance_checkpoint: Mapping[str, Any],
    derivative_receipt: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    authority_sha256: str,
) -> dict[str, Any]:
    """Décide sur un PDF *source* et son dérivé, sans autoriser la publication.

    Les reçus sont des observations structurées. Le gate indépendant doit
    relire leurs octets, recalculer les blocs depuis le PDF et vérifier les
    signatures/digests avant qu'une décision candidate soit opposable.
    """
    sha = packet_artifact.get("content_sha256")
    if sha == CFTR_SHA256:
        return {
            "source_disposition": "EXCLUDE",
            "derivative_disposition": "EXCLUDE",
            "final_disposition": "EXCLUDE",
            "replacement": None,
            "reason_codes": ["TEACHER_NON_DISCLOSURE_INSTRUCTION"],
        }

    reasons: list[str] = []
    if (policy.get("authorized_use") != "student_retrieval_excerpt_only"
            or policy.get("full_pdf_redistribution_allowed") is not False
            or policy.get("answer_generation_allowed") is not False):
        reasons.append("POLICY_SCOPE_INVALID")
    if (not _sha256(sha)
            or pdf_scan.get("content_sha256") != sha
            or pdf_scan.get("page_count") != packet_artifact.get("page_count")
            or pdf_scan.get("exact_bytes_match") is not True
            or pdf_scan.get("full_document_scan_complete") is not True
            or pdf_scan.get("annexes_scan_complete") is not True):
        reasons.append("SOURCE_SCAN_NOT_PROVEN")
    if (packet_artifact.get("source_pii_status") != "CLEARED"
            or packet_artifact.get("explicit_student_exclusion_signal") is not False):
        reasons.append("SOURCE_STUDENT_SAFETY_NOT_CLEARED")

    source = _mapping(provenance_checkpoint.get("source_provenance"))
    status = source.get("status")
    accepted_status = status in {"EXACT_CURRENT_SOURCE", "HISTORICAL_OFFICIAL_SNAPSHOT"}
    if (provenance_checkpoint.get("kind")
            != "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1"
            or provenance_checkpoint.get("content_sha256") != sha
            or not accepted_status):
        reasons.append("SOURCE_PROVENANCE_NOT_PROVEN")
    if status == "EXACT_CURRENT_SOURCE":
        fetched = _mapping(source.get("pdf_fetch"))
        if (fetched.get("http_status") != 200
                or fetched.get("content_sha256") != sha
                or not fetched.get("final_url")):
            reasons.append("SOURCE_CURRENT_PDF_NOT_EXACT")
    elif status == "HISTORICAL_OFFICIAL_SNAPSHOT":
        historical = _mapping(source.get("historical_capture"))
        if historical.get("content_sha256") != sha or not historical.get("official_download_uri"):
            reasons.append("SOURCE_HISTORICAL_SNAPSHOT_NOT_EXACT")
    if (source.get("currentness_status") != "PASS"
            or not _mapping(source.get("currentness_evidence_ref"))
            or not isinstance(source.get("currentness_observed_at_utc"), str)
            or not source["currentness_observed_at_utc"].endswith("Z")
            or source.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
            or not _mapping(source.get("revocation_evidence_ref"))
            or not isinstance(source.get("revocation_observed_at_utc"), str)
            or not source["revocation_observed_at_utc"].endswith("Z")):
        reasons.append("SOURCE_CURRENTNESS_OR_REVOCATION_NOT_PROVEN")

    proof_kind = provenance_checkpoint.get("rights_basis_kind")
    proof_kinds = _mapping(policy.get("rights_authorities")).get("accepted_proof_kinds")
    if not isinstance(proof_kinds, list) or proof_kind not in proof_kinds:
        reasons.append("RIGHTS_BASIS_NOT_ALLOWED")
    if proof_kind == "INDIVIDUAL_EXPLICIT_LICENCE":
        # A licence individuelle exige un reçu distinct lié aux octets exacts.
        # Aucun format positif de ce type n'est encore produit par ce lot.
        reasons.append("INDIVIDUAL_LICENCE_RECEIPT_MISSING")
    if proof_kind == "SITEWIDE_DOWNLOAD_AUTHORITY" and (
        not _sha256(authority_sha256)
        or provenance_checkpoint.get("authority_yaml_sha256") != authority_sha256
        or provenance_checkpoint.get("rights_basis_status")
        != "CANDIDATE_PENDING_FINAL_APPROVAL"
    ):
        reasons.append("SITEWIDE_AUTHORITY_NOT_BOUND")
    updated = _mapping(source.get("source_updated_at"))
    allowed_dates = _mapping(policy.get("attribution")).get("accepted_date_evidence_kinds")
    if (not isinstance(allowed_dates, list)
            or updated.get("kind") not in allowed_dates
            or not isinstance(updated.get("date"), str)
            or not updated.get("date")
            or not _mapping(updated.get("evidence_ref"))):
        reasons.append("ATTRIBUTION_DATE_NOT_PROVEN")

    derivative_sha = derivative_receipt.get("derivative_content_sha256")
    if (derivative_receipt.get("kind") != "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
            or derivative_receipt.get("source_content_sha256") != sha
            or derivative_receipt.get("source_page_count") != packet_artifact.get("page_count")
            or derivative_receipt.get("status") != "PREPARED_PRIVATE"
            or derivative_receipt.get("publication_authorized") is not False
            or not _sha256(derivative_sha) or derivative_sha == sha
            or derivative_receipt.get("derivative_media_type") != "text/plain"
            or derivative_receipt.get("derivative_encoding") != "utf-8"
            or type(derivative_receipt.get("derivative_byte_count")) is not int
            or derivative_receipt["derivative_byte_count"] < 1):
        reasons.append("DERIVATIVE_IDENTITY_OR_MEDIA_INVALID")
    if (derivative_receipt.get("ocr_used") is not False
            or derivative_receipt.get("images_copied") is not False
            or derivative_receipt.get("graphic_renders_copied") is not False
            or derivative_receipt.get("all_source_pages_inspected") is not True):
        reasons.append("DERIVATIVE_GRAPHIC_OR_SCAN_INVALID")
    attribution = _mapping(derivative_receipt.get("source_attribution"))
    required_attribution = (
        "source_uri", "source_label", "source_updated_at", "source_date_kind", "licensor",
        "licence_id", "derivative_notice",
    )
    if (any(not isinstance(attribution.get(key), str) or not attribution[key].strip()
            for key in required_attribution)
            or attribution.get("source_updated_at") != updated.get("date")
            or attribution.get("source_date_kind") != updated.get("kind")
            or attribution.get("licence_id") != "ETALAB-2.0"
            or attribution.get("licensor") != _mapping(policy.get("attribution")).get(
                "licensor_display")):
        reasons.append("DERIVATIVE_ATTRIBUTION_INCOMPLETE")
    if updated.get("kind") == "DATED_OFFICIAL_SNAPSHOT":
        snapshot_time = (
            _mapping(source.get("pdf_fetch")).get("observed_at_utc")
            if status == "EXACT_CURRENT_SOURCE"
            else _mapping(source.get("historical_capture")).get("observed_at_utc")
        )
        if (updated.get("date") != snapshot_time
                or "snapshot" not in str(attribution.get("derivative_notice", "")).lower()):
            reasons.append("SNAPSHOT_ATTRIBUTION_NOT_LABELLED")
    if status == "EXACT_CURRENT_SOURCE" and attribution.get("source_uri") != _mapping(
            source.get("pdf_fetch")).get("final_url"):
        reasons.append("DERIVATIVE_SOURCE_URL_MISMATCH")

    publisher = _mapping(derivative_receipt.get("publisher_proof"))
    text_policy = _mapping(policy.get("text_derivative"))
    accepted_publisher_kinds = text_policy.get("accepted_publisher_proof_kinds")
    if (text_policy.get("positive_ministry_author_or_publisher_proof_required") is not True
            or not isinstance(accepted_publisher_kinds, list)
            or derivative_receipt.get("publisher_status") != "PASS"
            or publisher.get("status") != "PASS"
            or publisher.get("kind") not in accepted_publisher_kinds):
        reasons.append("MINISTRY_PUBLISHER_NOT_PROVEN")
    elif publisher.get("kind") == "OFFICIAL_CAPTURED_DOWNLOAD_PUBLISHER":
        if (publisher.get("listing_capture_receipt_sha256")
                != source.get("listing_capture_receipt_sha256")
                or not _sha256(publisher.get("listing_capture_receipt_sha256"))
                or publisher.get("source_provenance_checkpoint_sha256")
                != provenance_checkpoint.get("checkpoint_sha256")
                or publisher.get("rights_authority_sha256") != authority_sha256
                or publisher.get("source_content_sha256") != sha
                or publisher.get("matched_anchor_href")
                != _mapping(source.get("matched_anchor")).get("href")
                or publisher.get("source_pdf_url")
                != _mapping(source.get("pdf_fetch")).get("final_url")):
            reasons.append("CAPTURED_PUBLISHER_PROOF_MISMATCH")
    elif publisher.get("kind") == "OFFICIAL_PDF_AUTHOR_METADATA":
        if (publisher.get("metadata_field") != "author"
                or not _sha256(publisher.get("normalized_value_sha256"))):
            reasons.append("PDF_AUTHOR_PROOF_INVALID")
    elif publisher.get("kind") == "EXPLICIT_DOCUMENT_IMPRINT":
        if (type(publisher.get("page_number")) is not int
                or not 1 <= publisher["page_number"] <= packet_artifact.get("page_count", 0)
                or type(publisher.get("block_index")) is not int
                or publisher["block_index"] < 0
                or not _sha256(publisher.get("normalized_text_sha256"))):
            reasons.append("PDF_IMPRINT_PROOF_INVALID")

    pages = derivative_receipt.get("pages")
    expected_pages = packet_artifact.get("page_count")
    if (not isinstance(pages, list)
            or type(expected_pages) is not int
            or len(pages) != expected_pages
            or any(not isinstance(page, Mapping) for page in pages)
            or [page.get("page_number") for page in pages if isinstance(page, Mapping)]
            != list(range(1, expected_pages + 1))):
        reasons.append("DERIVATIVE_PAGE_COVERAGE_INVALID")
    else:
        selected_total = 0
        for page in pages:
            blocks = page.get("all_blocks")
            selected = page.get("selected_block_indices")
            if not isinstance(blocks, list) or not isinstance(selected, list):
                reasons.append("DERIVATIVE_BLOCK_MAP_INVALID")
                continue
            by_index = {block.get("block_index"): block for block in blocks
                        if isinstance(block, Mapping)}
            if len(by_index) != len(blocks) or len(set(selected)) != len(selected):
                reasons.append("DERIVATIVE_BLOCK_MAP_INVALID")
                continue
            for index in selected:
                block = _mapping(by_index.get(index))
                expected_citation = {
                    **attribution, "source_page": page["page_number"],
                    "source_pdf_sha256": sha,
                }
                if (block.get("block_type") != 0
                        or block.get("block_class") != "SAFE_TEXT_CANDIDATE"
                        or block.get("citation") != expected_citation):
                    reasons.append("EXCLUDED_BLOCK_INCLUDED")
                selected_total += 1
        if selected_total == 0:
            reasons.append("DERIVATIVE_EMPTY")

    if reasons:
        return {
            "source_disposition": "EXCLUDE",
            "derivative_disposition": "EXCLUDE",
            "final_disposition": "EXCLUDE",
            "replacement": None,
            "reason_codes": sorted(set(reasons)),
        }
    return {
        "source_disposition": "REPLACE_WITH_NEW_CONTENT",
        "derivative_disposition": "APPROVE_PUBLIC",
        "final_disposition": "REPLACE_WITH_NEW_CONTENT",
        "replacement": {"new_content_sha256": derivative_sha},
        "reason_codes": [],
    }


def build_derivative_artifact_record(
    packet_artifact: Mapping[str, Any],
    pdf_scan: Mapping[str, Any],
    provenance_checkpoint: Mapping[str, Any],
    derivative_receipt: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    source_checkpoint_sha256: str,
    derivative_receipt_sha256: str | None,
    authority_sha256: str,
    bindings: Mapping[str, Any],
    decided_at_utc: str,
) -> dict[str, Any]:
    """Projette la décision V2 : le SHA source PDF n'est jamais public."""
    sha = packet_artifact.get("content_sha256")
    if not _sha256(sha) or pdf_scan.get("content_sha256") != sha:
        raise ValueError("SOURCE_SCAN_IDENTITY_MISMATCH")
    verdict = adjudicate_derivative_candidate(
        packet_artifact, pdf_scan, provenance_checkpoint, derivative_receipt,
        policy, authority_sha256=authority_sha256,
    )
    attribution = _mapping(derivative_receipt.get("source_attribution"))
    selected_pages = [
        page.get("page_number") for page in derivative_receipt.get("pages", [])
        if isinstance(page, Mapping) and page.get("selected_block_indices")
    ] if isinstance(derivative_receipt.get("pages"), list) else []
    rights_basis = provenance_checkpoint.get("rights_basis_kind")
    if rights_basis not in {"SITEWIDE_DOWNLOAD_AUTHORITY", "INDIVIDUAL_EXPLICIT_LICENCE"}:
        rights_basis = "NONE"
    return {
        "record_kind": "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V2",
        "artifact_id": sha,
        "content_sha256": sha,
        "source_uri": attribution.get("source_uri") or packet_artifact.get("source_listing_url"),
        "page_count": pdf_scan.get("page_count"),
        "byte_size": pdf_scan.get("file_size_bytes"),
        "scan_complete": pdf_scan.get("full_document_scan_complete") is True,
        "images_and_annexes_checked": pdf_scan.get("images_and_annexes_checked") is True,
        "page_scans": project_page_scans(pdf_scan),
        "pdf_scan_evidence": dict(pdf_scan),
        "source_receipt_sha256": source_checkpoint_sha256,
        "rights_basis": rights_basis,
        "rights_authority_id": (
            "EDUSCOL_ETALAB_2_0_SITEWIDE"
            if rights_basis == "SITEWIDE_DOWNLOAD_AUTHORITY" else None
        ),
        "rights_authority_sha256": (
            authority_sha256 if rights_basis == "SITEWIDE_DOWNLOAD_AUTHORITY" else None
        ),
        "derivative_receipt_sha256": derivative_receipt_sha256,
        "derivative_content_sha256": derivative_receipt.get("derivative_content_sha256"),
        "student_suitability": (
            "FAIL" if sha == CFTR_SHA256 else
            "PASS" if verdict["derivative_disposition"] == "APPROVE_PUBLIC"
            else "UNVERIFIABLE"
        ),
        "evidence_pages": [3] if sha == CFTR_SHA256 else selected_pages,
        "decision_executor": DECISION_EXECUTOR,
        "delegation_id": DELEGATION_ID,
        "individual_human_review_claimed": False,
        "bindings": {**bindings, "pdf_sha256": sha},
        "decided_at_utc": decided_at_utc,
        **verdict,
    }


def build_public_derivative_candidate_manifest(
    packet_artifacts: list[Mapping[str, Any]],
    records: list[Mapping[str, Any]],
    provenance_by_source_sha: Mapping[str, Mapping[str, Any]],
    derivative_by_source_sha: Mapping[str, Mapping[str, Any]],
    *,
    inventory_sha256: str,
    authority_sha256: str,
    extraction_policy_sha256: str,
) -> dict[str, Any]:
    """Inventorie uniquement les dérivés candidats, jamais les PDF sources.

    Les comptes de chunks ne sont pas prétendus ici : ils appartiennent à la
    future release successeur et devront être mesurés après son chunking réel.
    """
    if not all(_sha256(value) for value in (
            inventory_sha256, authority_sha256, extraction_policy_sha256)):
        raise ValueError("CANDIDATE_MANIFEST_BINDING_INVALID")
    packets = {row.get("content_sha256"): row for row in packet_artifacts}
    decisions = {row.get("content_sha256"): row for row in records}
    if (len(packets) != len(packet_artifacts)
            or len(decisions) != len(records)
            or set(packets) != set(decisions)
            or not all(_sha256(sha) for sha in packets)):
        raise ValueError("CANDIDATE_MANIFEST_SOURCE_SET_INVALID")
    entries: list[dict[str, Any]] = []
    excluded: list[str] = []
    derivative_shas: set[str] = set()
    collections: set[str] = set()
    placements = 0
    segments = 0
    for sha in sorted(packets):
        packet, record = packets[sha], decisions[sha]
        if record.get("source_disposition") == "EXCLUDE":
            if record.get("derivative_disposition") != "EXCLUDE":
                raise ValueError("CANDIDATE_MANIFEST_DISPOSITION_INVALID")
            excluded.append(sha)
            continue
        if (record.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
                or record.get("derivative_disposition") != "APPROVE_PUBLIC"):
            raise ValueError("CANDIDATE_MANIFEST_DISPOSITION_INVALID")
        derivative = _mapping(derivative_by_source_sha.get(sha))
        provenance = _mapping(provenance_by_source_sha.get(sha))
        derivative_sha = record.get("derivative_content_sha256")
        if (not _sha256(derivative_sha) or derivative_sha == sha
                or derivative_sha in derivative_shas
                or derivative.get("derivative_content_sha256") != derivative_sha
                or not _sha256(record.get("derivative_receipt_sha256"))):
            raise ValueError("CANDIDATE_MANIFEST_DERIVATIVE_INVALID")
        derivative_shas.add(derivative_sha)
        source_placements = packet.get("placements")
        if (not isinstance(source_placements, list) or not source_placements
                or any(not isinstance(row, Mapping)
                       or not isinstance(row.get("collection"), str)
                       or not row["collection"] for row in source_placements)):
            raise ValueError("CANDIDATE_MANIFEST_PLACEMENTS_INVALID")
        placement_collections = sorted({row["collection"] for row in source_placements})
        collections.update(placement_collections)
        placements += len(source_placements)
        pages = derivative.get("pages")
        if not isinstance(pages, list):
            raise ValueError("CANDIDATE_MANIFEST_SEGMENTS_INVALID")
        artifact_segments = sum(
            len(page.get("review_groups", [])) for page in pages
            if isinstance(page, Mapping) and isinstance(page.get("review_groups"), list)
        )
        if artifact_segments < 1:
            raise ValueError("CANDIDATE_MANIFEST_SEGMENTS_INVALID")
        segments += artifact_segments
        attribution = _mapping(derivative.get("source_attribution"))
        date_kind = _mapping(_mapping(
            provenance.get("source_provenance")).get("source_updated_at")
        ).get("kind")
        if not isinstance(date_kind, str) or not date_kind:
            raise ValueError("CANDIDATE_MANIFEST_ATTRIBUTION_DATE_MISSING")
        entries.append({
            "source_content_sha256": sha,
            "derivative_content_sha256": derivative_sha,
            "derivative_receipt_sha256": record["derivative_receipt_sha256"],
            "media_type": "text/plain; charset=utf-8",
            "private_candidate_relpath": f"candidates/{derivative_sha}.txt",
            "collections": placement_collections,
            "citation": {**attribution, "source_date_kind": date_kind},
            "source_disposition": "REPLACE_WITH_NEW_CONTENT",
            "derivative_disposition": "APPROVE_PUBLIC",
        })
    return {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_MANIFEST_V1",
        "status": "PRE_REVIEW_NOT_PROMOTABLE",
        "inventory_sha256": inventory_sha256,
        "rights_authority_sha256": authority_sha256,
        "text_derivative_extraction_policy_sha256": extraction_policy_sha256,
        "entries": entries,
        "excluded_source_sha256": excluded,
        "counts": {
            "source_pdfs": len(packets),
            "public_collections": len(collections),
            "public_derivative_artifacts": len(entries),
            "public_placements": placements,
            "public_derivative_segments": segments,
            "original_pdf_public_count": 0,
        },
    }


def materialize_derivative_pack(
    root: Path,
    *,
    scan_checkpoints: Path,
    source_checkpoints: Path,
    derivative_checkpoints: Path,
    private_candidate_root: Path,
    decided_at_utc: str,
) -> dict[str, Any]:
    """Projette les 315 décisions depuis les reçus gelés, sans publier de PDF.

    Le gate indépendant recalcule les octets, l'applicabilité de la licence et
    les exclusions. Ici, tous les chemins de sortie restent locaux au dépôt.
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
    policy_bytes, mandate_bytes = policy_path.read_bytes(), mandate_path.read_bytes()
    policy, mandate = yaml.safe_load(policy_bytes), yaml.safe_load(mandate_bytes)
    if (policy.get("status") != "SEALED_PENDING_FINAL_APPROVAL"
            or mandate.get("status") != "SEALED_PENDING_FINAL_APPROVAL"
            or mandate.get("effective_authority") is not False):
        raise ValueError("POLICY_OR_MANDATE_NOT_SEALED")
    packet_bytes, schema_bytes = packet_path.read_bytes(), schema_path.read_bytes()
    packet, schema = json.loads(packet_bytes), json.loads(schema_bytes)
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    base = root / "governance/student_public_rights"
    evidence_dir = root / "docs/reports/go_live/student_rights_evidence"
    source_refs, source_counts = source_population_refs(root)
    paths = {
        "engine_code_sha256": Path(__file__),
        "scanner_code_sha256": root / "scripts/go_live/student_rights_pdf_scan.py",
        "source_checker_code_sha256": root / "scripts/go_live/student_rights_source_provenance.py",
        "reviewer_code_sha256": root / "scripts/go_live/student_rights_reviewers.py",
        "derivative_builder_code_sha256": root / "scripts/go_live/student_rights_text_derivative.py",
        "text_derivative_extraction_policy_sha256": base / "text_derivative_extraction_policy_v1.yml",
        "rights_authority_sha256": base / "authorities/eduscol_etalab_2_0_sitewide_20261010.yml",
        "independent_verifier_code_sha256": root / "scripts/go_live/check_delegated_student_rights_gate.py",
    }
    hashes = {
        "inventory_sha256": _sha(packet_bytes),
        "policy_sha256": _sha(policy_bytes),
        "mandate_sha256": _sha(mandate_bytes),
        "schema_sha256": _sha(schema_bytes),
        **{name: _sha(path.read_bytes()) for name, path in paths.items()},
    }
    binding = _mapping(mandate.get("source_binding"))
    binding_names = {"inventory_file_sha256": "inventory_sha256", **{
        key: key for key in hashes if key not in {"inventory_sha256", "mandate_sha256"}
    }}
    for binding_name, hash_name in binding_names.items():
        if binding.get(binding_name) != hashes[hash_name]:
            raise ValueError(f"MANDATE_BINDING_INVALID:{binding_name}")
    artifacts = packet.get("artifacts")
    if (not isinstance(artifacts, list) or len(artifacts) != 315
            or len({row.get("content_sha256") for row in artifacts}) != 315
            or {row["content_sha256"] for row in artifacts} != set(source_counts)):
        raise ValueError("INVENTORY_NOT_315_UNIQUE")
    reviewer_pins = _pin_reviewers(root, mandate)
    prepared: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
    provenance: dict[str, dict[str, Any]] = {}
    derivatives: dict[str, dict[str, Any]] = {}
    for artifact in sorted(artifacts, key=lambda row: row["content_sha256"]):
        sha = artifact["content_sha256"]
        scan = json.loads((scan_checkpoints / f"{sha}.json").read_bytes())
        source_path = source_checkpoints / f"{sha}.json"
        source_raw = source_path.read_bytes()
        source = json.loads(source_raw)
        sidecar = json.loads((derivative_checkpoints / f"{sha}.json").read_bytes())
        receipt_digest = sidecar.get("derivative_receipt_sha256")
        if (sidecar.get("source_content_sha256") != sha
                or not _sha256(receipt_digest)):
            raise ValueError(f"DERIVATIVE_CHECKPOINT_INVALID:{sha[:12]}")
        receipt_path = evidence_dir / "derivative_receipts" / receipt_digest[:2] / f"{receipt_digest}.json"
        receipt_raw = receipt_path.read_bytes()
        if _sha(receipt_raw) != receipt_digest:
            raise ValueError(f"DERIVATIVE_RECEIPT_DIGEST:{sha[:12]}")
        receipt = json.loads(receipt_raw)
        if receipt.get("source_content_sha256") != sha:
            raise ValueError(f"DERIVATIVE_RECEIPT_SOURCE:{sha[:12]}")
        if receipt.get("status") == "PREPARED_PRIVATE":
            candidate = private_candidate_root / str(receipt.get("candidate_relpath"))
            if (not candidate.resolve().is_relative_to(private_candidate_root.resolve())
                    or _sha(candidate.read_bytes()) != receipt.get("derivative_content_sha256")):
                raise ValueError(f"DERIVATIVE_CANDIDATE_DIGEST:{sha[:12]}")
        record = build_derivative_artifact_record(
            artifact, scan, source, receipt, policy,
            source_checkpoint_sha256=_sha(source_raw),
            derivative_receipt_sha256=receipt_digest,
            authority_sha256=hashes["rights_authority_sha256"],
            bindings={
                **{key: value for key, value in hashes.items()
                   if key != "independent_verifier_code_sha256"},
                "pdf_sha256": sha,
            },
            decided_at_utc=decided_at_utc,
        )
        errors = list(validator.iter_errors(record))
        if errors:
            raise ValueError(f"EVIDENCE_SCHEMA_INVALID:{sha[:12]}:{errors[0].json_path}")
        provenance[sha], derivatives[sha] = source, receipt
        prepared.append((record, artifact, _canonical_file_bytes(record)))
    sheet = render_derivative_decision_sheet([
        (record, artifact, _sha(raw)) for record, artifact, raw in prepared
    ])
    manifest = build_public_derivative_candidate_manifest(
        artifacts, [record for record, _, _ in prepared], provenance, derivatives,
        inventory_sha256=hashes["inventory_sha256"],
        authority_sha256=hashes["rights_authority_sha256"],
        extraction_policy_sha256=hashes["text_derivative_extraction_policy_sha256"],
    )
    manifest_bytes = _canonical_file_bytes(manifest)
    candidate_counts = manifest["counts"]
    population = {
        "collections": candidate_counts["public_collections"],
        "artifacts": candidate_counts["public_derivative_artifacts"],
        "placements": candidate_counts["public_placements"],
        "derivative_segments": candidate_counts["public_derivative_segments"],
        "source_pdfs": 315,
        "original_pdf_public_count": 0,
    }
    index = {
        "schema_version": "NEXUS_DELEGATED_STUDENT_RIGHTS_EVIDENCE_INDEX_V2",
        **{key: value for key, value in hashes.items()
           if key != "independent_verifier_code_sha256"},
        "delegation_sha256": hashes["mandate_sha256"],
        "reviewer_a": reviewer_pins["a"],
        "reviewer_b": reviewer_pins["b"],
        "source_population": source_refs,
        "artifacts": {
            record["content_sha256"]: {
                "path": f"{record['content_sha256']}.json",
                "sha256": _sha(raw),
                "source_placement_count": source_counts[record["content_sha256"]]["source_placement_count"],
                "source_chunk_count": source_counts[record["content_sha256"]]["source_chunk_count"],
            }
            for record, _, raw in prepared
        },
        "decision_sheet_sha256": _sha(sheet),
        "public_candidate_manifest_sha256": _sha(manifest_bytes),
        "final_population": population,
    }
    # Écrit seulement après validation de toutes les 315 entrées et des CAS.
    for record, _, raw in prepared:
        _write_atomic(evidence_dir / f"{record['content_sha256']}.json", raw)
    _write_atomic(evidence_dir / "index.json", _canonical_file_bytes(index))
    _write_atomic(evidence_dir / "public_derivative_candidate_manifest_20261010.json", manifest_bytes)
    _write_atomic(
        root / "docs/reports/go_live/student_public_rights_individual_review_sheet_20261009.tsv",
        sheet,
    )
    summary = {
        "report_kind": "NEXUS_DELEGATED_STUDENT_RIGHTS_ADJUDICATION_V2",
        "decided_at_utc": decided_at_utc,
        "inventory_count": 315,
        "source_decision_count": len(prepared),
        "pending_count": 0,
        "population": population,
        "source_dispositions": {
            key: sum(record["source_disposition"] == key for record, _, _ in prepared)
            for key in ("EXCLUDE", "REPLACE_WITH_NEW_CONTENT")
        },
        "inventory_sha256": hashes["inventory_sha256"],
        "rights_authority_sha256": hashes["rights_authority_sha256"],
        "policy_sha256": hashes["policy_sha256"],
        "delegation_sha256": hashes["mandate_sha256"],
        "decision_sheet_sha256": _sha(sheet),
        "evidence_pack_sha256": _sha(_canonical_file_bytes(index)),
        "verdict": "AWAITING_INDEPENDENT_GATE_AND_FINAL_EXACT_HEAD_AUTHORITY_APPROVAL",
    }
    report_base = root / "docs/reports/go_live/delegated_student_public_rights_adjudication_20261010"
    _write_atomic(report_base.with_suffix(".json"), _canonical_file_bytes(summary))
    markdown = (
        "# Adjudication déléguée — dérivés textuels Éduscol, 10 octobre 2026\n\n"
        "Ce pack candidat n'autorise aucune publication ni déploiement. Les PDF sources restent internes.\n\n"
        f"- Horodatage UTC : `{decided_at_utc}`\n"
        f"- Sources décidées : `{len(prepared)}/315`, PENDING : `0`\n"
        f"- Dérivés textuels candidats : `{population['artifacts']}` dans "
        f"`{population['collections']}` collections ; segments : `{population['derivative_segments']}`\n"
        f"- Sources exclues : `{summary['source_dispositions']['EXCLUDE']}`\n"
        f"- SHA-256 du registre de preuves : `{summary['evidence_pack_sha256']}`\n"
        "- Gate indépendant et approbation exact-HEAD d'abenrhouma : requis.\n"
    )
    _write_atomic(report_base.with_suffix(".md"), markdown.encode("utf-8"))
    return summary


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
