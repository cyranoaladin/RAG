"""Le pont de droits des dérivés s'appuie sur #300/#312, jamais sur les zones PDF."""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compact(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def _pretty(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _bridge():
    return importlib.import_module("derivative_rights_bridge")


def _candidate() -> dict:
    authority_raw = (ROOT / "governance/student_public_rights/authorities"
                     / "eduscol_etalab_2_0_sitewide_20261010.yml").read_bytes()
    authority_sha = _sha(authority_raw)
    source_sha = "a" * 64
    derivative_bytes = b"Native ministerial text excerpt\n"
    derivative_sha = _sha(derivative_bytes)
    attribution = {
        "source_uri": "https://eduscol.education.gouv.fr/document.pdf",
        "source_label": "Document de cours",
        "source_updated_at": "2026-10-10T06:00:00Z",
        "source_date_kind": "DATED_OFFICIAL_SNAPSHOT",
        "licensor": "Direction générale de l'enseignement scolaire",
        "licence_id": "ETALAB-2.0",
        "derivative_notice": "Source : Éduscol, dérivé textuel, snapshot du 2026-10-10T06:00:00Z, Licence Ouverte 2.0.",
    }
    receipt = {
        "kind": "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1",
        "status": "PREPARED_PRIVATE",
        "publication_authorized": False,
        "source_content_sha256": source_sha,
        "derivative_content_sha256": derivative_sha,
        "candidate_relpath": f"candidates/{derivative_sha}.txt",
        "rights_authority_sha256": authority_sha,
        "source_attribution": attribution,
        "all_source_pages_inspected": True,
        "images_copied": False,
        "graphic_renders_copied": False,
        "ocr_used": False,
    }
    receipt_raw = _compact(receipt).rstrip(b"\n")
    receipt_sha = _sha(receipt_raw)
    manifest = {"status": "PRE_REVIEW_NOT_PROMOTABLE",
                "rights_authority_sha256": authority_sha,
                "counts": {"public_derivative_artifacts": 1,
                           "original_pdf_public_count": 0},
                "entries": [{"source_content_sha256": source_sha,
                             "derivative_content_sha256": derivative_sha,
                             "derivative_receipt_sha256": receipt_sha,
                             "source_disposition": "REPLACE_WITH_NEW_CONTENT",
                             "derivative_disposition": "APPROVE_PUBLIC",
                             "media_type": "text/plain; charset=utf-8",
                             "private_candidate_relpath": f"candidates/{derivative_sha}.txt",
                             "citation": attribution}]}
    manifest_raw = _compact(manifest)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "content_sha256", "source_disposition", "derivative_disposition",
        "derivative_content_sha256", "derivative_receipt_sha256",
        "rights_authority_id", "rights_authority_sha256", "rights_evidence_ref",
    ], delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerow({"content_sha256": source_sha,
                     "source_disposition": "REPLACE_WITH_NEW_CONTENT",
                     "derivative_disposition": "APPROVE_PUBLIC",
                     "derivative_content_sha256": derivative_sha,
                     "derivative_receipt_sha256": receipt_sha,
                     "rights_authority_id": "EDUSCOL_ETALAB_2_0_SITEWIDE",
                     "rights_authority_sha256": authority_sha,
                     "rights_evidence_ref": "https://eduscol.education.gouv.fr/4656/mentions-legales"})
    sheet_raw = output.getvalue().encode()
    citation = {**attribution, "source_pdf_sha256": source_sha}
    return {
        "approval": {"kind": "PR300_DELEGATED_STUDENT_RIGHTS_APPROVAL_V1",
                     "reviewer": "abenrhouma",
                     "sha256": {"authority": authority_sha,
                                "decision_sheet": _sha(sheet_raw),
                                "candidate_manifest": _sha(manifest_raw)}},
        "authority_raw": authority_raw,
        "decision_sheet_raw": sheet_raw,
        "manifest_raw": manifest_raw,
        "artifacts": [{"content_sha256": derivative_sha, "artifact_id": derivative_sha,
                       "source_pdf_sha256": source_sha,
                       "derivative_receipt_sha256": receipt_sha,
                       "derivative_receipt_path": f"derivative_receipts/{receipt_sha}.json",
                       "source_path": f"{derivative_sha}.txt",
                       "media_type": "text/plain; charset=utf-8",
                       "source_url": attribution["source_uri"],
                       "citation": citation}],
        "rights_registry": {"kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V1",
                            "status": "CANDIDATE_NOT_AUTHORIZED",
                            "rights_authority_sha256": authority_sha,
                            "authorized_use": "student_retrieval_excerpt_only",
                            "full_pdf_redistribution_allowed": False,
                            "answer_generation_allowed": False,
                            "entries": [{"content_sha256": derivative_sha,
                                         "source_pdf_sha256": source_sha,
                                         "derivative_receipt_sha256": receipt_sha,
                                         "citation_sha256": _sha(_pretty(citation))}]},
        "receipt_bytes": {receipt_sha: receipt_raw},
        "derivative_bytes": {derivative_sha: derivative_bytes},
        "expected_count": 1,
    }


def test_accepts_explicitly_approved_text_derivative() -> None:
    assert _bridge()._verify_derivative_rights_bindings(**_candidate()) == 1


def test_public_gate_cannot_reduce_the_253_artifact_population() -> None:
    with pytest.raises(TypeError):
        _bridge().verify_derivative_rights_bridge(**_candidate())


@pytest.mark.parametrize("mutate", [
    lambda c: c["derivative_bytes"].update({next(iter(c["derivative_bytes"])): b"changed"}),
    lambda c: c["receipt_bytes"].update({next(iter(c["receipt_bytes"])): b"{}\n"}),
    lambda c: c["approval"]["sha256"].update({"authority": "0" * 64}),
    lambda c: c["artifacts"][0]["citation"].update({"licence_id": "NONE"}),
    lambda c: c["artifacts"][0].update({"media_type": "application/pdf"}),
    lambda c: c["rights_registry"].update({"full_pdf_redistribution_allowed": True}),
    lambda c: c["rights_registry"]["entries"][0].update({"rights_basis": "officiel_public"}),
])
def test_refuses_tampered_or_pdf_zone_based_rights(mutate) -> None:
    candidate = copy.deepcopy(_candidate())
    mutate(candidate)
    with pytest.raises(_bridge().DerivativeRightsBridgeError):
        _bridge()._verify_derivative_rights_bindings(**candidate)


def test_replays_all_253_approved_derivative_bytes() -> None:
    private_root = Path(os.environ.get(
        "NEXUS_PRIVATE_CANDIDATE_ROOT",
        Path.home() / "nexus-student-text-derivatives-20261010",
    ))
    if not (private_root / "candidates").is_dir():
        pytest.skip("private #300 derivative CAS absent")
    evidence = ROOT / "docs/reports/go_live/student_rights_evidence"
    release = (ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
               / "profile_gate_student_public_v1/release-eb39f6cd0423e184/profile_gate")
    manifest_raw = (evidence / "public_derivative_candidate_manifest_20261010.json").read_bytes()
    manifest = json.loads(manifest_raw)
    receipts = {}
    candidates = {}
    for row in manifest["entries"]:
        receipt_sha = row["derivative_receipt_sha256"]
        derivative_sha = row["derivative_content_sha256"]
        receipts[receipt_sha] = (evidence / "derivative_receipts" / receipt_sha[:2]
                                 / f"{receipt_sha}.json").read_bytes()
        candidates[derivative_sha] = (private_root / "candidates"
                                      / f"{derivative_sha}.txt").read_bytes()
    assert _bridge().verify_derivative_rights_bridge(
        approval=json.loads((evidence / "pr300_final_authority_approval.json").read_bytes()),
        authority_raw=(ROOT / "governance/student_public_rights/authorities"
                       / "eduscol_etalab_2_0_sitewide_20261010.yml").read_bytes(),
        decision_sheet_raw=(ROOT / "docs/reports/go_live"
                            / "student_public_rights_individual_review_sheet_20261009.tsv").read_bytes(),
        manifest_raw=manifest_raw,
        artifacts=json.loads((release / "artifacts.release.json").read_bytes())["artifacts"],
        rights_registry=json.loads((release / "public_rights_registry.json").read_bytes()),
        receipt_bytes=receipts,
        derivative_bytes=candidates,
    ) == 253
