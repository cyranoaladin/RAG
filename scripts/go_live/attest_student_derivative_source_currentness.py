"""Atteste en lecture seule la source courante des 253 dérivés #312.

Le reçu prouve un constat daté par PDF exact et listing officiel. Il n'active
pas #312 : le futur successeur doit ancrer son SHA dans son propre manifeste.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scan_student_derivative_pii import _canonical, _sha, _write_atomic
from student_derivative_pii_currentness_gate import EVIDENCE_RELATIVE, assess_repository
from student_rights_source_provenance import canonical_json_bytes, load_listing_capture

ROOT = Path(__file__).resolve().parents[2]


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.utcoffset() == timezone.utc.utcoffset(stamp) else None
    except ValueError:
        return None


def assess_fresh_checkpoint(
    entry: Mapping[str, Any], row: Mapping[str, Any],
    checkpoint: Mapping[str, Any], *, listing_receipt_sha256: str,
) -> dict[str, Any]:
    """Aucun statut source général n'est inféré d'un simple HTTP 403."""
    source_sha = entry.get("source_content_sha256")
    derivative_sha = entry.get("derivative_content_sha256")
    citation = entry.get("citation")
    uri = citation.get("source_uri") if isinstance(citation, dict) else None
    source = checkpoint.get("source_provenance")
    if not isinstance(source, dict):
        source = {}
    fetch = source.get("pdf_fetch")
    current = source.get("currentness_evidence_ref")
    revocation = source.get("revocation_evidence_ref")
    reasons = []
    if (row.get("content_sha256") != source_sha
            or checkpoint.get("content_sha256") != source_sha
            or source_sha == derivative_sha):
        reasons.append("SOURCE_DERIVATIVE_IDENTITY_MISMATCH")
    if (row.get("source_status") != "EXACT_CURRENT_SOURCE"
            or row.get("currentness_status") != "PASS"
            or row.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
            or source.get("status") != "EXACT_CURRENT_SOURCE"
            or source.get("currentness_status") != "PASS"
            or source.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
            or source.get("retraction_notice_associated") is not False):
        reasons.append("SOURCE_CURRENTNESS_OR_REVOCATION_UNPROVEN")
    if (not isinstance(fetch, dict)
            or fetch.get("requested_url") != uri
            or fetch.get("final_url") != uri
            or fetch.get("http_status") != 200
            or fetch.get("content_sha256") != source_sha
            or type(fetch.get("byte_count")) is not int
            or fetch["byte_count"] <= 0):
        reasons.append("FRESH_PDF_EXACT_IDENTITY_UNPROVEN")
    for ref in (current, revocation):
        if (not isinstance(ref, dict)
                or ref.get("pdf_sha256") != source_sha
                or ref.get("pdf_url") != uri
                or ref.get("listing_capture_receipt_sha256")
                != listing_receipt_sha256):
            reasons.append("LISTING_SOURCE_LINK_UNPROVEN")
            break
    attribution_at = _utc(citation.get("source_updated_at") if isinstance(citation, dict) else None)
    download_at = _utc(fetch.get("observed_at_utc") if isinstance(fetch, dict) else None)
    current_at = _utc(source.get("currentness_observed_at_utc"))
    revocation_at = _utc(source.get("revocation_observed_at_utc"))
    if (attribution_at is None or download_at is None or current_at is None
            or revocation_at is None or min(download_at, current_at, revocation_at)
            < attribution_at):
        reasons.append("FRESH_OBSERVATION_DATE_INVALID")
    return {
        "derivative_content_sha256": derivative_sha,
        "source_pdf_sha256": source_sha,
        "source_uri": uri,
        "status": "PASS" if not reasons else "BLOCKED",
        "reason_codes": sorted(set(reasons)),
    }


def attest_repository(
    root: Path, private_root: Path, source_checkpoint_root: Path,
    fresh_root: Path, *, attested_at_utc: str,
) -> dict[str, Any]:
    """Recoupe les captures, fetchs, checkpoints et reçus #300/#312."""
    prior = assess_repository(root, private_root,
                              source_checkpoint_root=source_checkpoint_root)
    if (prior["structural_pass_count"] != 253
            or prior["missing_currentness_checkpoint_count"] != 0):
        raise ValueError("PR300_312_PRIOR_BINDING_INVALID")
    evidence = root / EVIDENCE_RELATIVE
    manifest_raw = (evidence / "public_derivative_candidate_manifest_20261010.json").read_bytes()
    manifest = json.loads(manifest_raw)
    approval = json.loads((evidence / "pr300_final_authority_approval.json").read_bytes())
    fresh_raw = (fresh_root / "index.json").read_bytes()
    fresh = json.loads(fresh_raw)
    unsigned = dict(fresh)
    logical_index_sha = unsigned.pop("index_sha256", None)
    if (fresh.get("kind") != "NEXUS-STUDENT-SOURCE-PROVENANCE-INDEX-V1"
            or logical_index_sha != _sha(canonical_json_bytes(unsigned))
            or fresh.get("inventory_sha256")
            != approval.get("sha256", {}).get("inventory_packet")
            or fresh.get("authority_yaml_sha256")
            != approval.get("sha256", {}).get("authority")
            or fresh.get("record_count") != 315
            or fresh.get("listing_count") != 15
            or fresh.get("source_checker_code_sha256")
            != _sha((root / "scripts/go_live/student_rights_source_provenance.py").read_bytes())
            or fresh.get("capture_script_sha256")
            != _sha((root / "scripts/go_live/capture_eduscol_source_listings.py").read_bytes())
            or not isinstance(fresh.get("rows"), list)
            or len(fresh["rows"]) != 315):
        raise ValueError("FRESH_SOURCE_INDEX_INVALID")
    by_source = {row["content_sha256"]: row for row in fresh["rows"]}
    if len(by_source) != 315:
        raise ValueError("FRESH_SOURCE_INDEX_DUPLICATE")
    old_index = json.loads((evidence / "provenance/index.json").read_bytes())
    old_rows = {row["content_sha256"]: row for row in old_index["rows"]}
    listing_cache: dict[str, dict[str, Any]] = {}
    rows = []
    for entry in sorted(manifest["entries"], key=lambda x: x["derivative_content_sha256"]):
        source_sha = entry["source_content_sha256"]
        row = by_source[source_sha]
        checkpoint_path = fresh_root / "checkpoints" / f"{source_sha}.json"
        if not row["checkpoint_relpath"].endswith(
                f"/checkpoints/{source_sha}.json"):
            raise ValueError("FRESH_SOURCE_CHECKPOINT_PATH_INVALID")
        checkpoint_raw = checkpoint_path.read_bytes()
        checkpoint = json.loads(checkpoint_raw)
        unsigned_checkpoint = dict(checkpoint)
        checkpoint_sha = unsigned_checkpoint.pop("checkpoint_sha256", None)
        if (row.get("checkpoint_file_sha256") != _sha(checkpoint_raw)
                or checkpoint_sha != _sha(canonical_json_bytes(unsigned_checkpoint))
                or checkpoint.get("inventory_sha256") != fresh["inventory_sha256"]
                or checkpoint.get("authority_yaml_sha256")
                != fresh["authority_yaml_sha256"]):
            raise ValueError("FRESH_SOURCE_CHECKPOINT_DIGEST_MISMATCH")
        provenance = checkpoint["source_provenance"]
        listing_relative = provenance.get("listing_capture_receipt_relpath")
        if (not isinstance(listing_relative, str)
                or not listing_relative.endswith(".receipt.json")
                or Path(listing_relative).name != listing_relative.rsplit("/", 1)[-1]):
            raise ValueError("FRESH_SOURCE_LISTING_PATH_INVALID")
        listing_path = fresh_root.parent / "listings" / Path(listing_relative).name
        listing_raw = listing_path.read_bytes()
        listing_sha = _sha(listing_raw)
        if listing_sha not in listing_cache:
            listing_cache[listing_sha] = load_listing_capture(
                root, listing_path,
                root / "scripts/go_live/capture_eduscol_source_listings.py",
            )["receipt"]
        listing = listing_cache[listing_sha]
        if (listing_sha != provenance.get("listing_capture_receipt_sha256")
                or listing.get("http_status") != 200
                or listing.get("requested_url") not in {
                    checkpoint.get("source_listing_url"),
                    provenance.get("discovered_official_listing_url"),
                }
                or not any(link.get("href") == entry["citation"]["source_uri"]
                           for link in listing.get("pdf_links", []))):
            raise ValueError("FRESH_SOURCE_LISTING_BINDING_INVALID")
        pdf_uri = entry["citation"]["source_uri"]
        fetch_key = _sha(pdf_uri.encode("utf-8"))
        fetch_raw = (fresh_root / "pdf_fetches" / f"{fetch_key}.json").read_bytes()
        fetch = json.loads(fetch_raw)
        unsigned_fetch = dict(fetch)
        fetch_sha = unsigned_fetch.pop("receipt_sha256", None)
        if (fetch.get("url") != pdf_uri
                or fetch.get("fetch") != provenance.get("pdf_fetch")
                or fetch_sha != _sha(canonical_json_bytes(unsigned_fetch))):
            raise ValueError("FRESH_SOURCE_PDF_FETCH_BINDING_INVALID")
        decision = assess_fresh_checkpoint(
            entry, row, checkpoint, listing_receipt_sha256=listing_sha,
        )
        old = old_rows[source_sha]
        receipt_sha = entry["derivative_receipt_sha256"]
        receipt = json.loads((evidence / "derivative_receipts" / receipt_sha[:2]
                              / f"{receipt_sha}.json").read_bytes())
        if (receipt.get("source_provenance_checkpoint_sha256") is None
                or old.get("checkpoint_file_sha256") is None):
            raise ValueError("PR300_SOURCE_CHECKPOINT_BINDING_MISSING")
        decision.update({
            "derivative_receipt_sha256": receipt_sha,
            "old_source_checkpoint_sha256": receipt["source_provenance_checkpoint_sha256"],
            "old_source_checkpoint_file_sha256": old["checkpoint_file_sha256"],
            "fresh_source_checkpoint_sha256": checkpoint_sha,
            "fresh_source_checkpoint_file_sha256": _sha(checkpoint_raw),
            "fresh_listing_receipt_sha256": listing_sha,
            "fresh_pdf_fetch_receipt_sha256": _sha(fetch_raw),
            "currentness_observed_at_utc": provenance["currentness_observed_at_utc"],
            "revocation_observed_at_utc": provenance["revocation_observed_at_utc"],
        })
        decision["evidence_sha256"] = _sha(_canonical(decision))
        rows.append(decision)
    counts = Counter(row["status"] for row in rows)
    return {
        "kind": "NEXUS_STUDENT_DERIVATIVE_SOURCE_CURRENTNESS_ATTESTATION_V1",
        "attested_at_utc": attested_at_utc,
        "candidate_manifest_sha256": _sha(manifest_raw),
        "pr300_evidence_index_sha256": prior["pr300_evidence_index_sha256"],
        "fresh_source_index_logical_sha256": logical_index_sha,
        "fresh_source_index_file_sha256": _sha(fresh_raw),
        "fresh_source_checked_at_utc": fresh["checked_at_utc"],
        "decision_count": len(rows),
        "status_counts": dict(counts),
        "successor_release_binding": "NOT_YET_SEALED",
        "producer_code_sha256": _sha(Path(__file__).read_bytes()),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--source-checkpoint-root", type=Path, required=True)
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = attest_repository(
        args.repository_root, args.private_root, args.source_checkpoint_root,
        args.fresh_root, attested_at_utc=now,
    )
    raw = _canonical(result)
    _write_atomic(args.output, raw)
    _write_atomic(args.output.with_suffix(args.output.suffix + ".sha256"),
                  f"{hashlib.sha256(raw).hexdigest()}  {args.output.name}\n".encode())
    print(json.dumps({"decision_count": result["decision_count"],
                      "status_counts": result["status_counts"],
                      "report_sha256": _sha(raw),
                      "successor_release_binding": result["successor_release_binding"]},
                     sort_keys=True))
    return 0 if result["status_counts"] == {"PASS": 253} else 1


if __name__ == "__main__":
    raise SystemExit(main())
