#!/usr/bin/env python3
"""Vérifier les preuves PII/actualité du successeur puis générer son inclusion.

Ce contrôle ne promeut aucun manifeste et ne transfère aucun octet privé.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from build_student_public_successor_release import load_sources
from prepare_student_public_candidate_inventory import canonical, digest

SHA = re.compile(r"[0-9a-f]{64}\Z")
PII_KIND = "NEXUS_STUDENT_DERIVATIVE_PII_ADJUDICATION_V1"
CURRENT_KIND = "NEXUS_STUDENT_DERIVATIVE_SOURCE_CURRENTNESS_ATTESTATION_V1"
INCLUSION_KIND = "NEXUS_STUDENT_PUBLIC_DERIVATIVE_INCLUSIONS_V2"
EVIDENCE = Path("docs/reports/go_live/student_rights_evidence")
PACKET = Path("docs/reports/go_live/student_public_rights_individual_review_packet_20261009.json")
PATTERN = Path("docs/reports/go_live/student_derivative_pii_pattern_screen_20261010.json")
POLICY = Path("governance/student_public_rights/derivative_pii_adjudication_policy_v1.yml")
RIGHTS_AUTHORITY = Path(
    "governance/student_public_rights/authorities/eduscol_etalab_2_0_sitewide_20261010.yml"
)
CAS_KIND = "NEXUS_STUDENT_DERIVATIVE_PRIVATE_EVIDENCE_CAS_V1"
FRESHNESS_TTL = timedelta(hours=24)
CAPTURE_WINDOW = timedelta(hours=1)
LISTING_BODIES = (
    ("normalized_html", ".normalized.html"),
    ("extracted_text", ".extracted.txt"),
    ("screenshot", ".png"),
)


def _json(raw: bytes, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical(value) != raw:
        raise ValueError(f"{label} canonical JSON differs")
    return value


def _row_digest(row: dict[str, Any]) -> bool:
    unsigned = {key: value for key, value in row.items() if key != "evidence_sha256"}
    return row.get("evidence_sha256") == digest(canonical(unsigned))


def _compact(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_join(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("private evidence path escapes root")
    return path


def _sha_field(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def check_capture_timing(
    checked_at: datetime, listing_at: datetime, fetch_at: datetime,
    current_at: datetime, revocation_at: datetime, *, as_of: datetime,
) -> datetime:
    """Borner chaque capture réelle, pas seulement l'heure d'un index réécrit."""
    observations = (listing_at, fetch_at, current_at, revocation_at)
    if (any(value.tzinfo is None for value in (checked_at, as_of, *observations))
            or not checked_at <= as_of
            or any(not checked_at - CAPTURE_WINDOW <= value <= checked_at
                   or not as_of - value < FRESHNESS_TTL for value in observations)
            or current_at != fetch_at or revocation_at != listing_at):
        raise ValueError("source capture timing differs or expired")
    return min(observations) + FRESHNESS_TTL


def listing_body_paths(
    receipt: dict[str, Any], receipt_sha: str, listing_root: Path, *, prefix: str,
) -> dict[Path, Path]:
    """Copier les trois corps exacts que le reçu Chromium référence."""
    if not _sha_field(receipt_sha) or not re.fullmatch(r"[0-9a-f]{16}", prefix):
        raise ValueError("listing body identity differs")
    result: dict[Path, Path] = {}
    for name, suffix in LISTING_BODIES:
        filename = f"{prefix}{suffix}"
        sha = receipt.get(f"{name}_sha256")
        path = listing_root / filename
        if (receipt.get(f"{name}_file") != filename or not _sha_field(sha)
                or digest(path.read_bytes()) != sha):
            raise ValueError(f"listing body digest differs: {name}")
        result[Path("fresh_listing_bodies") / receipt_sha / filename] = path
    return result


def _indexed(rows: object, key: str, expected: set[str], label: str) -> dict[str, dict]:
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError(f"{label} population differs")
    by_key: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str):
            raise ValueError(f"{label} row malformed")
        value = row[key]
        if value in by_key or not _row_digest(row):
            raise ValueError(f"{label} row digest or uniqueness differs")
        by_key[value] = row
    if set(by_key) != expected:
        raise ValueError(f"{label} exact population differs")
    return by_key


def verify_report_pair(
    source: dict[str, Any], pii_raw: bytes, current_raw: bytes,
    *, as_of: datetime | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Refuser tout screen partiel, statut faux ou identité hors candidat."""
    pii = _json(pii_raw, "PII adjudication")
    current = _json(current_raw, "source currentness")
    inputs = source["inputs"]
    artifacts = inputs["artifacts"]["artifacts"]
    expected = {item["content_sha256"] for item in artifacts}
    if len(expected) != len(artifacts):
        raise ValueError("candidate derivative duplicates")
    candidate_sha = inputs["candidate_manifest_sha256"]
    checked_at = _utc(current.get("fresh_source_checked_at_utc"))
    attested_at = _utc(current.get("attested_at_utc"))
    now = as_of or datetime.now(timezone.utc)
    if (checked_at is None or attested_at is None
            or now.tzinfo is None or not checked_at <= attested_at <= now
            or now - checked_at > FRESHNESS_TTL):
        raise ValueError("source currentness receipt expired or time invalid")
    if (pii.get("kind") != PII_KIND
            or pii.get("pii_decision_scope")
            != "DETERMINISTIC_FULL_DERIVATIVE_TEXT_AND_SOURCE_REVIEW"
            or pii.get("currentness_revocation_status") != "UNPROVEN_FOR_SUCCESSOR"
            or pii.get("candidate_manifest_sha256") != candidate_sha
            or pii.get("artifact_registry_sha256")
            != inputs["artifact_registry_sha256"]
            or current.get("kind") != CURRENT_KIND
            or current.get("candidate_manifest_sha256") != candidate_sha
            or current.get("successor_release_binding") != "NOT_YET_SEALED"
            or any(report.get("decision_count") != len(expected)
                   or report.get("status_counts") != {"PASS": len(expected)}
                   for report in (pii, current))
            or any(not isinstance(report.get(field), str)
                   or SHA.fullmatch(report[field]) is None
                   for report, field in (
                       (pii, "policy_sha256"),
                       (current, "fresh_source_index_file_sha256"),
                       (current, "fresh_source_index_logical_sha256"),
                   ))):
        raise ValueError("full PII/currentness report authority differs")
    pii_rows = _indexed(pii.get("rows"), "derivative_content_sha256", expected, "PII")
    current_rows = _indexed(current.get("rows"), "derivative_content_sha256", expected,
                            "currentness")
    pairs = []
    for artifact in sorted(artifacts, key=lambda item: item["content_sha256"]):
        sha = artifact["content_sha256"]
        p, c = pii_rows[sha], current_rows[sha]
        source_sha = artifact["source_pdf_sha256"]
        receipt_sha = artifact["derivative_receipt_sha256"]
        if (p.get("decision_kind") != "NEXUS_STUDENT_DERIVATIVE_PII_DECISION_V1"
                or p.get("pii_scan_scope") != "FULL_DERIVATIVE_TEXT"
                or p.get("pii_status") != "PASS" or p.get("reason_codes") != []
                or c.get("status") != "PASS" or c.get("reason_codes") != []
                or any(row.get("source_pdf_sha256") != source_sha
                       or row.get("derivative_receipt_sha256") != receipt_sha
                       for row in (p, c))
                or c.get("source_uri") != artifact["citation"]["source_uri"]
                or p.get("policy_sha256") != pii["policy_sha256"]
                or type(p.get("text_byte_count")) is not int
                or p["text_byte_count"] <= 0
                or any(not isinstance(c.get(field), str)
                       or SHA.fullmatch(c[field]) is None
                       for field in (
                           "fresh_source_checkpoint_file_sha256",
                           "fresh_source_checkpoint_sha256",
                           "fresh_listing_receipt_sha256",
                           "fresh_pdf_fetch_receipt_sha256",
                       ))):
            raise ValueError(f"derivative report evidence differs: {sha}")
        pairs.append((artifact, p, c))
    return pairs


def make_inclusion(
    source: dict[str, Any], pii_raw: bytes, current_raw: bytes,
    rows: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    *, private_cas_manifest_sha256: str, source_currentness_valid_until: datetime,
) -> dict[str, Any]:
    """Sérialisation déterministe ; appeler seulement après preuves privées vérifiées."""
    _json(pii_raw, "PII adjudication")
    current = _json(current_raw, "source currentness")
    if len(rows) != len(source["inputs"]["artifacts"]["artifacts"]):
        raise ValueError("verified inclusion population differs")
    if (not _sha_field(private_cas_manifest_sha256)
            or source_currentness_valid_until.tzinfo is None):
        raise ValueError("private CAS manifest digest required")
    decisions = []
    for artifact, p, c in rows:
        proof = {
            "pii_evidence_sha256": p["evidence_sha256"],
            "currentness_evidence_sha256": c["evidence_sha256"],
            "fresh_source_checkpoint_file_sha256": c["fresh_source_checkpoint_file_sha256"],
        }
        decisions.append({
            "content_sha256": artifact["content_sha256"],
            "source_pdf_sha256": artifact["source_pdf_sha256"],
            "disposition": "INCLUDE",
            **proof,
            "evidence_sha256": digest(canonical(proof)),
        })
    decisions.sort(key=lambda row: row["content_sha256"])
    return {
        "kind": INCLUSION_KIND,
        "source_candidate_manifest_sha256": source["inputs"]["candidate_manifest_sha256"],
        "rights_authority_sha256": source["inputs"]["release"]["authorities"][
            "rights_authority_sha256"],
        "source_candidate_inventory_sha256": digest(canonical(source["inventory"])),
        "pii_adjudication_report_sha256": digest(pii_raw),
        "source_currentness_attestation_sha256": digest(current_raw),
        "fresh_source_index_file_sha256": current["fresh_source_index_file_sha256"],
        "fresh_source_index_logical_sha256": current["fresh_source_index_logical_sha256"],
        "source_currentness_valid_until_utc": source_currentness_valid_until.isoformat(
        ).replace("+00:00", "Z"),
        "private_cas_manifest_sha256": private_cas_manifest_sha256,
        "decision_count": len(decisions),
        "evidence_pack_sha256": digest(canonical(decisions)),
        "decisions": decisions,
    }


def _source_map(
    source: dict[str, Any], root: Path, pii_path: Path, current_path: Path,
    fresh_root: Path, derivative_root: Path, source_pdf_root: Path,
    old_checkpoint_root: Path,
) -> dict[Path, Path]:
    """Inventorier les octets exacts, hors Git, avant copie dans le CAS privé."""
    evidence = root / EVIDENCE
    pii_raw, current_raw = pii_path.read_bytes(), current_path.read_bytes()
    pairs = verify_report_pair(source, pii_raw, current_raw)
    pii, current = _json(pii_raw, "PII adjudication"), _json(current_raw, "source currentness")
    fixed = {
        Path("reports/pii_adjudication.json"): pii_path,
        Path("reports/source_currentness.json"): current_path,
        Path("reports/pattern_screen.json"): root / PATTERN,
        Path("authority/pii_policy.yml"): root / POLICY,
        Path("authority/eduscol_sitewide_rights.yml"): root / RIGHTS_AUTHORITY,
        Path("authority/source_packet.json"): root / PACKET,
        Path("authority/pr300_evidence_index.json"): evidence / "index.json",
        Path("authority/old_provenance_index.json"): evidence / "provenance/index.json",
        Path("authority/candidate_manifest.json"):
            evidence / "public_derivative_candidate_manifest_20261010.json",
        Path("authority/fresh_source_index.json"): fresh_root / "index.json",
    }
    observed = {name: path.read_bytes() for name, path in fixed.items()}
    if (digest(observed[Path("reports/pattern_screen.json")])
            != pii.get("pattern_screen_sha256")
            or digest(observed[Path("authority/pii_policy.yml")]) != pii["policy_sha256"]
            or digest(observed[Path("authority/eduscol_sitewide_rights.yml")])
            != source["inputs"]["release"]["authorities"]["rights_authority_sha256"]
            or digest(observed[Path("authority/source_packet.json")])
            != pii.get("source_inventory_packet_sha256")
            or digest(observed[Path("authority/pr300_evidence_index.json")])
            != pii.get("pr300_evidence_index_sha256")
            or digest(observed[Path("authority/pr300_evidence_index.json")])
            != current.get("pr300_evidence_index_sha256")
            or digest(observed[Path("authority/candidate_manifest.json")])
            != source["inputs"]["candidate_manifest_sha256"]
            or digest(observed[Path("authority/fresh_source_index.json")])
            != current["fresh_source_index_file_sha256"]):
        raise ValueError("source evidence authority digest differs")
    packet = json.loads(observed[Path("authority/source_packet.json")])
    fresh_index = json.loads(observed[Path("authority/fresh_source_index.json")])
    old_index = json.loads(observed[Path("authority/old_provenance_index.json")])
    if (fresh_index.get("kind") != "NEXUS-STUDENT-SOURCE-PROVENANCE-INDEX-V1"
            or fresh_index.get("index_sha256")
            != digest(_compact({k: v for k, v in fresh_index.items() if k != "index_sha256"}))
            or fresh_index["index_sha256"] != current["fresh_source_index_logical_sha256"]):
        raise ValueError("fresh source index logical digest differs")
    packet_rows = {row["content_sha256"]: row for row in packet["artifacts"]}
    fresh_rows = {row["content_sha256"]: row for row in fresh_index["rows"]}
    old_rows = {row["content_sha256"]: row for row in old_index["rows"]}
    if any(len(rows) != len({row["content_sha256"] for row in rows})
           for rows in (packet["artifacts"], fresh_index["rows"], old_index["rows"])):
        raise ValueError("source evidence index duplicate")
    for artifact, _, current_row in pairs:
        sha = artifact["content_sha256"]
        source_sha = artifact["source_pdf_sha256"]
        receipt_sha = artifact["derivative_receipt_sha256"]
        packet_row = packet_rows.get(source_sha)
        old = old_rows.get(source_sha)
        fresh = fresh_rows.get(source_sha)
        if not isinstance(packet_row, dict) or not isinstance(old, dict) or not isinstance(fresh, dict):
            raise ValueError("source proof population differs")
        source_path = packet_row.get("source_path")
        if not isinstance(source_path, str) or not source_path.endswith(".pdf"):
            raise ValueError("source PDF path missing")
        fixed[Path("source_pdfs") / f"{source_sha}.pdf"] = _safe_join(source_pdf_root, source_path)
        fixed[Path("derivatives") / f"{sha}.txt"] = derivative_root / f"{sha}.txt"
        fixed[Path("derivative_receipts") / f"{receipt_sha}.json"] = (
            evidence / "derivative_receipts" / receipt_sha[:2] / f"{receipt_sha}.json"
        )
        fixed[Path("source_evidence") / f"{source_sha}.json"] = evidence / f"{source_sha}.json"
        old_rel = old.get("checkpoint_relpath")
        if not isinstance(old_rel, str):
            raise ValueError("old checkpoint path missing")
        fixed[Path("old_checkpoints") / f"{source_sha}.json"] = _safe_join(
            old_checkpoint_root, old_rel,
        )
        fresh_file = fresh_root / "checkpoints" / f"{source_sha}.json"
        fixed[Path("fresh_checkpoints") / f"{source_sha}.json"] = fresh_file
        checkpoint = json.loads(fresh_file.read_bytes())
        listing_rel = checkpoint.get("source_provenance", {}).get(
            "listing_capture_receipt_relpath")
        if (not isinstance(listing_rel, str)
                or not listing_rel.startswith(".private-source-refresh/listings/")
                or not listing_rel.endswith(".receipt.json")):
            raise ValueError("fresh listing receipt path differs")
        listing_sha = current_row["fresh_listing_receipt_sha256"]
        listing_root = fresh_root.parent / "listings"
        listing_path = listing_root / Path(listing_rel).name
        listing_raw = listing_path.read_bytes()
        if digest(listing_raw) != listing_sha:
            raise ValueError("fresh listing receipt digest differs")
        fixed[Path("fresh_listings") / f"{listing_sha}.json"] = listing_path
        fixed.update(listing_body_paths(
            json.loads(listing_raw), listing_sha, listing_root,
            prefix=listing_path.name.removesuffix(".receipt.json"),
        ))
        uri = current_row["source_uri"]
        fixed[Path("fresh_fetches") / f"{digest(uri.encode())}.json"] = (
            fresh_root / "pdf_fetches" / f"{digest(uri.encode())}.json"
        )
    return fixed


def write_private_cas(
    cas_root: Path, files: dict[Path, Path], *, repository_root: Path,
    candidate_sha256: str,
) -> str:
    """Copie atomique immuable des preuves ; aucun PDF dans le dépôt."""
    cas_root = cas_root.resolve()
    if cas_root.is_relative_to(repository_root.resolve()):
        raise ValueError("private CAS must be outside repository")
    if cas_root.exists():
        raise ValueError("private CAS output already exists")
    cas_root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{cas_root.name}-", dir=cas_root.parent))
    try:
        os.chmod(stage, 0o700)
        refs = []
        for relative, origin in sorted(files.items(), key=lambda pair: pair[0].as_posix()):
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("private CAS relative path invalid")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
            os.chmod(target, 0o600)
            raw = target.read_bytes()
            refs.append({"path": relative.as_posix(), "sha256": digest(raw),
                         "byte_count": len(raw)})
        index = {
            "kind": CAS_KIND,
            "candidate_manifest_sha256": candidate_sha256,
            "private_only": True,
            "public_pdf_count": 0,
            "full_pdf_redistribution_allowed": False,
            "file_count": len(refs),
            "files": refs,
        }
        raw = canonical(index)
        (stage / "index.json").write_bytes(raw)
        os.chmod(stage / "index.json", 0o600)
        stage.rename(cas_root)
        return digest(raw)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_cas_files(cas_root: Path, *, candidate_sha256: str) -> dict[str, str]:
    """Relire chaque octet du paquet durable et refuser tout fichier supplémentaire."""
    raw = (cas_root / "index.json").read_bytes()
    index = _json(raw, "private CAS index")
    rows = index.get("files")
    if (index.get("kind") != CAS_KIND
            or index.get("candidate_manifest_sha256") != candidate_sha256
            or index.get("private_only") is not True
            or index.get("public_pdf_count") != 0
            or index.get("full_pdf_redistribution_allowed") is not False
            or not isinstance(rows, list) or index.get("file_count") != len(rows)):
        raise ValueError("private CAS index authority differs")
    refs: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "byte_count"}:
            raise ValueError("private CAS file reference malformed")
        relative = row["path"]
        if (not isinstance(relative, str) or relative in refs
                or not _sha_field(row["sha256"])
                or type(row["byte_count"]) is not int or row["byte_count"] < 0):
            raise ValueError("private CAS file reference differs")
        path = _safe_join(cas_root, relative)
        observed = path.read_bytes()
        if digest(observed) != row["sha256"] or len(observed) != row["byte_count"]:
            raise ValueError(f"private CAS file digest differs: {relative}")
        refs[relative] = row["sha256"]
    expected_paths = set(refs) | {"index.json"}
    actual_paths = {path.relative_to(cas_root).as_posix()
                    for path in cas_root.rglob("*") if path.is_file()}
    if actual_paths != expected_paths:
        raise ValueError("private CAS file population differs")
    return refs


def verify_private_cas_evidence(
    source: dict[str, Any], cas_root: Path, *, as_of: datetime | None = None,
) -> dict[str, Any]:
    """Rejouer les 253 preuves depuis le CAS durable, sans chemin agent temporaire."""
    refs = verify_cas_files(
        cas_root, candidate_sha256=source["inputs"]["candidate_manifest_sha256"],
    )
    used: set[str] = set()

    def read(relative: str) -> bytes:
        if relative not in refs:
            raise ValueError(f"private proof missing: {relative}")
        used.add(relative)
        return (cas_root / relative).read_bytes()

    pii_raw = read("reports/pii_adjudication.json")
    current_raw = read("reports/source_currentness.json")
    pairs = verify_report_pair(source, pii_raw, current_raw, as_of=as_of)
    pii, current = json.loads(pii_raw), json.loads(current_raw)
    pattern_raw = read("reports/pattern_screen.json")
    policy_raw = read("authority/pii_policy.yml")
    rights_authority_raw = read("authority/eduscol_sitewide_rights.yml")
    packet_raw = read("authority/source_packet.json")
    pr300_index_raw = read("authority/pr300_evidence_index.json")
    old_index_raw = read("authority/old_provenance_index.json")
    candidate_raw = read("authority/candidate_manifest.json")
    fresh_index_raw = read("authority/fresh_source_index.json")
    if (digest(pattern_raw) != pii.get("pattern_screen_sha256")
            or digest(policy_raw) != pii["policy_sha256"]
            or digest(rights_authority_raw)
            != source["inputs"]["release"]["authorities"]["rights_authority_sha256"]
            or digest(packet_raw) != pii.get("source_inventory_packet_sha256")
            or digest(pr300_index_raw) != pii.get("pr300_evidence_index_sha256")
            or digest(pr300_index_raw) != current.get("pr300_evidence_index_sha256")
            or digest(candidate_raw) != source["inputs"]["candidate_manifest_sha256"]
            or digest(fresh_index_raw) != current["fresh_source_index_file_sha256"]
            or pii.get("source_pdf_reverified_count") != len(pairs)):
        raise ValueError("private proof authority digest differs")
    rights_authority = yaml.safe_load(rights_authority_raw)
    if (not isinstance(rights_authority, dict)
            or rights_authority.get("authority_id") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
            or rights_authority.get("authority_kind") != "SITEWIDE_DOWNLOAD_AUTHORITY"
            or rights_authority.get("licence_id") != "ETALAB-2.0"
            or rights_authority.get("full_pdf_redistribution_allowed_by_product") is not False
            or rights_authority.get("answer_generation_allowed") is not False):
        raise ValueError("global Eduscol rights authority differs")
    pattern = json.loads(pattern_raw)
    packet = json.loads(packet_raw)
    pr300_index = json.loads(pr300_index_raw)
    old_index = json.loads(old_index_raw)
    fresh_index = json.loads(fresh_index_raw)
    unsigned_index = {k: v for k, v in fresh_index.items() if k != "index_sha256"}
    if (pattern.get("kind") != "NEXUS_STUDENT_DERIVATIVE_PII_PATTERN_SCREEN_V1"
            or pattern.get("scope") != "PATTERN_SCREEN_ONLY_NOT_FULL_PII_ADJUDICATION"
            or pattern.get("artifact_count") != len(pairs)
            or fresh_index.get("kind") != "NEXUS-STUDENT-SOURCE-PROVENANCE-INDEX-V1"
            or fresh_index.get("checked_at_utc")
            != current.get("fresh_source_checked_at_utc")
            or fresh_index.get("index_sha256") != digest(_compact(unsigned_index))
            or fresh_index["index_sha256"] != current["fresh_source_index_logical_sha256"]):
        raise ValueError("private source index or pattern scope differs")
    checked_at = _utc(fresh_index["checked_at_utc"])
    now = as_of or datetime.now(timezone.utc)
    if checked_at is None:
        raise ValueError("private source index timestamp invalid")
    valid_until = checked_at + FRESHNESS_TTL

    def indexed(rows: list[dict], key: str) -> dict[str, dict]:
        result = {row[key]: row for row in rows}
        if len(result) != len(rows):
            raise ValueError("private proof duplicate")
        return result

    packet_by_source = indexed(packet["artifacts"], "content_sha256")
    old_by_source = indexed(old_index["rows"], "content_sha256")
    fresh_by_source = indexed(fresh_index["rows"], "content_sha256")
    screen_by_derivative = indexed(pattern["rows"], "content_sha256")
    if set(screen_by_derivative) != {item[0]["content_sha256"] for item in pairs}:
        raise ValueError("pattern screen exact population differs")
    for artifact, p, c in pairs:
        sha = artifact["content_sha256"]
        source_sha = artifact["source_pdf_sha256"]
        receipt_sha = artifact["derivative_receipt_sha256"]
        uri = artifact["citation"]["source_uri"]
        packet_row = packet_by_source.get(source_sha, {})
        old_row = old_by_source.get(source_sha, {})
        fresh_row = fresh_by_source.get(source_sha, {})
        screen_row = screen_by_derivative[sha]
        if (packet_row.get("source_pii_status") != "CLEARED"
                or packet_row.get("source_pdf_sha256_verified") is not True
                or p.get("source_inventory_packet_sha256") != digest(packet_raw)
                or screen_row.get("status") != "PATTERN_SCREEN_CLEAR_ONLY"
                or screen_row.get("unresolved_hits") != 0
                or p.get("pattern_screen_sha256") != digest(canonical(screen_row))
                or p.get("text_byte_count") != screen_row.get("text_byte_count")):
            raise ValueError(f"private PII proof differs: {sha}")
        derivative_raw = read(f"derivatives/{sha}.txt")
        pdf_raw = read(f"source_pdfs/{source_sha}.pdf")
        receipt_raw = read(f"derivative_receipts/{receipt_sha}.json")
        source_evidence_raw = read(f"source_evidence/{source_sha}.json")
        old_checkpoint_raw = read(f"old_checkpoints/{source_sha}.json")
        checkpoint_raw = read(f"fresh_checkpoints/{source_sha}.json")
        if (digest(derivative_raw) != sha or len(derivative_raw) != p["text_byte_count"]
                or digest(pdf_raw) != source_sha or digest(receipt_raw) != receipt_sha
                or digest(source_evidence_raw) != p.get("source_evidence_sha256")
                or pr300_index.get("artifacts", {}).get(source_sha, {}).get("sha256")
                != digest(source_evidence_raw)
                or digest(old_checkpoint_raw) != old_row.get("checkpoint_file_sha256")
                or digest(old_checkpoint_raw) != c.get("old_source_checkpoint_file_sha256")
                or digest(checkpoint_raw) != fresh_row.get("checkpoint_file_sha256")
                or digest(checkpoint_raw) != c["fresh_source_checkpoint_file_sha256"]):
            raise ValueError(f"private exact bytes or checkpoint digest differs: {sha}")
        receipt = json.loads(receipt_raw)
        source_evidence = json.loads(source_evidence_raw)
        old_checkpoint = json.loads(old_checkpoint_raw)
        checkpoint = json.loads(checkpoint_raw)
        unsigned_old = {k: v for k, v in old_checkpoint.items() if k != "checkpoint_sha256"}
        unsigned = {k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"}
        if (receipt.get("kind") != "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
                or receipt.get("source_content_sha256") != source_sha
                or receipt.get("derivative_content_sha256") != sha
                or receipt.get("derivative_byte_count") != len(derivative_raw)
                or receipt.get("status") != "PREPARED_PRIVATE"
                or receipt.get("all_source_pages_inspected") is not True
                or any(receipt.get(key) is not False for key in (
                    "ocr_used", "images_copied", "graphic_renders_copied"))
                or source_evidence.get("scan_complete") is not True
                or source_evidence.get("images_and_annexes_checked") is not True
                or source_evidence.get("pdf_scan_evidence", {}).get("exact_bytes_match")
                is not True
                or old_checkpoint.get("checkpoint_sha256") != digest(_compact(unsigned_old))
                or old_checkpoint["checkpoint_sha256"] != c.get("old_source_checkpoint_sha256")
                or receipt.get("source_provenance_checkpoint_sha256")
                != old_checkpoint["checkpoint_sha256"]
                or checkpoint.get("checkpoint_sha256") != digest(_compact(unsigned))
                or checkpoint["checkpoint_sha256"] != c["fresh_source_checkpoint_sha256"]
                or checkpoint.get("content_sha256") != source_sha
                or checkpoint.get("checked_at_utc") != fresh_index["checked_at_utc"]):
            raise ValueError(f"private lineage proof differs: {sha}")
        provenance = checkpoint.get("source_provenance")
        if not isinstance(provenance, dict):
            raise ValueError(f"fresh source provenance absent: {sha}")
        fetch = provenance.get("pdf_fetch")
        current_ref = provenance.get("currentness_evidence_ref")
        revocation_ref = provenance.get("revocation_evidence_ref")
        citation_date = _utc(artifact["citation"].get("source_updated_at"))
        download_at = _utc(fetch.get("observed_at_utc")) if isinstance(fetch, dict) else None
        current_at = _utc(provenance.get("currentness_observed_at_utc"))
        revocation_at = _utc(provenance.get("revocation_observed_at_utc"))
        if (fresh_row.get("source_status") != "EXACT_CURRENT_SOURCE"
                or fresh_row.get("currentness_status") != "PASS"
                or fresh_row.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
                or provenance.get("status") != "EXACT_CURRENT_SOURCE"
                or provenance.get("currentness_status") != "PASS"
                or provenance.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
                or provenance.get("retraction_notice_associated") is not False
                or not isinstance(fetch, dict)
                or fetch.get("requested_url") != uri or fetch.get("final_url") != uri
                or fetch.get("http_status") != 200 or fetch.get("content_sha256") != source_sha
                or any(not isinstance(ref, dict)
                       or ref.get("pdf_sha256") != source_sha
                       or ref.get("pdf_url") != uri
                       or ref.get("listing_capture_receipt_sha256")
                       != c["fresh_listing_receipt_sha256"]
                       for ref in (current_ref, revocation_ref))
                or c.get("currentness_observed_at_utc")
                != provenance.get("currentness_observed_at_utc")
                or c.get("revocation_observed_at_utc")
                != provenance.get("revocation_observed_at_utc")
                or citation_date is None or download_at is None
                or current_at is None or revocation_at is None
                or min(download_at, current_at, revocation_at) < citation_date):
            raise ValueError(f"fresh source currentness or URL proof differs: {sha}")
        listing_sha = c["fresh_listing_receipt_sha256"]
        listing_raw = read(f"fresh_listings/{listing_sha}.json")
        listing = json.loads(listing_raw)
        fetch_raw = read(f"fresh_fetches/{digest(uri.encode())}.json")
        fetch_receipt = json.loads(fetch_raw)
        unsigned_fetch = {k: v for k, v in fetch_receipt.items()
                          if k != "receipt_sha256"}
        listing_at = _utc(listing.get("observed_at_utc"))
        get_at = _utc(fetch_receipt.get("fetch", {}).get("observed_at_utc"))
        if (listing_at is None or get_at is None
                or provenance.get("listing_observed_at_utc")
                != listing.get("observed_at_utc")):
            raise ValueError(f"fresh listing or PDF capture timestamp differs: {sha}")
        valid_until = min(valid_until, check_capture_timing(
            checked_at, listing_at, get_at, current_at, revocation_at, as_of=now,
        ))
        prefix = listing.get("normalized_html_file", "").removesuffix(".normalized.html")
        if not re.fullmatch(r"[0-9a-f]{16}", prefix):
            raise ValueError(f"fresh listing body identity differs: {sha}")
        for name, suffix in LISTING_BODIES:
            filename = f"{prefix}{suffix}"
            if (listing.get(f"{name}_file") != filename
                    or digest(read(f"fresh_listing_bodies/{listing_sha}/{filename}"))
                    != listing.get(f"{name}_sha256")):
                raise ValueError(f"fresh listing body digest differs: {sha}")
        if (digest(listing_raw) != listing_sha
                or listing.get("http_status") != 200
                or not any(link.get("href") == uri for link in listing.get("pdf_links", []))
                or provenance.get("listing_capture_receipt_sha256") != listing_sha
                or digest(fetch_raw) != c["fresh_pdf_fetch_receipt_sha256"]
                or fetch_receipt.get("receipt_sha256") != digest(_compact(unsigned_fetch))
                or fetch_receipt.get("url") != uri
                or fetch_receipt.get("fetch") != fetch):
            raise ValueError(f"fresh listing or PDF fetch proof differs: {sha}")
    if used != set(refs):
        raise ValueError("private proof population contains unexpected files")
    return make_inclusion(
        source, pii_raw, current_raw, pairs,
        private_cas_manifest_sha256=digest((cas_root / "index.json").read_bytes()),
        source_currentness_valid_until=valid_until,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--pii-report", type=Path, required=True)
    parser.add_argument("--currentness-report", type=Path, required=True)
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--private-derivatives-root", type=Path, required=True)
    parser.add_argument("--source-pdf-root", type=Path, required=True)
    parser.add_argument("--old-checkpoint-root", type=Path, required=True)
    parser.add_argument("--private-cas-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = load_sources(args.repository_root)
    if not args.private_cas_root.exists():
        files = _source_map(
            source, args.repository_root.resolve(), args.pii_report, args.currentness_report,
            args.fresh_root, args.private_derivatives_root, args.source_pdf_root,
            args.old_checkpoint_root,
        )
        write_private_cas(
            args.private_cas_root, files, repository_root=args.repository_root,
            candidate_sha256=source["inputs"]["candidate_manifest_sha256"],
        )
    elif (args.pii_report.read_bytes()
          != (args.private_cas_root / "reports/pii_adjudication.json").read_bytes()
          or args.currentness_report.read_bytes()
          != (args.private_cas_root / "reports/source_currentness.json").read_bytes()):
        raise ValueError("input reports differ from immutable private CAS")
    inclusion = verify_private_cas_evidence(source, args.private_cas_root)
    output = canonical(inclusion)
    if args.output.exists() and args.output.read_bytes() != output:
        raise ValueError("immutable inclusion output differs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists():
        args.output.write_bytes(output)
    print(f"INCLUSION_COUNT={inclusion['decision_count']}")
    print(f"INCLUSION_SHA256={digest(output)}")
    print(f"PRIVATE_CAS_MANIFEST_SHA256={inclusion['private_cas_manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
