"""La source PDF reste privée même lorsqu'un dérivé textuel est admissible."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from adjudicate_student_public_rights import (  # noqa: E402
    adjudicate_derivative_candidate,
    build_derivative_artifact_record,
    build_public_derivative_candidate_manifest,
    materialize_derivative_pack,
    render_derivative_decision_sheet,
)


SOURCE_SHA = "a" * 64
DERIVATIVE_SHA = "b" * 64
AUTHORITY_SHA = "c" * 64
SOURCE_URL = "https://eduscol.education.gouv.fr/sites/default/files/document/source.pdf"


def evidence() -> tuple[dict, dict, dict, dict, dict]:
    packet = {
        "content_sha256": SOURCE_SHA,
        "page_count": 1,
        "source_pii_status": "CLEARED",
        "explicit_student_exclusion_signal": False,
    }
    scan = {
        "content_sha256": SOURCE_SHA,
        "page_count": 1,
        "exact_bytes_match": True,
        "full_document_scan_complete": True,
        "annexes_scan_complete": True,
    }
    provenance = {
        "kind": "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1",
        "content_sha256": SOURCE_SHA,
        "checkpoint_sha256": "2" * 64,
        "authority_yaml_sha256": AUTHORITY_SHA,
        "rights_basis_kind": "SITEWIDE_DOWNLOAD_AUTHORITY",
        "rights_basis_status": "CANDIDATE_PENDING_FINAL_APPROVAL",
        "raw_http_status_diagnostic": 403,
        "source_provenance": {
            "status": "EXACT_CURRENT_SOURCE",
            "listing_capture_receipt_sha256": "1" * 64,
            "matched_anchor": {"href": SOURCE_URL},
            "currentness_status": "PASS",
            "currentness_evidence_ref": {"pdf_sha256": SOURCE_SHA},
            "currentness_observed_at_utc": "2026-10-10T06:00:00Z",
            "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
            "revocation_evidence_ref": {"pdf_sha256": SOURCE_SHA},
            "revocation_observed_at_utc": "2026-10-10T06:00:00Z",
            "pdf_fetch": {
                "final_url": SOURCE_URL,
                "http_status": 200,
                "content_sha256": SOURCE_SHA,
            },
            "source_updated_at": {
                "date": "2026-09-01T00:00:00Z",
                "kind": "PDF_EXPLICIT_UPDATE_DATE",
                "evidence_ref": {"page": 1},
            },
        },
    }
    attribution = {
        "source_uri": SOURCE_URL,
        "source_label": "Programme de référence",
        "source_updated_at": "2026-09-01T00:00:00Z",
        "source_date_kind": "PDF_EXPLICIT_UPDATE_DATE",
        "licensor": "Direction générale de l'enseignement scolaire",
        "licence_id": "ETALAB-2.0",
        "derivative_notice": "Extrait textuel dérivé",
    }
    derivative = {
        "kind": "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1",
        "source_content_sha256": SOURCE_SHA,
        "source_page_count": 1,
        "status": "PREPARED_PRIVATE",
        "derivative_content_sha256": DERIVATIVE_SHA,
        "derivative_media_type": "text/plain",
        "derivative_encoding": "utf-8",
        "derivative_byte_count": 68,
        "publication_authorized": False,
        "ocr_used": False,
        "images_copied": False,
        "graphic_renders_copied": False,
        "all_source_pages_inspected": True,
        "source_attribution": attribution,
        "publisher_status": "PASS",
        "publisher_proof": {
            "status": "PASS",
            "kind": "OFFICIAL_CAPTURED_DOWNLOAD_PUBLISHER",
            "listing_capture_receipt_sha256": "1" * 64,
            "source_provenance_checkpoint_sha256": "2" * 64,
            "rights_authority_sha256": AUTHORITY_SHA,
            "source_content_sha256": SOURCE_SHA,
            "matched_anchor_href": SOURCE_URL,
            "source_pdf_url": SOURCE_URL,
        },
        "pages": [{
            "page_number": 1,
            "all_blocks": [{
                "block_index": 0,
                "block_type": 0,
                "block_class": "SAFE_TEXT_CANDIDATE",
                "citation": {**attribution, "source_page": 1,
                             "source_pdf_sha256": SOURCE_SHA},
            }],
            "selected_block_indices": [0],
        }],
    }
    policy = {
        "authorized_use": "student_retrieval_excerpt_only",
        "full_pdf_redistribution_allowed": False,
        "answer_generation_allowed": False,
        "rights_authorities": {"accepted_proof_kinds": [
            "INDIVIDUAL_EXPLICIT_LICENCE", "SITEWIDE_DOWNLOAD_AUTHORITY"]},
        "attribution": {"accepted_date_evidence_kinds": [
            "PDF_EXPLICIT_UPDATE_DATE", "OFFICIAL_RESOURCE_UPDATE_DATE",
            "DATED_OFFICIAL_SNAPSHOT"],
            "licensor_display": "Direction générale de l'enseignement scolaire"},
        "text_derivative": {"positive_ministry_author_or_publisher_proof_required": True,
            "accepted_publisher_proof_kinds": [
            "OFFICIAL_CAPTURED_DOWNLOAD_PUBLISHER", "OFFICIAL_PDF_AUTHOR_METADATA",
            "EXPLICIT_DOCUMENT_IMPRINT"]},
    }
    return packet, scan, provenance, derivative, policy


def decide(*, mutate=None) -> dict:
    packet, scan, provenance, derivative, policy = copy.deepcopy(evidence())
    if mutate is not None:
        mutate(packet, scan, provenance, derivative, policy)
    return adjudicate_derivative_candidate(
        packet, scan, provenance, derivative, policy,
        authority_sha256=AUTHORITY_SHA,
    )


def test_sitewide_authority_with_exact_source_allows_only_distinct_text_derivative() -> None:
    result = decide()
    assert result["source_disposition"] == "REPLACE_WITH_NEW_CONTENT"
    assert result["derivative_disposition"] == "APPROVE_PUBLIC"
    assert result["final_disposition"] == "REPLACE_WITH_NEW_CONTENT"
    assert result["replacement"]["new_content_sha256"] == DERIVATIVE_SHA


def test_python_http_403_does_not_negate_independent_sitewide_authority() -> None:
    result = decide()
    assert result["derivative_disposition"] == "APPROVE_PUBLIC"
    assert "OFFICIAL_TERMS_UNVERIFIABLE" not in result["reason_codes"]


def test_unproven_source_excludes_candidate() -> None:
    result = decide(mutate=lambda _p, _s, source, _d, _policy: source[
        "source_provenance"].update(status="SOURCE_UNPROVEN"))
    assert result["source_disposition"] == "EXCLUDE"
    assert result["derivative_disposition"] == "EXCLUDE"


def test_missing_revocation_evidence_excludes_candidate() -> None:
    result = decide(mutate=lambda _p, _s, source, _d, _policy: source[
        "source_provenance"].update(revocation_evidence_ref=None))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_missing_dated_revocation_observation_excludes_candidate() -> None:
    result = decide(mutate=lambda _p, _s, source, _d, _policy: source[
        "source_provenance"].update(revocation_observed_at_utc=None))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_individual_licence_without_its_own_receipt_cannot_borrow_sitewide_evidence() -> None:
    result = decide(mutate=lambda _p, _s, source, _d, _policy: source.update(
        rights_basis_kind="INDIVIDUAL_EXPLICIT_LICENCE"))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_derivative_cannot_reuse_pdf_sha() -> None:
    result = decide(mutate=lambda _p, _s, _source, derivative, _policy: derivative.update(
        derivative_content_sha256=SOURCE_SHA))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_selected_third_party_segment_excludes_derivative() -> None:
    result = decide(mutate=lambda _p, _s, _source, derivative, _policy: derivative[
        "pages"][0]["all_blocks"][0].update(block_class="THIRD_PARTY_TEXT_SUSPECT"))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_missing_attribution_date_excludes_derivative() -> None:
    result = decide(mutate=lambda _p, _s, _source, derivative, _policy: derivative[
        "source_attribution"].update(source_updated_at=""))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_missing_positive_publisher_proof_excludes_derivative() -> None:
    result = decide(mutate=lambda _p, _s, _source, derivative, _policy: derivative[
        "publisher_proof"].update(status="UNPROVEN"))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_publisher_status_must_match_structured_proof() -> None:
    result = decide(mutate=lambda _p, _s, _source, derivative, _policy: derivative.update(
        publisher_status="UNPROVEN"))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_captured_publisher_proof_cannot_point_to_another_pdf() -> None:
    result = decide(mutate=lambda _p, _s, _source, derivative, _policy: derivative[
        "publisher_proof"].update(source_content_sha256="9" * 64))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_snapshot_date_must_not_be_presented_as_editorial_update() -> None:
    result = decide(mutate=lambda _p, _s, source, derivative, _policy: (
        source["source_provenance"]["source_updated_at"].update(
            kind="DATED_OFFICIAL_SNAPSHOT", date="2026-09-01T00:00:00Z"),
        source["source_provenance"]["pdf_fetch"].update(
            observed_at_utc="2026-09-01T00:00:00Z"),
        derivative["source_attribution"].update(
            source_date_kind="DATED_OFFICIAL_SNAPSHOT",
            derivative_notice="Extrait textuel dérivé"),
        derivative["pages"][0]["all_blocks"][0]["citation"].update(
            source_date_kind="DATED_OFFICIAL_SNAPSHOT",
            derivative_notice="Extrait textuel dérivé"),
    ))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_date_kind_mismatch_excludes_derivative() -> None:
    result = decide(mutate=lambda _p, _s, _source, derivative, _policy: (
        derivative["source_attribution"].update(
            source_date_kind="DATED_OFFICIAL_SNAPSHOT"),
        derivative["pages"][0]["all_blocks"][0]["citation"].update(
            source_date_kind="DATED_OFFICIAL_SNAPSHOT"),
    ))
    assert result["derivative_disposition"] == "EXCLUDE"


def test_cftr_is_excluded_even_with_otherwise_positive_evidence() -> None:
    cftr = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
    def mutate(packet, scan, source, derivative, _policy):
        packet["content_sha256"] = cftr
        scan["content_sha256"] = cftr
        source["content_sha256"] = cftr
        source["source_provenance"]["pdf_fetch"]["content_sha256"] = cftr
        derivative["source_content_sha256"] = cftr
    result = decide(mutate=mutate)
    assert result["source_disposition"] == "EXCLUDE"
    assert result["derivative_disposition"] == "EXCLUDE"
    assert "TEACHER_NON_DISCLOSURE_INSTRUCTION" in result["reason_codes"]


def test_record_v2_keeps_pdf_source_private_and_binds_checkpoint_octets() -> None:
    packet, scan, provenance, derivative, policy = evidence()
    scan.update({
        "file_size_bytes": 100,
        "images_and_annexes_checked": True,
        "pages": [{
            "page_number": 1,
            "text_sha256": "d" * 64,
            "render_sha256": None,
            "ocr_sha256": None,
            "raster_image_count": 0,
            "vector_drawing_count": 0,
            "annotation_count": 0,
        }],
    })
    record = build_derivative_artifact_record(
        packet, scan, provenance, derivative, policy,
        source_checkpoint_sha256="e" * 64,
        derivative_receipt_sha256="f" * 64,
        authority_sha256=AUTHORITY_SHA,
        bindings={"inventory_sha256": "1" * 64},
        decided_at_utc="2026-10-10T06:00:00Z",
    )
    assert record["record_kind"] == "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V2"
    assert record["source_receipt_sha256"] == "e" * 64
    assert record["derivative_receipt_sha256"] == "f" * 64
    assert record["source_disposition"] == "REPLACE_WITH_NEW_CONTENT"
    assert record["final_disposition"] != "APPROVE_PUBLIC"
    assert record["derivative_disposition"] == "APPROVE_PUBLIC"


def test_excluded_cftr_record_keeps_exact_pdf_url_binding() -> None:
    packet, scan, provenance, derivative, policy = evidence()
    cftr = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
    packet.update(content_sha256=cftr,
                  source_listing_url="https://eduscol.education.gouv.fr/5835/programmes")
    scan.update(content_sha256=cftr, file_size_bytes=100,
                images_and_annexes_checked=True, pages=[{
                    "page_number": 1,
                    "text_sha256": "d" * 64,
                    "render_sha256": None,
                    "ocr_sha256": None,
                    "raster_image_count": 0,
                    "vector_drawing_count": 0,
                    "annotation_count": 0,
                }])
    provenance["content_sha256"] = cftr
    provenance["source_provenance"]["pdf_fetch"]["content_sha256"] = cftr
    derivative["source_attribution"] = {}

    record = build_derivative_artifact_record(
        packet, scan, provenance, derivative, policy,
        source_checkpoint_sha256="e" * 64,
        derivative_receipt_sha256="f" * 64,
        authority_sha256=AUTHORITY_SHA,
        bindings={"inventory_sha256": "1" * 64},
        decided_at_utc="2026-10-10T06:00:00Z",
    )
    assert record["source_disposition"] == "EXCLUDE"
    assert record["source_uri"] == SOURCE_URL


def test_candidate_manifest_counts_only_text_derivatives_and_real_placements() -> None:
    packet, _scan, provenance, derivative, _policy = evidence()
    packet["placements"] = [{"collection": "nsi_premiere"},
                            {"collection": "nsi_terminale"}]
    derivative["pages"][0]["review_groups"] = [{"group_index": 1}]
    other_sha = "9" * 64
    excluded_packet = {"content_sha256": other_sha,
                       "placements": [{"collection": "svt_premiere"}]}
    records = [
        {"content_sha256": SOURCE_SHA,
         "source_disposition": "REPLACE_WITH_NEW_CONTENT",
         "derivative_disposition": "APPROVE_PUBLIC",
         "derivative_content_sha256": DERIVATIVE_SHA,
         "derivative_receipt_sha256": "f" * 64},
        {"content_sha256": other_sha, "source_disposition": "EXCLUDE",
         "derivative_disposition": "EXCLUDE", "derivative_content_sha256": None,
         "derivative_receipt_sha256": "8" * 64},
    ]
    manifest = build_public_derivative_candidate_manifest(
        [packet, excluded_packet], records,
        {SOURCE_SHA: provenance}, {SOURCE_SHA: derivative},
        inventory_sha256="1" * 64,
        authority_sha256=AUTHORITY_SHA,
        extraction_policy_sha256="2" * 64,
    )
    assert manifest["status"] == "PRE_REVIEW_NOT_PROMOTABLE"
    assert manifest["counts"] == {
        "source_pdfs": 2,
        "public_collections": 2,
        "public_derivative_artifacts": 1,
        "public_placements": 2,
        "public_derivative_segments": 1,
        "original_pdf_public_count": 0,
    }
    assert manifest["entries"][0]["derivative_content_sha256"] == DERIVATIVE_SHA
    assert manifest["entries"][0]["media_type"] == "text/plain; charset=utf-8"
    assert manifest["excluded_source_sha256"] == [other_sha]


def test_sheet_v2_distinguishes_private_pdf_from_public_text_derivative() -> None:
    packet = {
        "content_sha256": SOURCE_SHA,
        "source_release": "v4_non_hggsp",
        "placements": [{"collection": "nsi_premiere"}],
        "source_path": "private.pdf",
        "source_listing_url": SOURCE_URL,
        "page_count": 1,
        "source_pii_status": "CLEARED",
        "source_currentness_disposition": "CURRENT",
        "automated_review_signals": [],
        "explicit_student_exclusion_signal": False,
    }
    record = {
        "content_sha256": SOURCE_SHA,
        "source_disposition": "REPLACE_WITH_NEW_CONTENT",
        "derivative_disposition": "APPROVE_PUBLIC",
        "final_disposition": "REPLACE_WITH_NEW_CONTENT",
        "derivative_content_sha256": DERIVATIVE_SHA,
        "derivative_receipt_sha256": "f" * 64,
        "rights_authority_id": "EDUSCOL_ETALAB_2_0_SITEWIDE",
        "rights_authority_sha256": AUTHORITY_SHA,
        "rights_basis": "SITEWIDE_DOWNLOAD_AUTHORITY",
        "evidence_pages": [1],
        "reason_codes": [],
        "decided_at_utc": "2026-10-10T06:00:00Z",
        "decision_executor": "nexus-delegated-student-rights-adjudicator-v1",
        "delegation_id": "nexus-student-public-rights-abenrhouma-20261009-v1",
    }
    sheet = render_derivative_decision_sheet([(record, packet, "e" * 64)]).decode()
    header, row = sheet.splitlines()
    assert "source_disposition" in header
    assert "derivative_disposition" in header
    assert "REPLACE_WITH_NEW_CONTENT" in row
    assert "APPROVE_PUBLIC" in row
    assert DERIVATIVE_SHA in row


def test_sheet_v2_uses_explicit_sentinel_for_unproven_authority() -> None:
    record = {
        "content_sha256": SOURCE_SHA,
        "source_disposition": "EXCLUDE",
        "derivative_disposition": "EXCLUDE",
        "final_disposition": "EXCLUDE",
        "rights_authority_id": None,
        "rights_authority_sha256": None,
        "evidence_pages": [],
        "reason_codes": ["SOURCE_UNPROVEN"],
    }
    sheet = render_derivative_decision_sheet([(record, {"content_sha256": SOURCE_SHA}, "f" * 64)])
    assert sheet.splitlines()[1].endswith(b"\tNONE\tNONE")


def test_derivative_pack_refuses_draft_policy_before_any_output(tmp_path: Path) -> None:
    import pytest

    root = tmp_path
    actual_root = Path(__file__).resolve().parents[2]
    governance = root / "governance/student_public_rights"
    governance.mkdir(parents=True)
    source = (actual_root / "governance/student_public_rights/delegated_review_policy_v1.yml")
    (governance / "delegated_review_policy_v1.yml").write_text(
        source.read_text().replace("status: SEALED_PENDING_FINAL_APPROVAL", "status: DRAFT_UNSEALED", 1)
    )
    mandate = (actual_root / "governance/student_public_rights/delegation_abenrhouma_20261009.yml")
    (governance / "delegation_abenrhouma_20261009.yml").write_bytes(mandate.read_bytes())
    with pytest.raises(ValueError, match="POLICY_OR_MANDATE_NOT_SEALED"):
        materialize_derivative_pack(
            root,
            scan_checkpoints=tmp_path / "scans",
            source_checkpoints=tmp_path / "provenance",
            derivative_checkpoints=tmp_path / "derivatives",
            private_candidate_root=tmp_path / "private",
            decided_at_utc="2026-10-10T06:00:00Z",
        )
