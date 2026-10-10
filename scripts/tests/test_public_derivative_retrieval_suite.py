"""The public acceptance plan cannot pass on an unpromoted candidate."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "go_live"))

from public_derivative_retrieval_suite import (  # noqa: E402
    SuiteFailure,
    check_dense_tie_probe,
    load_draft_suite,
    require_final_binding,
    validate_draft_suite,
)


def test_draft_covers_exact_candidate_and_fixed_cases() -> None:
    suite = load_draft_suite(ROOT)
    assert suite["status"] == "PREPARED_UNBOUND"
    assert len(suite["collections"]) == 11
    assert sum(len(row["positive"]) for row in suite["collections"].values()) == 33
    assert suite["thresholds"]["student_positive_nonempty"] == 33
    assert suite["thresholds"]["teacher_refusals"] == 11
    assert suite["thresholds"]["dense_misses"] == 0


def test_final_quality_cannot_pass_without_successor_manifest_and_scope_registry() -> (
    None
):
    suite = load_draft_suite(ROOT)
    with pytest.raises(SuiteFailure, match="final.*binding"):
        require_final_binding(ROOT, suite)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s["collections"].pop(next(iter(s["collections"]))),
        lambda s: s["collections"][next(iter(s["collections"]))]["positive"][0].update(
            expected_content_sha256="0" * 64
        ),
        lambda s: s["collections"][next(iter(s["collections"]))]["positive"][1].update(
            query="L'Union européenne dans l'enseignement"
        ),
        lambda s: s["collections"][next(iter(s["collections"]))].pop(
            "expected_citation"
        ),
        lambda s: s["thresholds"].update(student_positive_nonempty=0),
        lambda s: s["thresholds"].update(teacher_refusals=0),
        lambda s: s["collections"][next(iter(s["collections"]))].update(
            teacher_expected_http=200
        ),
        lambda s: s["thresholds"].update(dense_misses=1),
        lambda s: s.update(candidate_manifest_sha256="0" * 64),
    ],
)
def test_sabotage_rejected(mutation) -> None:
    suite = load_draft_suite(ROOT)
    altered = copy.deepcopy(suite)
    mutation(altered)
    with pytest.raises(SuiteFailure):
        validate_draft_suite(ROOT, altered)


def test_rehearsal_pdf_identity_cannot_replace_derivative_identity() -> None:
    suite = load_draft_suite(ROOT)
    altered = copy.deepcopy(suite)
    collection = next(iter(altered["collections"].values()))
    collection["positive"][0]["expected_content_sha256"] = collection[
        "expected_source_pdf_sha256"
    ]
    with pytest.raises(SuiteFailure, match="derivative"):
        validate_draft_suite(ROOT, altered)


def test_promoted_manifest_cannot_substitute_its_artifact_set(tmp_path: Path) -> None:
    suite = copy.deepcopy(load_draft_suite(ROOT))
    candidate = tmp_path / suite["candidate_manifest_path"]
    candidate.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / suite["candidate_manifest_path"], candidate)
    registry = tmp_path / "release" / "artifacts.release.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"artifacts": [{"content_sha256": "0" * 64}]}))
    manifest = tmp_path / "release" / "production-profile-gate.release.json"
    manifest.write_text(
        json.dumps(
            {
                "release_mode": "production",
                "promotion_status": "PROMOTABLE",
                "activation_status": "PRODUCTION_ACTIVATION_ALLOWED",
                "review_status": "REVIEWED",
                "expected_counts": {
                    "subjects": 11,
                    "unique_artifacts": 253,
                    "placements": 377,
                },
                "artifact_registry": {
                    "path": "artifacts.release.json",
                    "sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
                },
            }
        )
    )
    scopes = tmp_path / "scopes.json"
    scopes.write_text("{}")
    suite.update(
        status="BOUND",
        final_release_manifest_path=str(manifest.relative_to(tmp_path)),
        final_release_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        final_scope_registry_path=str(scopes.relative_to(tmp_path)),
        final_scope_registry_sha256=hashlib.sha256(scopes.read_bytes()).hexdigest(),
        final_checkout_sha="a" * 40,
    )
    with pytest.raises(SuiteFailure, match="canonical release verifier required"):
        require_final_binding(tmp_path, suite)


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "sabotage", ["empty_scopes", "cross_collection", "forged_checkout"]
)
def test_declarative_final_bindings_never_pass_without_canonical_evidence(
    tmp_path: Path,
    sabotage: str,
) -> None:
    suite = copy.deepcopy(load_draft_suite(ROOT))
    candidate_path = tmp_path / suite["candidate_manifest_path"]
    candidate_path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / suite["candidate_manifest_path"], candidate_path)
    candidate = json.loads(candidate_path.read_text())
    artifacts = []
    placements: dict[str, list[dict]] = {name: [] for name in suite["collections"]}
    for entry in candidate["entries"]:
        sha = entry["derivative_content_sha256"]
        artifacts.append(
            {
                "artifact_id": sha,
                "content_sha256": sha,
                "source_pdf_sha256": entry["source_content_sha256"],
                "citation": entry["citation"],
                "chunks": [
                    {
                        "chunk_id": hashlib.sha256(sha.encode()).hexdigest(),
                        "page_start": 1,
                    }
                ],
            }
        )
        for collection in entry["collections"]:
            placements[collection].append(
                {
                    "placement_id": hashlib.sha256(
                        f"{collection}:{sha}".encode()
                    ).hexdigest(),
                    "artifact_id": sha,
                    "collection": collection,
                    "visibility": "public",
                    "placement_status": "active",
                    "review_status": "reviewed",
                }
            )
    assert sum(map(len, placements.values())) == 377
    if sabotage == "cross_collection":
        target = "rag_nexus_dgemc_terminale_option"
        foreign = next(
            entry["derivative_content_sha256"]
            for entry in candidate["entries"]
            if target not in entry["collections"]
        )
        placements[target][0]["artifact_id"] = foreign
    release = tmp_path / "release"
    registry_sha = _write_json(
        release / "artifacts.release.json", {"artifacts": artifacts}
    )
    refs = []
    for collection, rows in placements.items():
        relative = f"subjects/{collection}.json"
        sha = _write_json(
            release / relative, {"collection": collection, "placements": rows}
        )
        refs.append({"collection": collection, "path": relative, "sha256": sha})
    manifest_sha = _write_json(
        release / "promoted.json",
        {
            "release_mode": "production",
            "promotion_status": "PROMOTABLE",
            "activation_status": "PRODUCTION_ACTIVATION_ALLOWED",
            "review_status": "REVIEWED",
            "expected_counts": {
                "subjects": 11,
                "unique_artifacts": 253,
                "placements": 377,
                "unique_chunks": 253,
            },
            "artifact_registry": {
                "path": "artifacts.release.json",
                "sha256": registry_sha,
            },
            "subjects": refs,
        },
    )
    scopes = (
        {}
        if sabotage == "empty_scopes"
        else {
            "entries": [
                {"collection": name, "scope_id": f"public_{name}", "roles": ["student"]}
                for name in suite["collections"]
            ]
        }
    )
    scope_sha = _write_json(release / "scopes.json", scopes)
    suite.update(
        status="BOUND",
        final_release_manifest_path="release/promoted.json",
        final_release_manifest_sha256=manifest_sha,
        final_scope_registry_path="release/scopes.json",
        final_scope_registry_sha256=scope_sha,
        final_checkout_sha="f" * 40,
    )
    # The manifest is self-consistent enough to fool the former structural
    # checker, but none of these declarations is an authority receipt.
    with pytest.raises(SuiteFailure, match="canonical release verifier required"):
        require_final_binding(tmp_path, suite)


def test_dense_tie_overflow_is_recorded_and_not_counted_as_a_miss() -> None:
    suite = load_draft_suite(ROOT)
    counts = {name: 2 for name in suite["collections"]}
    probe = {
        "provenance": {
            "final_release_manifest_sha256": "a" * 64,
            "checkout_sha": "b" * 40,
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "collections": {
            name: {
                "chunks": 2,
                "rappel_a_1": 1,
                "rappel_a_5": 1,
                "manques": 0,
                "refus_egalite": 1,
            }
            for name in counts
        },
    }
    assert check_dense_tie_probe(suite, probe, counts, "a" * 64, "b" * 40) == 11
    bad = copy.deepcopy(probe)
    bad["collections"][next(iter(counts))]["refus_egalite"] = 0
    with pytest.raises(SuiteFailure, match="tie overflow"):
        check_dense_tie_probe(suite, bad, counts, "a" * 64, "b" * 40)
