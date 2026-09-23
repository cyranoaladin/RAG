"""Le diff machine entre deux releases profile-gate dit ce qui a changé, et seulement cela."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "go_live" / "diff_profile_gate_releases.py"


def _load():
    spec = importlib.util.spec_from_file_location("diff_profile_gate_releases", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


A, B, C = ("a" * 64, "b" * 64, "c" * 64)


def _artifact(sha: str, chunks: str = "x") -> dict:
    return {
        "artifact_id": sha, "content_sha256": sha, "chunk_id_set_digest": chunks * 64,
        "chunk_sha256_set_digest": chunks * 64, "chunks": [{"chunk_id": sha[:8] + chunks}],
        "page_count": 3, "source_path": f"{sha[:4]}.pdf", "title": "t",
    }


def _placement(sha: str, collection: str = "rag_x") -> dict:
    return {"artifact_id": sha, "collection": collection, "placement_id": f"p-{sha[:6]}-{collection}",
            "currentness": "current", "review_status": "reviewed"}


def _base() -> dict:
    return {
        "manifest": {
            "release_id": "r-v2", "release_mode": "rehearsal", "review_status": "PRE_REVIEW",
            "authorities": {"pii_evidence_sha256": "1" * 64, "rights_registry_sha256": "2" * 64},
        },
        "artifacts": [_artifact(A), _artifact(B)],
        "placements": [_placement(A), _placement(B), _placement(B, "rag_y")],
        "pii": [{"content_sha256": A, "status": "CLEARED"}, {"content_sha256": B, "status": "CLEARED"}],
        "currentness": [{"content_sha256": A, "decision": "CURRENT"}, {"content_sha256": B, "decision": "CURRENT"}],
    }


def _write(root: Path, spec: dict) -> Path:
    gate = root / "profile_gate"
    (gate / "subjects").mkdir(parents=True)
    (gate / "artifacts.release.json").write_text(json.dumps({"artifacts": spec["artifacts"]}))
    by_collection: dict[str, list] = {}
    for placement in spec["placements"]:
        by_collection.setdefault(placement["collection"], []).append(placement)
    for collection, placements in by_collection.items():
        (gate / "subjects" / f"{collection}.release.json").write_text(
            json.dumps({"collection": collection, "placements": placements})
        )
    (gate / "pii_evidence.json").write_text(json.dumps({"results": spec["pii"]}))
    (gate / "currentness_evidence.json").write_text(json.dumps({"artifacts": spec["currentness"]}))
    (gate / "production-profile-gate.release.json").write_text(json.dumps(spec["manifest"]))
    return gate


def test_identical_releases_differ_in_nothing(tmp_path: Path) -> None:
    diff = _load().diff_releases(_write(tmp_path / "v2", _base()), _write(tmp_path / "v3", _base()))
    assert diff["files"]["changed"] == [] and diff["files"]["added"] == [] and diff["files"]["removed"] == []
    assert diff["authorities"] == {"added": {}, "removed": {}, "changed": {}}
    assert diff["artifacts"]["added"] == [] and diff["artifacts"]["removed"] == []
    assert diff["artifacts"]["chunk_identity_changed"] == []
    assert diff["placements"]["added"] == [] and diff["placements"]["removed"] == []
    assert diff["pii"]["transitions"] == {"CLEARED->CLEARED": 2}


def test_every_kind_of_change_is_reported(tmp_path: Path) -> None:
    head = copy.deepcopy(_base())
    head["manifest"]["release_id"] = "r-v3"
    head["manifest"]["authorities"]["pii_evidence_sha256"] = "9" * 64
    head["manifest"]["authorities"]["pii_decision_set_sha256"] = "8" * 64
    head["artifacts"] = [_artifact(A), _artifact(C)]  # B retiré, C ajouté
    head["placements"] = [_placement(A), _placement(C)]
    head["pii"] = [{"content_sha256": A, "status": "DETECTED_REVIEWED_ACCEPTED"},
                   {"content_sha256": C, "status": "CLEARED"}]
    head["currentness"] = [{"content_sha256": A, "decision": "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"},
                           {"content_sha256": C, "decision": "CURRENT"}]

    diff = _load().diff_releases(_write(tmp_path / "v2", _base()), _write(tmp_path / "v3", head))

    assert diff["manifest_fields"]["release_id"] == {"base": "r-v2", "head": "r-v3"}
    assert diff["authorities"]["changed"] == {"pii_evidence_sha256": {"base": "1" * 64, "head": "9" * 64}}
    assert diff["authorities"]["added"] == {"pii_decision_set_sha256": "8" * 64}
    assert diff["artifacts"]["added"] == [C] and diff["artifacts"]["removed"] == [B]
    assert diff["placements"]["removed"] == [["rag_x", B], ["rag_y", B]]
    assert diff["placements"]["added"] == [["rag_x", C]]
    assert diff["pii"]["transitions"] == {"CLEARED->DETECTED_REVIEWED_ACCEPTED": 1}
    assert diff["pii"]["added"] == {C: "CLEARED"} and diff["pii"]["removed"] == {B: "CLEARED"}
    assert diff["currentness"]["transitions"] == {"CURRENT->OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": 1}
    assert "production-profile-gate.release.json" in diff["files"]["changed"]


def test_a_changed_chunk_identity_is_named(tmp_path: Path) -> None:
    """L'adoption (ADR-0059 § 5) exige l'égalité exacte : un écart doit être nommé."""
    head = copy.deepcopy(_base())
    head["artifacts"] = [_artifact(A, chunks="y"), _artifact(B)]
    diff = _load().diff_releases(_write(tmp_path / "v2", _base()), _write(tmp_path / "v3", head))
    assert diff["artifacts"]["chunk_identity_changed"] == [A]
    assert diff["artifacts"]["changed_fields"] == {A: ["chunk_id_set_digest", "chunk_sha256_set_digest", "chunks"]}


def test_the_cli_writes_canonical_json_and_refuses_a_non_release(tmp_path: Path) -> None:
    module = _load()
    base, head = _write(tmp_path / "v2", _base()), _write(tmp_path / "v3", _base())
    out = tmp_path / "diff.json"
    assert module.main(["--base", str(base), "--head", str(head), "--output", str(out)]) == 0
    raw = out.read_bytes()
    assert raw == (json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    assert json.loads(raw)["base"]["manifest_sha256"] == hashlib.sha256(
        (base / "production-profile-gate.release.json").read_bytes()
    ).hexdigest()
    with pytest.raises(SystemExit):
        module.main(["--base", str(tmp_path), "--head", str(head), "--output", str(out)])


def test_the_v3_currentness_disposition_is_read_where_v2_had_a_decision(tmp_path: Path) -> None:
    """La preuve d'actualité V3 (ADR-0059) nomme la disposition, pas une décision."""
    head = copy.deepcopy(_base())
    head["currentness"] = [
        {"content_sha256": A, "currentness_disposition": "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"},
        {"content_sha256": B, "currentness_disposition": "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"},
    ]
    diff = _load().diff_releases(_write(tmp_path / "v2", _base()), _write(tmp_path / "v3", head))
    assert diff["currentness"]["transitions"] == {"CURRENT->OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": 2}
