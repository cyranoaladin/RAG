"""Dérivé natif privé : preuve structurelle sans publication implicite."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import fitz
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from student_rights_text_derivative import (  # noqa: E402
    CFTR_SHA256, DerivativeError, build_text_candidate, run_derivative_batch,
    write_private_candidate,
)


def _source(path: Path) -> str:
    document = fitz.open()
    page = document.new_page(width=500, height=500)
    page.insert_text((100, 100), "SAFE_NATIVE_CANARY")
    page.insert_text((20, 35), "IMAGE_OVERLAP_CANARY")
    page.insert_text((100, 250), "Ne pas communiquer aux eleves TEACHER_CANARY")
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    pixmap.clear_with(255)
    page.insert_image(fitz.Rect(10, 10, 200, 60), pixmap=pixmap)
    document.set_metadata({"author": "Direction générale de l'enseignement scolaire"})
    document.save(path)
    document.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attribution() -> dict:
    return {
        "source_uri": "https://eduscol.education.gouv.fr/exact.pdf",
        "source_label": "Document pédagogique",
        "source_updated_at": "2026-10-09T12:00:00Z",
        "source_date_kind": "DATED_OFFICIAL_SNAPSHOT",
        "licensor": "Ministère de l'Éducation nationale – Dgesco / Éduscol",
        "licence_id": "Etalab-2.0",
        "derivative_notice": (
            "Dérivé textuel sans images, OCR graphique ni PDF public ; "
            "snapshot du 2026-10-09T12:00:00Z."
        ),
    }


def _packet(sha: str, *, signals: list[dict] | None = None,
            pii_status: str = "CLEARED", excluded: bool = False) -> dict:
    return {
        "content_sha256": sha, "page_count": 1,
        "automated_review_signals": signals if signals is not None else [],
        "source_pii_status": pii_status,
        "explicit_student_exclusion_signal": excluded,
    }


def test_native_derivative_excludes_raster_overlap_teacher_text_and_raw_evidence(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)

    candidate = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))

    assert candidate.content is not None
    assert b"SAFE_NATIVE_CANARY" in candidate.content
    assert b"IMAGE_OVERLAP_CANARY" not in candidate.content
    assert b"TEACHER_CANARY" not in candidate.content
    assert b"\x89PNG" not in candidate.content
    assert candidate.evidence["derivative_content_sha256"] == hashlib.sha256(
        candidate.content
    ).hexdigest()
    assert candidate.evidence["derivative_content_sha256"] != sha
    assert candidate.evidence["source_content_sha256"] == sha
    assert candidate.evidence["source_packet_artifact_sha256"] == hashlib.sha256(
        json.dumps(_packet(sha), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert candidate.evidence["publication_authorized"] is False
    assert candidate.evidence["ocr_used"] is False
    assert candidate.evidence["images_copied"] is False
    assert candidate.evidence["source_attribution"] == _attribution()
    policy = Path(__file__).resolve().parents[2] / (
        "governance/student_public_rights/text_derivative_extraction_policy_v1.yml"
    )
    assert candidate.evidence["extraction_policy_sha256"] == hashlib.sha256(
        policy.read_bytes()
    ).hexdigest()
    adjudication = Path(__file__).resolve().parents[2] / (
        "governance/student_public_rights/delegated_review_policy_v1.yml"
    )
    assert candidate.evidence["adjudication_policy_sha256"] == hashlib.sha256(
        adjudication.read_bytes()
    ).hexdigest()
    assert candidate.evidence["pages"][0]["page_number"] == 1
    assert candidate.evidence["pages"][0]["selected_block_indices"]
    selected = [block for block in candidate.evidence["pages"][0]["all_blocks"]
                if block["block_class"] == "SAFE_TEXT_CANDIDATE"]
    assert selected[0]["citation"] == {
        **_attribution(), "source_pdf_sha256": sha, "source_page": 1,
    }
    assert candidate.evidence["pages"][0]["review_groups"][0]["citation"] == {
        **_attribution(), "source_pdf_sha256": sha, "source_page": 1,
    }
    assert {
        item["block_class"] for item in candidate.evidence["pages"][0]["all_blocks"]
    } >= {"SAFE_TEXT_CANDIDATE", "EXCLUDED_NON_TEXT", "TEACHER_ONLY"}
    assert {
        item["reason_code"] for item in candidate.evidence["pages"][0]["excluded_blocks"]
    } >= {"RASTER_OVERLAP", "TEACHER_OR_NONDISCLOSURE_SIGNAL"}
    assert "SAFE_NATIVE_CANARY" not in json.dumps(candidate.evidence)
    assert "TEACHER_CANARY" not in json.dumps(candidate.evidence)
    assert len(candidate.review_groups) == 1
    assert candidate.review_groups[0].text == "SAFE_NATIVE_CANARY"


def test_candidate_offsets_reconstruct_page_bytes_and_are_deterministic(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)

    first = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))
    second = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))

    assert first.content == second.content
    assert first.evidence == second.evidence
    page = first.evidence["pages"][0]
    assert first.content.startswith(b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n")
    assert b"\n[PAGE 1 BLOCK " in first.content[page["byte_start"]:page["byte_end"]]
    assert b"SAFE_NATIVE_CANARY\n" in first.content[page["byte_start"]:page["byte_end"]]
    header_line = first.content.split(b"\n", 2)[1]
    assert json.loads(header_line)["source_pdf_sha256"] == sha
    assert json.loads(header_line)["source_date_kind"] == (
        "DATED_OFFICIAL_SNAPSHOT"
    )
    selected = [block for block in page["all_blocks"]
                if block["block_class"] == "SAFE_TEXT_CANDIDATE"]
    assert len(selected) == 1
    assert first.content[selected[0]["byte_start"]:selected[0]["byte_end"]] == (
        b"SAFE_NATIVE_CANARY"
    )
    citation_line = first.content[:selected[0]["byte_start"]].split(b"\n")[-2]
    assert json.loads(citation_line) == {
        **_attribution(), "source_pdf_sha256": sha, "source_page": 1,
    }
    group = page["review_groups"][0]
    assert first.content[group["byte_start"]:group["byte_end"]] == (
        b"SAFE_NATIVE_CANARY"
    )


def test_private_writer_seals_cas_receipt_without_raw_text(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)
    candidate = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))
    private_root = tmp_path / "private"
    evidence_root = tmp_path / "evidence"

    checkpoint = write_private_candidate(candidate, private_root, evidence_root)
    again = write_private_candidate(candidate, private_root, evidence_root)

    assert checkpoint == again
    assert checkpoint["kind"] == "NEXUS-STUDENT-DERIVATIVE-CHECKPOINT-V1"
    assert checkpoint["source_content_sha256"] == sha
    assert checkpoint["candidate_relpath"] == (
        f"candidates/{candidate.evidence['derivative_content_sha256']}.txt"
    )
    raw = (private_root / checkpoint["candidate_relpath"]).read_bytes()
    assert raw == candidate.content
    assert raw.startswith(b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n")
    assert os.stat(private_root / checkpoint["candidate_relpath"]).st_mode & 0o777 == 0o600
    receipt_path = evidence_root / "derivative_receipts" / checkpoint[
        "derivative_receipt_sha256"
    ][:2] / f"{checkpoint['derivative_receipt_sha256']}.json"
    receipt_bytes = receipt_path.read_bytes()
    assert hashlib.sha256(receipt_bytes).hexdigest() == checkpoint[
        "derivative_receipt_sha256"
    ]
    receipt = json.loads(receipt_bytes)
    assert receipt["generator_code_sha256"] == hashlib.sha256(
        (Path(__file__).resolve().parents[1] / "go_live/student_rights_text_derivative.py")
        .read_bytes()
    ).hexdigest()
    assert receipt["candidate_relpath"] == checkpoint["candidate_relpath"]
    assert "SAFE_NATIVE_CANARY" not in receipt_bytes.decode("utf-8")
    assert (evidence_root / "derivatives" / f"{sha}.json").read_bytes() == (
        json.dumps(checkpoint, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    )


def test_private_writer_rejects_content_and_receipt_tampering(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)
    candidate = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))
    private_root = tmp_path / "private"
    evidence_root = tmp_path / "evidence"
    checkpoint = write_private_candidate(candidate, private_root, evidence_root)
    (private_root / checkpoint["candidate_relpath"]).write_bytes(b"tampered")
    with pytest.raises(DerivativeError, match="PRIVATE_CANDIDATE_CONFLICT"):
        write_private_candidate(candidate, private_root, evidence_root)
    (private_root / checkpoint["candidate_relpath"]).write_bytes(candidate.content or b"")
    receipt = evidence_root / "derivative_receipts" / checkpoint[
        "derivative_receipt_sha256"
    ][:2] / f"{checkpoint['derivative_receipt_sha256']}.json"
    receipt.write_bytes(b"tampered")
    with pytest.raises(DerivativeError, match="DERIVATIVE_RECEIPT_CONFLICT"):
        write_private_candidate(candidate, private_root, evidence_root)


def test_private_writer_refuses_repository_output(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)
    candidate = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))
    repo_root = Path(__file__).resolve().parents[2]
    with pytest.raises(DerivativeError, match="PRIVATE_ROOT_INSIDE_REPOSITORY"):
        write_private_candidate(candidate, repo_root / "tmp-public-pdf-text", tmp_path)


def test_identical_native_text_from_distinct_pdf_bytes_has_distinct_derivative_sha(
    tmp_path: Path,
) -> None:
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    document = fitz.open()
    page = document.new_page(width=500, height=500)
    page.insert_text((100, 100), "SAFE_NATIVE_CANARY")
    document.set_metadata({"author": "Direction générale de l'enseignement scolaire"})
    document.save(pdf_a)
    document.set_metadata({"title": "Different container metadata"})
    document.save(pdf_b)
    document.close()
    sha_a = hashlib.sha256(pdf_a.read_bytes()).hexdigest()
    sha_b = hashlib.sha256(pdf_b.read_bytes()).hexdigest()
    assert sha_a != sha_b

    first = build_text_candidate(pdf_a, sha_a, 1, _attribution(), _packet(sha_a))
    second = build_text_candidate(pdf_b, sha_b, 1, _attribution(), _packet(sha_b))

    assert first.evidence["pages"][0]["selected_block_indices"] == (
        second.evidence["pages"][0]["selected_block_indices"]
    )
    assert first.evidence["derivative_content_sha256"] != second.evidence[
        "derivative_content_sha256"
    ]


def test_changed_pdf_and_missing_attribution_fail_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)

    with pytest.raises(DerivativeError, match="SOURCE_SHA256_MISMATCH"):
        build_text_candidate(pdf, "0" * 64, 1, _attribution(), _packet("0" * 64))
    with pytest.raises(DerivativeError, match="ATTRIBUTION_INCOMPLETE"):
        build_text_candidate(pdf, sha, 1, {**_attribution(), "source_updated_at": None},
                             _packet(sha))


def test_cftr_cannot_become_candidate_even_with_text(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    _source(pdf)
    result = build_text_candidate(pdf, CFTR_SHA256, 1, _attribution(),
                                  _packet(CFTR_SHA256))

    assert result.content is None
    assert result.review_groups == ()
    assert result.evidence["status"] == "EXCLUDE"
    assert result.evidence["reason_codes"] == ["CFTR_FORCED_EXCLUDE"]
    assert result.evidence["derivative_content_sha256"] is None


def test_blocked_original_review_page_cannot_contribute_text(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)

    result = build_text_candidate(
        pdf, sha, 1, _attribution(),
        _packet(sha, signals=[{"kind": "reproduction_or_third_party", "page": 1}]),
    )

    assert result.content is None
    assert result.evidence["status"] == "EXCLUDE"
    assert result.evidence["pages"][0]["selected_block_indices"] == []
    assert all(
        block["block_class"] != "SAFE_TEXT_CANDIDATE"
        for block in result.evidence["pages"][0]["all_blocks"]
    )


def test_historical_pii_accepted_for_internal_blocks_all_public_text(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    sha = _source(pdf)

    result = build_text_candidate(
        pdf, sha, 1, _attribution(),
        _packet(sha, pii_status="DETECTED_REVIEWED_ACCEPTED"),
    )

    assert result.content is None
    assert result.evidence["status"] == "EXCLUDE"
    assert result.evidence["pages"][0]["selected_block_indices"] == []


def test_native_label_overlapping_vector_diagram_is_excluded(tmp_path: Path) -> None:
    pdf = tmp_path / "vector.pdf"
    document = fitz.open()
    page = document.new_page(width=500, height=500)
    page.insert_text((80, 80), "SAFE_NATIVE_CANARY")
    page.insert_text((80, 200), "VECTOR_LABEL_CANARY")
    page.draw_rect(fitz.Rect(75, 170, 300, 220), color=(0, 0, 0))
    document.set_metadata({"author": "Direction générale de l'enseignement scolaire"})
    document.save(pdf)
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()

    candidate = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))

    assert candidate.content is not None
    assert b"SAFE_NATIVE_CANARY" in candidate.content
    assert b"VECTOR_LABEL_CANARY" not in candidate.content
    assert candidate.evidence["pages"][0]["vector_drawing_count"] >= 1
    assert "VECTOR_OVERLAP" in {
        item["reason_code"] for item in candidate.evidence["pages"][0]["excluded_blocks"]
    }


def _provenance(sha: str, authority_sha: str, *, exact: bool = True) -> dict:
    pdf_url = "https://eduscol.education.gouv.fr/ressources/exact.pdf"
    captured = "2026-10-10T08:00:00Z"
    receipt_sha = "a" * 64
    record = {
        "kind": "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1",
        "content_sha256": sha,
        "inventory_sha256": "b" * 64,
        "authority_yaml_sha256": authority_sha,
        "source_listing_url": "https://eduscol.education.gouv.fr/listing",
        "checked_at_utc": captured,
        "raw_http_status_diagnostic": 403,
        "source_provenance": {
            "status": "EXACT_CURRENT_SOURCE" if exact else "SOURCE_UNPROVEN",
            "matched_anchor": {"href": pdf_url, "label": "Titre source", "occurrence_index": 0},
            "pdf_fetch": {
                "requested_url": pdf_url, "final_url": pdf_url,
                "http_status": 200, "observed_at_utc": captured,
                "content_sha256": sha, "byte_count": 1000,
            },
            "source_updated_at": {
                "date": captured,
                "kind": "DATED_OFFICIAL_SNAPSHOT",
                "evidence_ref": {
                    "pdf_url": pdf_url,
                    "downloaded_sha256": sha,
                    "http_status": 200,
                    "listing_capture_receipt_sha256": receipt_sha,
                },
            },
            "historical_capture": None,
            "reason_codes": [] if exact else ["NO_EXACT_CURRENT_PDF_LINK"],
            "listing_capture_receipt_relpath": "provenance/listings/synthetic.receipt.json",
            "listing_capture_receipt_sha256": receipt_sha,
            "currentness_status": "PASS",
            "currentness_evidence_ref": {
                "listing_capture_receipt_sha256": receipt_sha,
                "pdf_sha256": sha, "pdf_url": pdf_url,
            },
            "currentness_observed_at_utc": captured,
            "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
            "revocation_evidence_ref": {
                "listing_capture_receipt_sha256": receipt_sha,
                "pdf_sha256": sha, "pdf_url": pdf_url,
                "notice_scan": "NO_RETRACTION_NOTICE_FOUND",
            },
            "revocation_observed_at_utc": captured,
            "retraction_notice_associated": False,
        },
        "rights_basis_kind": "SITEWIDE_DOWNLOAD_AUTHORITY" if exact else "NONE",
        "rights_basis_status": (
            "CANDIDATE_PENDING_FINAL_APPROVAL" if exact else "SOURCE_UNPROVEN"
        ),
    }
    record["checkpoint_sha256"] = hashlib.sha256(
        (json.dumps(record, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False) + "\n").encode("utf-8")
    ).hexdigest()
    return record


def test_batch_uses_exact_provenance_and_excludes_unproven_without_fake_date(
    tmp_path: Path,
) -> None:
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    first_pdf = mirror / "exact.pdf"
    second_pdf = mirror / "unproven.pdf"
    first_document = fitz.open()
    first_document.new_page(width=500, height=500).insert_text(
        (100, 100), "SAFE_NATIVE_CANARY"
    )
    first_document.save(first_pdf)
    first_document.close()
    first_sha = hashlib.sha256(first_pdf.read_bytes()).hexdigest()
    second_sha = _source(second_pdf)
    authority = tmp_path / "authority.yml"
    authority.write_text(
        "authority_kind: SITEWIDE_DOWNLOAD_AUTHORITY\n"
        "status: SEALED_PENDING_FINAL_EXACT_HEAD_APPROVAL\n"
        "licensor: Direction générale de l'enseignement scolaire\n"
        "licence_id: ETALAB-2.0\n"
    )
    authority_sha = hashlib.sha256(authority.read_bytes()).hexdigest()
    provenance_dir = tmp_path / "provenance"
    provenance_dir.mkdir()
    for sha, exact in ((first_sha, True), (second_sha, False)):
        (provenance_dir / f"{sha}.json").write_text(
            json.dumps(_provenance(sha, authority_sha, exact=exact))
        )
    artifacts = []
    for sha, path in ((first_sha, first_pdf), (second_sha, second_pdf)):
        artifacts.append({
            **_packet(sha), "source_path": path.name,
            "source_listing_url": "https://eduscol.education.gouv.fr/listing",
            "title": "Synthetic exact source",
        })
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps({"artifacts": artifacts}))

    summary = run_derivative_batch(
        packet, mirror, provenance_dir, authority,
        tmp_path / "private", tmp_path / "evidence", expected_count=2,
    )

    assert summary["inventory_count"] == 2
    assert summary["private_candidates"] == 1
    assert summary["excluded"] == 1
    first = json.loads((tmp_path / "evidence/derivatives" / f"{first_sha}.json").read_text())
    second = json.loads((tmp_path / "evidence/derivatives" / f"{second_sha}.json").read_text())
    assert first["status"] == "PREPARED_PRIVATE"
    assert second["status"] == "EXCLUDE"
    assert second["candidate_relpath"] is None
    assert not (tmp_path / "private/candidates" / f"{second_sha}.txt").exists()
    source_text = (tmp_path / "private" / first["candidate_relpath"]).read_text()
    assert "snapshot du 2026-10-10T08:00:00Z" in source_text
    assert "Synthetic exact source" in source_text
    assert "Source : Ministère de l’Éducation nationale – Dgesco / Éduscol" in source_text
    first_receipt = json.loads((
        tmp_path / "evidence/derivative_receipts" /
        first["derivative_receipt_sha256"][:2] /
        f"{first['derivative_receipt_sha256']}.json"
    ).read_text())
    assert first_receipt["rights_authority_sha256"] == authority_sha
    assert first_receipt["source_provenance_checkpoint_sha256"] == _provenance(
        first_sha, authority_sha
    )["checkpoint_sha256"]
    assert first_receipt["publisher_proof"] == {
        "status": "PASS",
        "kind": "OFFICIAL_CAPTURED_DOWNLOAD_PUBLISHER",
        "listing_capture_receipt_sha256": "a" * 64,
        "source_provenance_checkpoint_sha256": _provenance(
            first_sha, authority_sha
        )["checkpoint_sha256"],
        "rights_authority_sha256": authority_sha,
        "source_content_sha256": first_sha,
        "matched_anchor_href": "https://eduscol.education.gouv.fr/ressources/exact.pdf",
        "source_pdf_url": "https://eduscol.education.gouv.fr/ressources/exact.pdf",
    }


def test_batch_rejects_source_mirror_path_traversal(tmp_path: Path) -> None:
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps({"artifacts": [{
        **_packet("f" * 64), "source_path": "../escape.pdf",
        "source_listing_url": "https://eduscol.education.gouv.fr/listing",
        "title": "Synthetic",
    }]}))
    authority = tmp_path / "authority.yml"
    authority.write_text("status: SEALED_PENDING_FINAL_EXACT_HEAD_APPROVAL\n")

    with pytest.raises(DerivativeError, match="SOURCE_PATH_ESCAPE"):
        run_derivative_batch(
            packet, tmp_path / "mirror", tmp_path / "provenance", authority,
            tmp_path / "private", tmp_path / "evidence", expected_count=1,
        )


def test_stale_or_revoked_provenance_cannot_prepare_derivative() -> None:
    from student_rights_text_derivative import _attribution_from_provenance

    sha = "f" * 64
    authority_sha = "a" * 64
    authority = {
        "authority_kind": "SITEWIDE_DOWNLOAD_AUTHORITY",
        "status": "SEALED_PENDING_FINAL_EXACT_HEAD_APPROVAL",
        "licensor": "Synthetic licensor", "licence_id": "ETALAB-2.0",
    }
    artifact = {
        "content_sha256": sha,
        "source_listing_url": "https://eduscol.education.gouv.fr/listing",
        "title": "Synthetic",
    }
    checkpoint = _provenance(sha, authority_sha)
    assert _attribution_from_provenance(artifact, checkpoint, authority, authority_sha)
    checkpoint["source_provenance"]["currentness_status"] = "FAIL"
    assert _attribution_from_provenance(artifact, checkpoint, authority, authority_sha) is None
    checkpoint.pop("checkpoint_sha256")
    checkpoint["checkpoint_sha256"] = hashlib.sha256(
        (json.dumps(checkpoint, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False) + "\n").encode("utf-8")
    ).hexdigest()
    assert _attribution_from_provenance(artifact, checkpoint, authority, authority_sha) is None


def test_no_positive_publisher_proof_excludes_native_text(tmp_path: Path) -> None:
    pdf = tmp_path / "no-publisher.pdf"
    document = fitz.open()
    page = document.new_page(width=500, height=500)
    page.insert_text((100, 100), "SAFE_NATIVE_CANARY")
    document.save(pdf)
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()

    candidate = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))

    assert candidate.content is None
    assert candidate.evidence["status"] == "EXCLUDE"
    assert candidate.evidence["publisher_proof"]["status"] == "UNPROVEN"
    assert "PUBLISHER_NOT_PROVEN" in {
        item["reason_code"] for item in candidate.evidence["pages"][0]["excluded_blocks"]
    }


def test_third_party_credit_in_separate_footer_blocks_whole_page(tmp_path: Path) -> None:
    pdf = tmp_path / "third-party-credit.pdf"
    document = fitz.open()
    first = document.new_page(width=500, height=500)
    first.insert_text((100, 100), "SAFE_PAGE_ONE_CANARY")
    first.insert_text((50, 470), "Credit photo : Editions Nathan")
    second = document.new_page(width=500, height=500)
    second.insert_text((100, 100), "SAFE_PAGE_TWO_CANARY")
    document.set_metadata({"author": "Direction générale de l'enseignement scolaire"})
    document.save(pdf)
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    packet = {**_packet(sha), "page_count": 2}

    candidate = build_text_candidate(pdf, sha, 2, _attribution(), packet)

    assert candidate.content is not None
    assert b"SAFE_PAGE_ONE_CANARY" not in candidate.content
    assert b"SAFE_PAGE_TWO_CANARY" in candidate.content
    assert candidate.evidence["pages"][0]["third_party_page_signal"] is True
    assert candidate.evidence["pages"][1]["third_party_page_signal"] is False
    assert "THIRD_PARTY_PAGE_SIGNAL" in {
        item["reason_code"] for item in candidate.evidence["pages"][0]["excluded_blocks"]
    }
    assert all(
        item["block_class"] == "THIRD_PARTY_TEXT_SUSPECT"
        for item in candidate.evidence["pages"][0]["excluded_blocks"]
        if item["block_type"] == 0
    )


def test_long_quotation_excluded_but_separate_native_block_retained(tmp_path: Path) -> None:
    pdf = tmp_path / "long-quotation.pdf"
    document = fitz.open()
    page = document.new_page(width=500, height=500)
    page.insert_text((100, 100), "SAFE_NATIVE_CANARY")
    page.insert_textbox(
        fitz.Rect(30, 150, 450, 280),
        "«" + "citation tierce longue " * 8 + "»",
    )
    document.set_metadata({"author": "Direction générale de l'enseignement scolaire"})
    document.save(pdf)
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()

    candidate = build_text_candidate(pdf, sha, 1, _attribution(), _packet(sha))

    assert candidate.content is not None
    assert b"SAFE_NATIVE_CANARY" in candidate.content
    assert b"citation tierce longue" not in candidate.content
    assert "THIRD_PARTY_SIGNAL" in {
        item["reason_code"] for item in candidate.evidence["pages"][0]["excluded_blocks"]
    }


def test_extraction_policy_regexes_match_executable_classifier() -> None:
    from student_rights_text_derivative import (
        _FIRST_PARTY_COPYRIGHT, _LONG_QUOTE, _OFFICIAL_PUBLISHER, _PUBLISHER_IMPRINT,
        _THIRD_PARTY, _THIRD_PARTY_PAGE,
    )

    policy = yaml.safe_load((
        Path(__file__).resolve().parents[2] /
        "governance/student_public_rights/text_derivative_extraction_policy_v1.yml"
    ).read_text())
    classes = policy["classification"]
    assert classes["publisher_name_regex"] == _OFFICIAL_PUBLISHER.pattern
    assert classes["publisher_imprint_regex"] == _PUBLISHER_IMPRINT.pattern
    assert classes["first_party_copyright_regex"] == _FIRST_PARTY_COPYRIGHT.pattern
    assert classes["third_party_block_regex"] == _THIRD_PARTY.pattern
    assert classes["third_party_page_regex"] == _THIRD_PARTY_PAGE.pattern
    assert classes["long_quotation_regex"] == _LONG_QUOTE.pattern


def test_official_copyright_kept_but_third_party_copyright_blocks_page(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "copyright.pdf"
    document = fitz.open()
    official = document.new_page(width=500, height=500)
    official.insert_text((50, 60), "© DGESCO")
    official.insert_text((50, 120), "OFFICIAL_SAFE_CANARY")
    third = document.new_page(width=500, height=500)
    third.insert_text((50, 60), "© Editions Nathan")
    third.insert_text((50, 120), "THIRD_PARTY_PAGE_CANARY")
    document.save(pdf)
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    packet = {**_packet(sha), "page_count": 2}

    candidate = build_text_candidate(pdf, sha, 2, _attribution(), packet)

    assert candidate.content is not None
    assert b"OFFICIAL_SAFE_CANARY" in candidate.content
    assert "© DGESCO".encode() in candidate.content
    assert b"THIRD_PARTY_PAGE_CANARY" not in candidate.content
    assert candidate.evidence["publisher_proof"]["kind"] == "EXPLICIT_DOCUMENT_IMPRINT"
    assert candidate.evidence["pages"][0]["third_party_page_signal"] is False
    assert candidate.evidence["pages"][1]["third_party_page_signal"] is True
