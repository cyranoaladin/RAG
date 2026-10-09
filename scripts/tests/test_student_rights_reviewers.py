"""Double revue sans partage de contexte ni approbation sur une image invisible."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
import base64
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from student_rights_reviewers import (  # noqa: E402
    OllamaTransport, ReviewError, _observation_schema, _project_metadata, _residual_ocr,
    _rights_signal_from_source, _segments, main, review_document, run_review_batch,
)


def _pdf(path: Path, *, pages: int = 2, graphic: bool = False, long_text: bool = False) -> str:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=320, height=320)
        text = "PRIVATE_REVIEW_CANARY " + ("word " * 60 if long_text else f"page {i + 1}")
        page.insert_text((20, 40), text, fontsize=6)
        if graphic:
            page.draw_rect(fitz.Rect(40, 80, 140, 180), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(path)
    doc.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeModel:
    def __init__(
        self, *, confidence: str = "HIGH", missing_page: int | None = None,
        reason_codes: dict[int, list[str]] | None = None,
        rights_pages: set[int] | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.confidence = confidence
        self.missing_page = missing_page
        self.reason_codes = reason_codes or {}
        self.rights_pages = rights_pages if rights_pages is not None else {1}
        self.supports_vision = True

    def __call__(
        self, model_id: str, system_prompt: str, user_payload: dict,
        parameters: dict, image_png: bytes | None,
    ) -> dict:
        self.calls.append(
            {
                "model_id": model_id,
                "system_prompt": system_prompt,
                "payload": user_payload,
                "parameters": parameters,
                "image_seen": image_png is not None,
                "image_size": struct.unpack(">II", image_png[16:24]) if image_png else None,
            }
        )
        page = user_payload["page_number"]
        response = {
            "page_number": page,
            "segment_index": user_payload["segment_index"],
            "segment_count": user_payload["segment_count"],
            "verdict": "PASS",
            "confidence": self.confidence,
            "reason_codes": self.reason_codes.get(page, []),
            "evidence_pages": [] if page == self.missing_page else [page],
            "visual_examined": image_png is not None,
        }
        if user_payload["review_domain"] == "reviewer_a":
            response["positive_rights_notice_present"] = page in self.rights_pages
        return response


def _run(path: Path, sha: str, model: FakeModel, **kwargs) -> dict:
    return review_document(
        path,
        sha,
        transport=model,
        model_id="qwen3-vl:2b",
        model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17},
        rights_evidence_positive=True,
        **kwargs,
    )


def test_two_reviewers_cover_all_text_pages_in_independent_contexts(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path)
    model = FakeModel()

    result = _run(path, sha, model)

    a, b = result["reviewer_a"], result["reviewer_b"]
    assert len(model.calls) == 4
    assert a["identity"] != b["identity"]
    assert a["prompt_sha256"] != b["prompt_sha256"]
    assert a["context_sha256"] != b["context_sha256"]
    assert a["pages_covered"] == b["pages_covered"] == [1, 2]
    assert a["complete"] is b["complete"] is True
    assert a["verdict"] == b["verdict"] == "PASS"
    assert len({c["system_prompt"] for c in model.calls}) == 2
    assert all(
        "reviewer_a" not in json.dumps(c["payload"])
        for c in model.calls if c["payload"]["review_domain"] == "reviewer_b"
    )
    assert "PRIVATE_REVIEW_CANARY" not in json.dumps(result)


def test_graphic_page_without_actual_vision_cannot_pass(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "graphic.pdf"
    sha = _pdf(path, pages=1, graphic=True)
    model = FakeModel()
    import student_rights_reviewers as reviewers

    monkeypatch.setattr(reviewers, "_ocr_text", lambda _png: "")
    result = _run(path, sha, model, vision_enabled=False)

    assert all(not call["image_seen"] for call in model.calls)
    assert result["reviewer_a"]["verdict"] == "FAIL"
    assert result["reviewer_b"]["verdict"] == "FAIL"
    assert result["reviewer_a"]["complete"] is False
    assert result["diagnostics"]["reviewer_a"]["visual_pages_unverified"] == [1]


def test_graphic_page_passes_visual_coverage_only_when_render_sent_to_vision_model(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "graphic.pdf"
    sha = _pdf(path, pages=1, graphic=True)
    model = FakeModel()
    import student_rights_reviewers as reviewers

    monkeypatch.setattr(reviewers, "_ocr_text", lambda _png: "")
    result = _run(path, sha, model, vision_enabled=True)

    assert len(model.calls) == 4
    for domain in ("reviewer_a", "reviewer_b"):
        calls = [call for call in model.calls if call["payload"]["review_domain"] == domain]
        assert [call["image_seen"] for call in calls] == [True, False]
        assert calls[0]["payload"]["page_text_segment"].startswith("[PDF_PAGE_RENDER_SHA256:")
        assert len(calls[0]["payload"]["page_text_segment"]) < 100
        assert "PRIVATE_REVIEW_CANARY" in calls[1]["payload"]["page_text_segment"]
        assert calls[0]["payload"]["segment_count"] == 2
    assert result["reviewer_a"]["complete"] is True
    assert result["reviewer_b"]["complete"] is True
    assert result["reviewer_a"]["verdict"] == "PASS"
    assert result["reviewer_b"]["verdict"] == "PASS"


def test_dedicated_visual_segment_does_not_truncate_long_text(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "graphic-long-metadata.pdf"
    _pdf(path, pages=1, graphic=True)
    document = fitz.open(path)
    document.set_xml_metadata(
        "<root><rights>" + "X" * 4500 + "RIGHTS_TAIL_CANARY" + "</rights></root>"
    )
    document.saveIncr()
    document.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    import student_rights_reviewers as reviewers

    monkeypatch.setattr(reviewers, "_ocr_text", lambda _png: "")
    model = FakeModel()
    result = _run(path, sha, model, vision_enabled=True)

    a_calls = [call for call in model.calls if call["payload"]["review_domain"] == "reviewer_a"]
    assert a_calls[0]["image_seen"] is True
    assert len(a_calls[0]["payload"]["page_text_segment"]) < 100
    assert all(not call["image_seen"] for call in a_calls[1:])
    reviewed_text = "".join(call["payload"]["page_text_segment"] for call in a_calls[1:])
    assert reviewed_text.count("X") >= 4500
    assert "RIGHTS_TAIL_CANARY" in reviewed_text
    assert result["reviewer_a"]["complete"] is True
    assert "RIGHTS_TAIL_CANARY" not in json.dumps(result)


def test_text_segment_cannot_claim_visual_inspection(tmp_path: Path) -> None:
    path = tmp_path / "text-only.pdf"
    sha = _pdf(path, pages=1)
    model = FakeModel()

    def contradictory(model_id, system_prompt, payload, parameters, image_png):
        observation = model(model_id, system_prompt, payload, parameters, image_png)
        observation["visual_examined"] = True
        return observation

    contradictory.supports_vision = True
    result = review_document(
        path, sha, transport=contradictory, model_id="granite3.2-vision:2b",
        model_version="sha256:test-model", parameters={"temperature": 0, "seed": 17},
        vision_enabled=True,
    )

    assert result["reviewer_a"]["complete"] is False
    assert result["reviewer_b"]["complete"] is False
    assert result["diagnostics"]["reviewer_a"]["error_codes"] == ["MODEL_INVALID_OUTPUT"]
    assert _observation_schema({"page_number": 1, "segment_index": 1,
                                "segment_count": 1, "review_domain": "reviewer_a"},
                               image_present=False)["properties"]["visual_examined"] == {"const": False}


def test_low_confidence_or_missing_page_is_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path)

    low = _run(path, sha, FakeModel(confidence="LOW"))
    missing = _run(path, sha, FakeModel(missing_page=2))

    assert low["reviewer_a"]["verdict"] == "FAIL"
    assert low["reviewer_b"]["confidence"] == "LOW"
    assert missing["reviewer_a"]["verdict"] == "FAIL"
    assert missing["reviewer_b"]["complete"] is False


def test_timeout_for_one_reviewer_does_not_fabricate_its_result(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)
    model = FakeModel()

    def timeout_a(model_id, system_prompt, user_payload, parameters, image_png):
        if "REVUE_A" in system_prompt:
            raise TimeoutError("PRIVATE_TIMEOUT_DETAIL")
        return model(model_id, system_prompt, user_payload, parameters, image_png)

    timeout_a.supports_vision = True
    result = review_document(
        path, sha, transport=timeout_a, model_id="qwen3-vl:2b",
        model_version="sha256:test-model", parameters={"temperature": 0, "seed": 17},
        rights_evidence_positive=True,
    )

    assert result["reviewer_a"]["complete"] is False
    assert result["reviewer_a"]["verdict"] == "FAIL"
    assert result["reviewer_b"]["complete"] is True
    assert "PRIVATE_TIMEOUT_DETAIL" not in json.dumps(result)


def test_long_page_is_segmented_without_truncation(tmp_path: Path) -> None:
    text = "A" * 4001
    chunks = _segments(text, 4000)

    assert chunks == ["A" * 4000, "A"]
    assert "".join(chunks) == text


def test_context_digest_changes_when_model_version_changes(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)
    first = _run(path, sha, FakeModel())
    second = review_document(
        path, sha, transport=FakeModel(), model_id="qwen3-vl:2b",
        model_version="sha256:another-model", parameters={"temperature": 0, "seed": 17},
        rights_evidence_positive=True,
    )

    assert first["reviewer_a"]["context_sha256"] != second["reviewer_a"]["context_sha256"]


def test_source_changed_during_review_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)
    model = FakeModel()

    def changing_model(model_id, system_prompt, user_payload, parameters, image_png):
        result = model(model_id, system_prompt, user_payload, parameters, image_png)
        if len(model.calls) == 1:
            with path.open("ab") as stream:
                stream.write(b"changed")
        return result

    changing_model.supports_vision = True
    with pytest.raises(ReviewError, match="PDF_CHANGED_DURING_REVIEW"):
        review_document(
            path, sha, transport=changing_model, model_id="qwen3-vl:2b",
            model_version="sha256:test-model", parameters={"temperature": 0, "seed": 17},
            rights_evidence_positive=True,
        )


def test_checkpoint_resumes_without_reusing_raw_document_text(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)
    checkpoint = tmp_path / "checkpoints"
    first_model = FakeModel()
    first = _run(path, sha, first_model, checkpoint_dir=checkpoint)
    second_model = FakeModel()

    second = _run(path, sha, second_model, checkpoint_dir=checkpoint)

    assert len(first_model.calls) == 2
    assert second_model.calls == []
    assert first["reviewer_a"] == second["reviewer_a"]
    assert first["reviewer_b"] == second["reviewer_b"]
    assert "PRIVATE_REVIEW_CANARY" not in "".join(
        file.read_text() for file in checkpoint.rglob("*.json")
    )


def test_segment_size_cannot_be_raised_above_fixed_budget(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)

    with pytest.raises(ReviewError, match="REVIEW_PARAMETERS_INVALID"):
        _run(path, sha, FakeModel(), max_chars_per_segment=4001)
    with pytest.raises(ReviewError, match="REVIEW_PARAMETERS_INVALID"):
        _run(path, sha, FakeModel(), max_chars_per_segment=3999)
    with pytest.raises(ReviewError, match="REVIEW_PARAMETERS_INVALID"):
        _run(path, sha, FakeModel(), vision_render_scale=1.5)


def test_metadata_and_annotation_content_reach_reviewers_but_not_output(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    _pdf(path, pages=1)
    doc = fitz.open(path)
    doc.set_metadata({"title": "PRIVATE_METADATA_CANARY"})
    doc[0].add_text_annot((40, 40), "PRIVATE_ANNOTATION_CANARY")
    doc.saveIncr()
    doc.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    model = FakeModel()

    result = _run(path, sha, model)

    payloads = json.dumps([call["payload"] for call in model.calls])
    assert "PRIVATE_METADATA_CANARY" in payloads
    assert "PRIVATE_ANNOTATION_CANARY" in payloads
    assert "PRIVATE_METADATA_CANARY" not in json.dumps(result)
    assert "PRIVATE_ANNOTATION_CANARY" not in json.dumps(result)


def test_embedded_file_is_not_silently_skipped(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    _pdf(path, pages=1)
    doc = fitz.open(path)
    doc.embfile_add("annex.txt", b"PRIVATE_ATTACHMENT_CANARY")
    doc.saveIncr()
    doc.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ReviewError, match="PDF_EMBEDDED_FILES_UNSUPPORTED"):
        _run(path, sha, FakeModel())


def test_reason_codes_are_aggregated_by_exact_page_without_document_text(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=2)
    model = FakeModel(reason_codes={2: ["TEACHER_NON_DISCLOSURE_INSTRUCTION"]})

    result = _run(path, sha, model)

    assert result["restriction_signals"] == [
        {"code": "TEACHER_NON_DISCLOSURE_INSTRUCTION", "pages": [2]}
    ]
    assert "PRIVATE_REVIEW_CANARY" not in json.dumps(result)


def test_positive_rights_pages_are_only_reported_from_explicit_a_observations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=2)
    model = FakeModel(rights_pages={2})

    result = _run(path, sha, model)

    assert result["rights_evidence_pages"] == [2]
    assert result["reviewer_a"]["verdict"] == "PASS"
    assert result["reviewer_b"]["verdict"] == "PASS"


def test_invalid_model_shape_has_specific_non_disclosing_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)
    model = FakeModel()

    def malformed(model_id, system_prompt, user_payload, parameters, image_png):
        value = model(model_id, system_prompt, user_payload, parameters, image_png)
        value.pop("evidence_pages")
        return value

    malformed.supports_vision = True
    result = review_document(
        path, sha, transport=malformed, model_id="qwen3-vl:2b",
        model_version="sha256:test-model", parameters={"temperature": 0, "seed": 17},
        rights_evidence_positive=True,
    )

    assert result["reviewer_a"]["complete"] is False
    assert result["diagnostics"]["reviewer_a"]["error_codes"] == ["MODEL_INVALID_OUTPUT"]


def test_receipts_are_cas_hashed_and_contain_no_pdf_text(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)
    receipt_dir = tmp_path / "receipts"

    result = _run(path, sha, FakeModel(), receipt_dir=receipt_dir)

    refs = result["reviewer_a"]["evidence_refs"] + result["reviewer_b"]["evidence_refs"]
    assert len(refs) == 2
    assert all(ref.startswith("sha256:") for ref in refs)
    for ref in refs:
        receipt_sha = ref.split(":", 1)[1]
        file = receipt_dir / receipt_sha[:2] / f"{receipt_sha}.json"
        raw = file.read_bytes()
        receipt = json.loads(raw)
        assert hashlib.sha256(raw).hexdigest() == receipt_sha
        assert receipt["content_sha256"] == sha
        assert receipt["request_sha256"]
        assert receipt["observation_sha256"] == hashlib.sha256(
            json.dumps(receipt["observation"], sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert receipt["image_sha256"] is None
        assert "PRIVATE_REVIEW_CANARY" not in raw.decode("utf-8")


def test_cached_observations_can_regenerate_same_receipts(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha = _pdf(path, pages=1)
    cache = tmp_path / "cache"
    first_dir = tmp_path / "receipts_a"
    second_dir = tmp_path / "receipts_b"
    first = _run(path, sha, FakeModel(), checkpoint_dir=cache, receipt_dir=first_dir)
    model = FakeModel()

    second = _run(path, sha, model, checkpoint_dir=cache, receipt_dir=second_dir)

    assert model.calls == []
    for label in ("reviewer_a", "reviewer_b"):
        assert first[label]["evidence_refs"] == second[label]["evidence_refs"]
        for ref in second[label]["evidence_refs"]:
            digest = ref.split(":", 1)[1]
            assert (second_dir / digest[:2] / f"{digest}.json").is_file()


def test_vision_render_can_be_bounded_to_half_scale_without_changing_pdf_scan(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "graphic.pdf"
    sha = _pdf(path, pages=1, graphic=True)
    import student_rights_reviewers as reviewers

    monkeypatch.setattr(reviewers, "_ocr_text", lambda _png: "")
    model = FakeModel()

    result = _run(
        path, sha, model, vision_enabled=True, vision_render_scale=0.5,
        receipt_dir=tmp_path / "receipts",
    )

    assert [call["image_size"] for call in model.calls] == [
        (160, 160), None, (160, 160), None,
    ]
    assert result["reviewer_a"]["complete"] is True


def test_batch_reviews_selected_sha_with_checkpointed_private_summary_and_receipts(
    tmp_path: Path,
) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    pdf = objects / "artifact.pdf"
    sha = _pdf(pdf, pages=1)
    pdf.rename(objects / sha)
    inventory = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    inventory.write_text(json.dumps({
        "artifacts": [{"content_sha256": value, "page_count": 1,
                       "source_path": value} for value in shas]
    }))
    model = FakeModel()

    first = run_review_batch(
        inventory, objects, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=model,
    )
    second_model = FakeModel()
    second = run_review_batch(
        inventory, objects, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=second_model,
    )

    assert first["reviewed"] == [sha]
    assert second["reused"] == [sha]
    assert second_model.calls == []
    summary_path = tmp_path / "pack" / "reviews" / f"{sha}.json"
    summary = json.loads(summary_path.read_bytes())
    assert summary["content_sha256"] == sha
    assert summary["reviewer_code_sha256"] == hashlib.sha256(
        (Path(__file__).resolve().parents[1] / "go_live/student_rights_reviewers.py").read_bytes()
    ).hexdigest()
    assert summary["model_id"] == "qwen3-vl:2b"
    assert summary["model_version"] == "sha256:test-model"
    assert summary["pii_status"] == "PASS"
    assert summary["third_party_status"] == "UNVERIFIABLE"
    assert summary["reviewer_a"]["evidence_refs"][0].startswith("sha256:")
    assert summary["reviewer_b"]["evidence_refs"][0].startswith("sha256:")
    assert summary_path.stat().st_mode & 0o077 == 0
    assert "PRIVATE_REVIEW_CANARY" not in summary_path.read_text()


def test_batch_rejects_unknown_sha_and_duplicate_inventory(tmp_path: Path) -> None:
    packet = tmp_path / "inventory.json"
    shas = [f"{number:064x}" for number in range(315)]
    packet.write_text(json.dumps({
        "artifacts": [{"content_sha256": sha, "page_count": 1,
                       "source_path": sha} for sha in shas]
    }))
    with pytest.raises(ReviewError, match="REVIEW_SHA_NOT_IN_INVENTORY"):
        run_review_batch(
            packet, tmp_path, tmp_path / "pack", artifact_sha256="f" * 64,
            model_id="qwen3-vl:2b", model_version="sha256:test-model",
            parameters={"temperature": 0, "seed": 17}, transport=FakeModel(),
        )
    shas[-1] = shas[0]
    packet.write_text(json.dumps({
        "artifacts": [{"content_sha256": sha, "page_count": 1,
                       "source_path": sha} for sha in shas]
    }))
    with pytest.raises(ReviewError, match="REVIEW_INVENTORY_INVALID"):
        run_review_batch(
            packet, tmp_path, tmp_path / "pack", artifact_sha256=shas[0],
            model_id="qwen3-vl:2b", model_version="sha256:test-model",
            parameters={"temperature": 0, "seed": 17}, transport=FakeModel(),
        )


def test_incomplete_batch_summary_is_retried_instead_of_reused(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    pdf = objects / "artifact.pdf"
    sha = _pdf(pdf, pages=1, graphic=True)
    pdf.rename(objects / sha)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [{"content_sha256": value, "page_count": 1,
                       "source_path": value} for value in shas]
    }))
    first_model = FakeModel()
    first_model.supports_vision = False
    first = run_review_batch(
        packet, objects, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17},
        transport=first_model,
    )
    second_model = FakeModel()
    second = run_review_batch(
        packet, objects, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=second_model,
    )

    assert first["reviewed"] == second["reviewed"] == [sha]
    assert first["incomplete"] == [sha]
    assert second["incomplete"] == []
    assert second["reused"] == []
    assert len(second_model.calls) == 2


def test_batch_cache_does_not_hide_pdf_byte_substitution(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    pdf = objects / "artifact.pdf"
    sha = _pdf(pdf, pages=1)
    pdf.rename(objects / sha)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [{"content_sha256": value, "page_count": 1,
                       "source_path": value} for value in shas]
    }))
    run_review_batch(
        packet, objects, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=FakeModel(),
    )
    with (objects / sha).open("ab") as stream:
        stream.write(b"substituted")

    with pytest.raises(ReviewError, match="PDF_SHA256_MISMATCH"):
        run_review_batch(
            packet, objects, tmp_path / "pack", artifact_sha256=sha,
            model_id="qwen3-vl:2b", model_version="sha256:test-model",
            parameters={"temperature": 0, "seed": 17}, transport=FakeModel(),
        )


def test_candidate_requires_two_effective_independent_classifications(
    tmp_path: Path,
) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    pdf = objects / "artifact.pdf"
    sha = _pdf(pdf, pages=1)
    pdf.rename(objects / sha)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [{"content_sha256": value, "page_count": 1,
                       "source_path": value} for value in shas]
    }))
    model = FakeModel()

    run_review_batch(
        packet, objects, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=model,
        rights_evidence_by_sha={sha: True},
    )

    assert len(model.calls) == 4
    summary = json.loads((tmp_path / "pack" / "reviews" / f"{sha}.json").read_bytes())
    replays = summary["candidate_replays"]
    assert [run["run_index"] for run in replays] == [1, 2]
    assert [run["run_nonce"] for run in replays] == [0, 1]
    assert replays[0]["reviewer_a_observation_sha256"] == replays[1][
        "reviewer_a_observation_sha256"
    ]
    assert replays[0]["reviewer_b_observation_sha256"] == replays[1][
        "reviewer_b_observation_sha256"
    ]
    for domain in ("reviewer_a", "reviewer_b"):
        first = replays[0][f"{domain}_evidence_refs"]
        second = replays[1][f"{domain}_evidence_refs"]
        assert len(first) == len(second) == 1
        assert first != second
        first_sha = first[0].split(":", 1)[1]
        second_sha = second[0].split(":", 1)[1]
        first_receipt = json.loads((tmp_path / "pack" / "receipts" /
                                    first_sha[:2] / f"{first_sha}.json").read_bytes())
        second_receipt = json.loads((tmp_path / "pack" / "receipts" /
                                     second_sha[:2] / f"{second_sha}.json").read_bytes())
        assert first_receipt["run_nonce"] == 0
        assert second_receipt["run_nonce"] == 1
        assert first_receipt["request_sha256"] != second_receipt["request_sha256"]


def test_candidate_second_run_observation_divergence_is_fail_closed(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    pdf = objects / "artifact.pdf"
    sha = _pdf(pdf, pages=1)
    pdf.rename(objects / sha)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [{"content_sha256": value, "page_count": 1,
                       "source_path": value} for value in shas]
    }))
    model = FakeModel()

    def divergent(model_id, system_prompt, user_payload, parameters, image_png):
        observation = model(model_id, system_prompt, user_payload, parameters, image_png)
        if len(model.calls) == 4:
            observation["visual_examined"] = True
        return observation

    divergent.supports_vision = True
    run_review_batch(
        packet, objects, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=divergent,
        rights_evidence_by_sha={sha: True},
    )

    summary = json.loads((tmp_path / "pack" / "reviews" / f"{sha}.json").read_bytes())
    assert summary["candidate_replays"][0]["candidate_verdict"] == "PASS"
    assert summary["candidate_replays"][1]["candidate_verdict"] == "FAIL"
    assert summary["candidate_replays"][0]["reviewer_b_observation_sha256"] != (
        summary["candidate_replays"][1]["reviewer_b_observation_sha256"]
    )


def test_candidate_cache_rejects_duplicated_replay_receipts(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    pdf = objects / "artifact.pdf"
    sha = _pdf(pdf, pages=1)
    pdf.rename(objects / sha)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [{"content_sha256": value, "page_count": 1,
                       "source_path": value} for value in shas]
    }))
    options = {
        "artifact_sha256": sha,
        "model_id": "qwen3-vl:2b",
        "model_version": "sha256:test-model",
        "parameters": {"temperature": 0, "seed": 17},
        "rights_evidence_by_sha": {sha: True},
    }
    run_review_batch(packet, objects, tmp_path / "pack", transport=FakeModel(), **options)
    summary_path = tmp_path / "pack" / "reviews" / f"{sha}.json"
    summary = json.loads(summary_path.read_bytes())
    summary["candidate_replays"][1]["reviewer_a_evidence_refs"] = summary[
        "candidate_replays"
    ][0]["reviewer_a_evidence_refs"]
    summary["summary_sha256"] = hashlib.sha256(json.dumps(
        {key: value for key, value in summary.items() if key != "summary_sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    summary_path.write_text(json.dumps(summary))
    model = FakeModel()

    outcome = run_review_batch(packet, objects, tmp_path / "pack", transport=model, **options)

    assert outcome["reviewed"] == [sha]
    assert outcome["reused"] == []


def test_cli_refuses_unpinned_model_version(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", [
        "student_rights_reviewers.py", "--packet", str(tmp_path / "missing.json"),
        "--objects", str(tmp_path), "--pack", str(tmp_path / "pack"),
        "--artifact-sha256", "a" * 64, "--model-id", "qwen3-vl:2b",
        "--model-version", "mutable-tag",
        "--source-checkpoints-dir", str(tmp_path / "source_checkpoints"),
    ])

    assert main() == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "REVIEW_MODEL_PIN_INVALID"


def test_cli_exits_red_when_a_review_is_incomplete(monkeypatch, capsys, tmp_path: Path) -> None:
    import student_rights_reviewers as reviewers

    monkeypatch.setattr(sys, "argv", [
        "student_rights_reviewers.py", "--packet", str(tmp_path / "packet.json"),
        "--source-mirror-root", str(tmp_path), "--pack-dir", str(tmp_path / "pack"),
        "--artifact-sha256", "a" * 64, "--model-id", "granite3.2-vision:2b",
        "--model-version", "sha256:" + "b" * 64,
        "--source-checkpoints-dir", str(tmp_path / "source"),
    ])
    monkeypatch.setattr(reviewers, "run_review_batch", lambda *args, **kwargs: {
        "reviewed": ["a" * 64], "reused": [], "incomplete": ["a" * 64],
        "inventory_count": 315,
    })

    assert main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_batch_resolves_nested_packet_source_path_without_copies(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    nested = mirror / "nested"
    nested.mkdir(parents=True)
    pdf = nested / "source.pdf"
    sha = _pdf(pdf, pages=1)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [
            {"content_sha256": value, "page_count": 1,
             "source_path": "nested/source.pdf" if value == sha else value}
            for value in shas
        ]
    }))

    result = run_review_batch(
        packet, mirror, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=FakeModel(),
    )

    assert result["reviewed"] == [sha]
    assert not (mirror / sha).exists()


def test_batch_rejects_source_path_traversal(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    outside = tmp_path / "outside.pdf"
    sha = _pdf(outside, pages=1)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [
            {"content_sha256": value, "page_count": 1,
             "source_path": "../outside.pdf" if value == sha else value}
            for value in shas
        ]
    }))

    with pytest.raises(ReviewError, match="REVIEW_SOURCE_PATH_INVALID"):
        run_review_batch(
            packet, mirror, tmp_path / "pack", artifact_sha256=sha,
            model_id="qwen3-vl:2b", model_version="sha256:test-model",
            parameters={"temperature": 0, "seed": 17}, transport=FakeModel(),
        )


def test_rights_signal_needs_positive_source_checkpoint_and_intact_receipt(
    tmp_path: Path,
) -> None:
    sha = "a" * 64
    receipt = {
        "kind": "NEXUS-STUDENT-SOURCE-RIGHTS-RECEIPT-V1",
        "artifact_content_sha256": sha,
        "listing_uri": "https://eduscol.education.gouv.fr/listing",
        "pdf": {"content_sha256": sha,
                "final_uri": "https://eduscol.education.gouv.fr/exact.pdf"},
        "legal_terms": {"body_sha256": "b" * 64},
        "license": {"body_sha256": "c" * 64},
        "source_checker_code_sha256": hashlib.sha256(
            (Path(__file__).resolve().parents[1] /
             "go_live/student_rights_source_check.py").read_bytes()
        ).hexdigest(),
        "transport_kind": "URLLIB_HTTPS_GET_NO_REDIRECT_V1",
    }
    raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) + "\n").encode()
    receipt_sha = hashlib.sha256(raw).hexdigest()
    receipt_dir = tmp_path / "source_receipts" / receipt_sha[:2]
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{receipt_sha}.json").write_bytes(raw)
    checkpoint = {
        "source_identity": {
            "status": "VERIFIED", "source_identity_verified": True,
            "exact_bytes_match": True,
            "source_uri": "https://eduscol.education.gouv.fr/listing",
            "exact_pdf_uri": "https://eduscol.education.gouv.fr/exact.pdf",
            "remote_pdf_sha256": sha, "downloaded_sha256": sha,
        },
        "rights_check": {
            "rights_basis": "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE",
            "rights_evidence_uri": "https://eduscol.education.gouv.fr/terms",
            "license_or_terms_excerpt_hash": "b" * 64,
            "license_snapshot_sha256": "c" * 64,
            "source_receipt_sha256": receipt_sha,
            "currentness_status": "PASS", "revocation_status": "PASS",
            "source_verification": {
                "status": "VERIFIED", "remote_pdf_sha256": sha,
                "exact_pdf_uri": "https://eduscol.education.gouv.fr/exact.pdf",
                "terms_sha256": "b" * 64,
            },
        },
    }
    checkpoint_dir = tmp_path / "source_checkpoints"
    checkpoint_dir.mkdir()
    checkpoint_path = checkpoint_dir / f"{sha}.json"
    checkpoint_path.write_text(json.dumps(checkpoint))
    artifact = {"content_sha256": sha,
                "source_listing_url": "https://eduscol.education.gouv.fr/listing"}

    assert _rights_signal_from_source(
        artifact, checkpoint_dir, tmp_path / "source_receipts"
    ) is True
    checkpoint["rights_check"]["revocation_status"] = "UNVERIFIABLE"
    checkpoint_path.write_text(json.dumps(checkpoint))
    assert _rights_signal_from_source(
        artifact, checkpoint_dir, tmp_path / "source_receipts"
    ) is False
    checkpoint["rights_check"]["revocation_status"] = "PASS"
    checkpoint_path.write_text(json.dumps(checkpoint))
    (receipt_dir / f"{receipt_sha}.json").write_bytes(b"tampered")
    assert _rights_signal_from_source(
        artifact, checkpoint_dir, tmp_path / "source_receipts"
    ) is False


def test_batch_source_checkpoints_override_unproven_manual_signal(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    pdf = mirror / "artifact.pdf"
    sha = _pdf(pdf, pages=1)
    packet = tmp_path / "inventory.json"
    shas = [sha] + [f"{number:064x}" for number in range(1, 315)]
    packet.write_text(json.dumps({
        "artifacts": [
            {"content_sha256": value, "page_count": 1,
             "source_path": "artifact.pdf" if value == sha else value,
             "source_listing_url": "https://eduscol.education.gouv.fr/listing"}
            for value in shas
        ]
    }))
    source_checkpoints = tmp_path / "source_checkpoints"
    source_checkpoints.mkdir()
    (source_checkpoints / f"{sha}.json").write_text(json.dumps({
        "source_identity": {"status": "UNVERIFIABLE"},
        "rights_check": {"rights_basis": "NONE"},
    }))
    model = FakeModel()

    run_review_batch(
        packet, mirror, tmp_path / "pack", artifact_sha256=sha,
        model_id="qwen3-vl:2b", model_version="sha256:test-model",
        parameters={"temperature": 0, "seed": 17}, transport=model,
        rights_evidence_by_sha={sha: True},
        source_checkpoint_dir=source_checkpoints,
        source_receipt_dir=tmp_path / "source_receipts",
    )

    summary = json.loads((tmp_path / "pack" / "reviews" / f"{sha}.json").read_bytes())
    assert len(model.calls) == 2
    assert summary["candidate_replays"] == []
    assert summary["reviewer_a"]["verdict"] == "FAIL"


def test_granite_transport_uses_bounded_generate_with_strict_json_schema(
    monkeypatch,
) -> None:
    requests = []
    observation = {
        "page_number": 1, "segment_index": 1, "segment_count": 1,
        "verdict": "FAIL", "confidence": "HIGH", "reason_codes": ["TEACHER_ONLY"],
        "evidence_pages": [1], "visual_examined": True,
    }

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(json.dumps({"response": json.dumps(observation)}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    transport = OllamaTransport()
    payload = {
        "page_number": 1, "segment_index": 1, "segment_count": 1,
        "page_text_segment": "PRIVATE_CANARY", "page_has_graphics": True,
        "review_domain": "reviewer_b",
    }

    actual = transport(
        "granite3.2-vision:2b", "REVUE_B", payload,
        {"temperature": 0, "seed": 17, "num_ctx": 4096, "num_predict": 320},
        b"synthetic-png",
    )

    assert actual == observation
    request, timeout = requests[0]
    body = json.loads(request.data)
    assert request.full_url.endswith("/api/generate")
    assert timeout == 120
    assert body["format"]["additionalProperties"] is False
    assert set(body["format"]["required"]) == set(observation)
    assert body["images"]
    assert body["options"]["num_predict"] == 320
    assert "PRIVATE_CANARY" in body["prompt"]


def test_ocr_dedup_removes_only_exact_normalized_extracted_lines() -> None:
    extracted = "Unique teacher notice\nOrdinary text\n"
    ocr = "  unique   TEACHER notice \nA distinct restriction!\nOrdinary text variation\n"

    residual, dropped = _residual_ocr(extracted, ocr)

    assert dropped == 1
    assert "A distinct restriction!" in residual
    assert "Ordinary text variation" in residual
    assert "unique   TEACHER notice" not in residual


def test_xmp_projection_dedups_exact_values_and_reviews_embedded_image(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "xmp.pdf"
    _pdf(path, pages=1)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 16, 12), 0)
    for y in range(12):
        for x in range(16):
            pixmap.set_pixel(x, y, ((x * 37 + y * 17) % 256,
                                    (x * 13 + y * 29) % 256,
                                    (x * 73 + y * 3) % 256))
    xmp_image = pixmap.tobytes("png")
    encoded = base64.b64encode(xmp_image).decode()
    doc = fitz.open(path)
    doc.set_xml_metadata(
        '<root><rights>PRIVATE_CANARY_NOTICE</rights>'
        '<rights>PRIVATE_CANARY_NOTICE</rights>'
        f'<image>{encoded}</image></root>'
    )
    doc.saveIncr()
    doc.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    import student_rights_reviewers as reviewers

    monkeypatch.setattr(reviewers, "_ocr_text", lambda _png: "")
    with fitz.open(path) as source:
        projected, images, facts = _project_metadata(source)
    assert projected.count("PRIVATE_CANARY_NOTICE") == 1
    assert len(images) == 1
    assert images[0] == xmp_image
    assert facts["xmp_duplicate_value_count"] >= 1
    model = FakeModel()

    result = _run(path, sha, model, vision_enabled=True, receipt_dir=tmp_path / "receipts")

    assert len(model.calls) == 4  # text segment + separate XMP image, A and B
    assert sum(call["image_seen"] for call in model.calls) == 2
    assert result["reviewer_a"]["complete"] is True
    assert result["reviewer_b"]["complete"] is True
    assert result["text_assembly"][0]["xmp_embedded_image_count"] == 1
    assert "PRIVATE_CANARY_NOTICE" not in json.dumps(result)


def test_xmp_projection_keeps_unique_values_without_repeating_namespace_uri(
    tmp_path: Path,
) -> None:
    path = tmp_path / "namespaces.pdf"
    _pdf(path, pages=1)
    namespace = "https://example.test/long/repeated/namespace/for/document/metadata/v1"
    xml = f'<root xmlns:x="{namespace}">' + "".join(
        f"<x:item>UNIQUE_VALUE_{number}</x:item>" for number in range(100)
    ) + "</root>"
    doc = fitz.open(path)
    doc.set_xml_metadata(xml)
    doc.saveIncr()
    doc.close()

    with fitz.open(path) as source:
        projected, images, facts = _project_metadata(source)

    assert len(images) == 0
    assert facts["xmp_unique_value_count"] == 100
    assert all(f"UNIQUE_VALUE_{number}" in projected for number in range(100))
    assert len(projected) < len(xml) * 2


def test_short_base64_xmp_image_is_still_reviewed_visually(tmp_path: Path) -> None:
    path = tmp_path / "tiny_image.pdf"
    _pdf(path, pages=1)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1, 1), 0)
    pixmap.set_pixel(0, 0, (255, 0, 0))
    image = pixmap.tobytes("png")
    encoded = base64.b64encode(image).decode()
    assert len(encoded) < 400
    doc = fitz.open(path)
    doc.set_xml_metadata(f"<root><image>{encoded}</image></root>")
    doc.saveIncr()
    doc.close()

    with fitz.open(path) as source:
        _, images, facts = _project_metadata(source)

    assert images == [image]
    assert facts["xmp_embedded_image_count"] == 1
