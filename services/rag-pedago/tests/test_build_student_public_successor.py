"""La release successeur ne contient que des dérivés natifs vérifiés."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/rag-pedago/scripts"))
sys.path.insert(0, str(ROOT / "packages/release-chain/tests"))

from build_student_public_successor import (  # noqa: E402
    PinnedE5TokenCounter,
    _bound_source_audiences,
    _set_digest,
    _source_placements,
    build_successor_documents,
    current_checkout_sha,
    project_derivative_artifact,
    run_approved_source_gate,
    verify_successor_metadata,
    write_successor_documents,
)
from nexus_contracts.ingestion import ResourceScope  # noqa: E402
from nexus_release_chain.release_readiness import _compact_set_digest  # noqa: E402
from test_text_derivative_chunking import _candidate as native_text_fixture  # noqa: E402

PRIVATE_CANDIDATE_ROOT = Path(os.environ.get(
    "NEXUS_PRIVATE_CANDIDATE_ROOT", Path.home() / "nexus-student-text-derivatives-20261010",
))
PUBLIC_SUCCESSOR_ROOT = (ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
                         / "profile_gate_student_public_v1/release-eb39f6cd0423e184/profile_gate")


class WordCounter:
    model_id = "intfloat/multilingual-e5-large"
    model_revision = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
    max_sequence_length = 512

    def passage_token_count(self, text: str) -> int:
        return len(text.split()) + 2


def _candidate() -> tuple[dict, dict, bytes]:
    content, receipt = native_text_fixture()
    digest = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    entry = {
        "source_content_sha256": receipt["source_content_sha256"],
        "derivative_content_sha256": receipt["derivative_content_sha256"],
        "derivative_receipt_sha256": digest,
        "media_type": "text/plain; charset=utf-8",
        "citation": receipt["source_attribution"],
    }
    return entry, receipt, content


def test_project_derivative_uses_new_identity_native_pages_and_complete_citation() -> None:
    entry, receipt, content = _candidate()
    artifact, lineage = project_derivative_artifact(
        entry, receipt, content, token_counter=WordCounter(), target_tokens=384,
    )
    assert artifact["content_sha256"] == entry["derivative_content_sha256"]
    assert artifact["content_sha256"] != artifact["source_pdf_sha256"]
    assert artifact["media_type"] == "text/plain; charset=utf-8"
    assert artifact["citation"] == {
        **receipt["source_attribution"],
        "source_pdf_sha256": entry["source_content_sha256"],
    }
    assert artifact["chunks"]
    assert all(row["page_start"] == row["page_end"] for row in artifact["chunks"])
    assert all("text" not in row for row in artifact["chunks"])
    assert artifact["excluded_source_pages"] == [3]
    assert artifact["chunk_id_set_digest"]
    assert artifact["chunk_sha256_set_digest"]
    assert artifact["page_coverage_digest"]
    assert artifact["chunk_lineage"]["sha256"] == hashlib.sha256(lineage).hexdigest()
    assert b"Une" in lineage or b"enseignement" in lineage


def test_project_derivative_rejects_cas_substitution() -> None:
    entry, receipt, content = _candidate()
    with pytest.raises(ValueError, match="CAS|SHA|sha"):
        project_derivative_artifact(
            entry, receipt, content + b"substitution", token_counter=WordCounter(),
            target_tokens=384,
        )


def _proofs() -> tuple[dict, dict]:
    evidence = ROOT / "docs/reports/go_live/student_rights_evidence"
    manifest_raw = (evidence / "public_derivative_candidate_manifest_20261010.json").read_bytes()
    manifest = json.loads(manifest_raw)
    index_raw = (evidence / "index.json").read_bytes()
    from collections import Counter

    placement_count = Counter(
        (entry["derivative_content_sha256"], collection)
        for entry in manifest["entries"] for collection in entry["collections"]
    )
    topology: dict[str, dict[str, int]] = {}
    for (sha, collection), count in placement_count.items():
        topology.setdefault(sha, {})[collection] = count
    authority = {
        "PR300_AUTHORITY_APPROVAL_PASS": True,
        "CANDIDATE_MANIFEST_SHA256": hashlib.sha256(manifest_raw).hexdigest(),
        "EVIDENCE_PACK_SHA256": hashlib.sha256(index_raw).hexdigest(),
    }
    gate = {
        "DELEGATED_RIGHTS_ADJUDICATION_PASS": True,
        "EVIDENCE_PACK_SHA256": authority["EVIDENCE_PACK_SHA256"],
        "FINAL_DECISIONS_COUNT": 315,
        "INVENTORY_COUNT": 315,
        "FULL_DOCUMENT_SCAN_COUNT": 315,
        "DUAL_REVIEW_COUNT": 315,
        "CFTR_DISPOSITION": "EXCLUDE",
        "POLICY_FAIL_CLOSED": True,
        "MANUAL_PER_FILE_REVIEW_REQUIRED": False,
        "PENDING_COUNT": 0,
        "errors": [],
        "APPROVED_DERIVATIVE_CONTENT_SHA256": sorted(topology),
        "APPROVED_DERIVATIVE_PLACEMENTS": topology,
        "APPROVED_DERIVATIVE_RECEIPT_SHA256": {
            entry["derivative_content_sha256"]: entry["derivative_receipt_sha256"]
            for entry in manifest["entries"]
        },
        "FINAL_POPULATION": {
            "artifacts": 253, "placements": 377, "collections": 11,
            "source_pdfs": 315, "original_pdf_public_count": 0,
            "derivative_segments": 2504,
        },
    }
    return authority, gate


@pytest.mark.skipif(not PRIVATE_CANDIDATE_ROOT.is_dir(), reason="private #300 CAS absent")
def test_build_successor_projects_all_approved_derivatives_without_a_pdf(tmp_path: Path) -> None:
    authority, gate = _proofs()
    release_root = tmp_path / "student-public-v1"
    private_root = tmp_path / "store"
    documents, private_documents = build_successor_documents(
        repository_root=ROOT,
        private_candidate_root=PRIVATE_CANDIDATE_ROOT,
        release_root=release_root,
        private_root=private_root,
        release_id="student-public-20261010-v1-test",
        token_counter=WordCounter(),
        authority_approval=authority,
        rights_gate=gate,
    )
    aggregate = json.loads(documents[release_root / "production-profile-gate.release.json"])
    registry = json.loads(documents[release_root / "artifacts.release.json"])
    assert aggregate["expected_counts"]["subjects"] == 11
    assert aggregate["expected_counts"]["unique_artifacts"] == 253
    assert aggregate["expected_counts"]["placements"] == 377
    assert aggregate["expected_counts"]["unique_chunks"] > 2504
    assert len(registry["artifacts"]) == 253
    assert all(a["media_type"] == "text/plain; charset=utf-8" for a in registry["artifacts"])
    assert all(a["type_doc"] for a in registry["artifacts"])
    assert all(not str(path).endswith(".pdf") for path in private_documents)
    assert len([p for p in private_documents if p.suffix == ".txt"]) == 253
    assert len([p for p in private_documents if "derivative_receipts" in p.parts]) == 253
    profile_registry = json.loads(documents[release_root / "public_profiles.json"])
    assert len(profile_registry["entries"]) == 11
    assert all(row["scope"]["audience"] == ["libre", "aefe"]
               for row in profile_registry["entries"])
    for row in profile_registry["entries"]:
        operational_scope = {key: value for key, value in row["scope"].items()
                             if key != "statut_enseignement"}
        assert ResourceScope.model_validate(operational_scope).visibility == "public"
    verdict = verify_successor_metadata(documents, release_root)
    assert verdict == {
        "collections": 11, "artifacts": 253, "placements": 377,
        "chunks": aggregate["expected_counts"]["unique_chunks"],
        "public_pdf_count": 0,
    }
    for name, authority_key, population in (
        ("public_profiles.json", "public_profile_registry_sha256", 11),
        ("public_rights_registry.json", "public_rights_registry_sha256", 253),
        ("public_pii_registry.json", "public_pii_registry_sha256", 253),
    ):
        raw = documents[release_root / name]
        descriptor = json.loads(raw)
        assert descriptor["status"] == "CANDIDATE_NOT_AUTHORIZED"
        assert len(descriptor["entries"]) == population
        assert aggregate["authorities"][authority_key] == hashlib.sha256(raw).hexdigest()


def test_bound_source_audience_refuses_a_valid_but_unapproved_profile_change(
    tmp_path: Path,
) -> None:
    index = json.loads((ROOT / "docs/reports/go_live/student_rights_evidence/index.json").read_bytes())
    subjects, _, _, _ = _source_placements(ROOT, index)
    relative = Path("services/rag-engine/configs/ingestion_profiles")
    source = ROOT / relative
    target = tmp_path / relative
    target.mkdir(parents=True)
    (target / "ingestion_manifest_v3_livraison_315.yml").write_bytes(
        (source / "ingestion_manifest_v3_livraison_315.yml").read_bytes()
    )
    profiles = target / "v3_livraison_315"
    profiles.mkdir()
    for path in (source / "v3_livraison_315").glob("*.yml"):
        (profiles / path.name).write_bytes(path.read_bytes())
    assert len(_bound_source_audiences(tmp_path, subjects)) == 11
    changed = profiles / "rag_nexus_svt_premiere_specialite.yml"
    changed.write_text(changed.read_text().replace("  - libre\n  - aefe", "  - aefe\n  - libre"))
    with pytest.raises(ValueError, match="source profile authority"):
        _bound_source_audiences(tmp_path, subjects)


def test_build_successor_fails_closed_without_exact_authority(tmp_path: Path) -> None:
    authority, gate = _proofs()
    authority["PR300_AUTHORITY_APPROVAL_PASS"] = False
    with pytest.raises(ValueError, match="authority"):
        build_successor_documents(
            repository_root=ROOT,
            private_candidate_root=PRIVATE_CANDIDATE_ROOT,
            release_root=tmp_path / "release", private_root=tmp_path / "store",
            release_id="student-public-20261010-v1-test", token_counter=WordCounter(),
            authority_approval=authority, rights_gate=gate,
        )


@pytest.mark.parametrize("sabotage", ["manifest_digest", "topology", "receipt"])
def test_build_successor_refuses_a_pack_or_topology_mismatch(
    tmp_path: Path, sabotage: str,
) -> None:
    authority, gate = _proofs()
    if sabotage == "manifest_digest":
        authority["CANDIDATE_MANIFEST_SHA256"] = "0" * 64
    elif sabotage == "topology":
        first = next(iter(gate["APPROVED_DERIVATIVE_PLACEMENTS"]))
        gate["APPROVED_DERIVATIVE_PLACEMENTS"][first] = {"forged_collection": 1}
    else:
        first = next(iter(gate["APPROVED_DERIVATIVE_RECEIPT_SHA256"]))
        gate["APPROVED_DERIVATIVE_RECEIPT_SHA256"][first] = "0" * 64
    with pytest.raises(ValueError, match="digest|topology|receipt"):
        build_successor_documents(
            repository_root=ROOT,
            private_candidate_root=PRIVATE_CANDIDATE_ROOT,
            release_root=tmp_path / "release", private_root=tmp_path / "store",
            release_id="student-public-20261010-v1-test", token_counter=WordCounter(),
            authority_approval=authority, rights_gate=gate,
        )


def test_build_successor_refuses_an_existing_release_identity(tmp_path: Path) -> None:
    authority, gate = _proofs()
    with pytest.raises(ValueError, match="already exists"):
        build_successor_documents(
            repository_root=ROOT,
            private_candidate_root=PRIVATE_CANDIDATE_ROOT,
            release_root=tmp_path / "release", private_root=tmp_path / "store",
            release_id="production-profile-gate-2026-2027-v4", token_counter=WordCounter(),
            authority_approval=authority, rights_gate=gate,
        )


@pytest.mark.skipif(not PRIVATE_CANDIDATE_ROOT.is_dir(), reason="private #300 CAS absent")
def test_clean_approved_gate_can_bind_a_pinned_manifest_without_new_topology_fields(
    tmp_path: Path,
) -> None:
    authority, gate = _proofs()
    gate["EVIDENCE_PACK_SHA256"] = authority["EVIDENCE_PACK_SHA256"]
    gate["FINAL_DECISIONS_COUNT"] = 315
    gate["PENDING_COUNT"] = 0
    gate["errors"] = []
    del gate["APPROVED_DERIVATIVE_PLACEMENTS"]
    del gate["APPROVED_DERIVATIVE_RECEIPT_SHA256"]
    documents, _ = build_successor_documents(
        repository_root=ROOT, private_candidate_root=PRIVATE_CANDIDATE_ROOT,
        release_root=tmp_path / "release", private_root=tmp_path / "store",
        release_id="student-public-20261010-v1-test", token_counter=WordCounter(),
        authority_approval=authority, rights_gate=gate,
    )
    assert len(json.loads(documents[tmp_path / "release/artifacts.release.json"])["artifacts"]) == 253
    gate["EVIDENCE_PACK_SHA256"] = "0" * 64
    with pytest.raises(ValueError, match="evidence"):
        build_successor_documents(
            repository_root=ROOT, private_candidate_root=PRIVATE_CANDIDATE_ROOT,
            release_root=tmp_path / "other", private_root=tmp_path / "other-store",
            release_id="student-public-20261010-v1-test", token_counter=WordCounter(),
            authority_approval=authority, rights_gate=gate,
        )


def test_write_successor_documents_refuses_any_existing_output(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    private_root = tmp_path / "store"
    documents = {
        release_root / "manifest.json": b"new\n",
        release_root.parent / "release-registry.json": b"registry\n",
    }
    private = {private_root / "a.txt": b"native text\n"}
    write_successor_documents(documents, private, release_root, private_root)
    assert (release_root / "manifest.json").read_bytes() == b"new\n"
    assert (private_root / "a.txt").read_bytes() == b"native text\n"
    assert release_root.stat().st_mode & 0o777 == 0o755
    assert (release_root / "manifest.json").stat().st_mode & 0o777 == 0o644
    assert private_root.stat().st_mode & 0o777 == 0o700
    assert (private_root / "a.txt").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_successor_documents(documents, private, release_root, private_root)
    assert (release_root / "manifest.json").read_bytes() == b"new\n"


def test_writer_removes_only_its_partial_registry_after_fsync_failure(tmp_path: Path, monkeypatch) -> None:
    release_root = tmp_path / "release"
    private_root = tmp_path / "store"
    registry_path = release_root.parent / "release-registry.json"
    documents = {release_root / "manifest.json": b"new\n", registry_path: b"registry\n"}
    private = {private_root / "a.txt": b"native text\n"}

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr("build_student_public_successor.os.fsync", fail_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        write_successor_documents(documents, private, release_root, private_root)
    assert not release_root.exists()
    assert not private_root.exists()
    assert not registry_path.exists()


@pytest.mark.parametrize("target", ["release", "private"])
def test_writer_rejects_path_traversal(tmp_path: Path, target: str) -> None:
    release_root = tmp_path / "release"
    private_root = tmp_path / "store"
    registry_path = release_root.parent / "release-registry.json"
    documents = {release_root / "manifest.json": b"new\n", registry_path: b"registry\n"}
    private = {private_root / "a.txt": b"native text\n"}
    if target == "release":
        documents[release_root / ".." / "escaped.json"] = b"escaped"
    else:
        private[private_root / ".." / "escaped.txt"] = b"escaped"
    with pytest.raises(ValueError, match="escaped|traversal"):
        write_successor_documents(documents, private, release_root, private_root)
    assert not (tmp_path / "escaped.json").exists()
    assert not (tmp_path / "escaped.txt").exists()
    assert not release_root.exists()
    assert not private_root.exists()


def test_writer_rejects_symlinked_output_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "link"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    release_root = linked_parent / "release"
    private_root = tmp_path / "store"
    documents = {
        release_root / "manifest.json": b"new\n",
        release_root.parent / "release-registry.json": b"registry\n",
    }
    with pytest.raises(ValueError, match="symlink"):
        write_successor_documents(documents, {private_root / "a.txt": b"text"},
                                  release_root, private_root)
    assert not (real_parent / "release").exists()


def test_pinned_e5_counter_refuses_a_noncanonical_snapshot(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="snapshot revision"):
        PinnedE5TokenCounter(tmp_path / "unrelated")


def test_page_coverage_digest_matches_release_parser_for_pages_over_nine() -> None:
    assert _set_digest([1, 2, 10, 11]) == _compact_set_digest([1, 2, 10, 11])


def test_current_checkout_sha_is_the_source_gate_head() -> None:
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert current_checkout_sha(ROOT) == expected


def _clean_authority_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run([
        "git", "-C", str(path), "-c", "user.name=Test",
        "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "source",
    ], check=True)
    return path


def test_source_gate_uses_a_separate_clean_authority_checkout(tmp_path: Path) -> None:
    authority_root = _clean_authority_repo(tmp_path / "authority")
    mirror_root = tmp_path / "mirror"
    candidate_root = tmp_path / "candidate"
    seen: list[dict] = []

    def gate_runner(**kwargs: object) -> dict:
        seen.append(kwargs)
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": True}

    head, verdict = run_approved_source_gate(
        authority_root=authority_root,
        expected_source_head=current_checkout_sha(authority_root),
        source_mirror_root=mirror_root,
        private_candidate_root=candidate_root,
        gate_runner=gate_runner,
    )
    assert verdict["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is True
    assert seen == [{
        "root": authority_root, "expected_head": head,
        "source_mirror_root": mirror_root,
        "private_candidate_root": candidate_root,
    }]


def test_source_gate_refuses_dirty_authority_before_rescan(tmp_path: Path) -> None:
    authority_root = _clean_authority_repo(tmp_path / "authority")
    (authority_root / "untracked.txt").write_text("dirty", encoding="utf-8")

    def should_not_run(**kwargs: object) -> dict:
        raise AssertionError("the expensive PDF rescan must not begin")

    with pytest.raises(ValueError, match="authority checkout is not clean"):
        run_approved_source_gate(
            authority_root=authority_root,
            expected_source_head=current_checkout_sha(authority_root),
            source_mirror_root=tmp_path / "mirror",
            private_candidate_root=tmp_path / "candidate",
            gate_runner=should_not_run,
        )


def test_source_gate_refuses_head_different_from_pr300_merge_receipt(tmp_path: Path) -> None:
    authority_root = _clean_authority_repo(tmp_path / "authority")

    def should_not_run(**kwargs: object) -> dict:
        raise AssertionError("the expensive PDF rescan must not begin")

    with pytest.raises(ValueError, match="authority checkout HEAD differs"):
        run_approved_source_gate(
            authority_root=authority_root,
            expected_source_head="f" * 40,
            source_mirror_root=tmp_path / "mirror",
            private_candidate_root=tmp_path / "candidate",
            gate_runner=should_not_run,
        )


def test_versioned_successor_metadata_can_be_verified_without_private_cas() -> None:
    documents = {path: path.read_bytes() for path in PUBLIC_SUCCESSOR_ROOT.rglob("*")
                 if path.is_file()}
    registry_path = PUBLIC_SUCCESSOR_ROOT.parent / "release-registry.json"
    documents[registry_path] = registry_path.read_bytes()
    assert verify_successor_metadata(documents, PUBLIC_SUCCESSOR_ROOT) == {
        "collections": 11, "artifacts": 253, "placements": 377,
        "chunks": 3975, "public_pdf_count": 0,
    }


@pytest.mark.skipif(not PRIVATE_CANDIDATE_ROOT.is_dir(), reason="private #300 CAS absent")
def test_metadata_verifier_rejects_a_changed_subject_digest(tmp_path: Path) -> None:
    authority, gate = _proofs()
    release_root = tmp_path / "release"
    documents, _ = build_successor_documents(
        repository_root=ROOT, private_candidate_root=PRIVATE_CANDIDATE_ROOT,
        release_root=release_root, private_root=tmp_path / "store",
        release_id="student-public-20261010-v1-test", token_counter=WordCounter(),
        authority_approval=authority, rights_gate=gate,
    )
    subject_path = next(path for path in documents if path.parent == release_root / "subjects")
    documents[subject_path] += b" "
    with pytest.raises(ValueError, match="subject.*digest"):
        verify_successor_metadata(documents, release_root)
