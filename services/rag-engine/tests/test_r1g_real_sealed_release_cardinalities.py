"""R1G, section 9: proof against the REAL, currently-sealed, versioned
release authority -- no PostgreSQL, no synthetic fixture. Loads
``production-profile-gate-2026-2027-v1`` exactly as the R1 exporter and
verifier both do (``load_release_registry_file``, unmodified, digest-pinned
by the same ``EXPECTED_SEALED_RELEASE_REGISTRY_SHA256`` the real Phase A/B
flow uses) and derives the pré-GO forensic's reconciled cardinalities FROM
that authority -- they are not asserted as free-standing business literals
anywhere else in this suite. A mutant subject file (one byte changed) must
make the load itself fail closed, proving the comparison is not vacuous.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.r1_operator_flow import (  # noqa: E402
    _RELEASE_REGISTRY_RELATIVE_PATH,
    EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
)
from nexus_release_chain.release_readiness import (  # noqa: E402
    ReleaseReadinessError,
    load_release_registry_file,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / _RELEASE_REGISTRY_RELATIVE_PATH


def _load():
    return load_release_registry_file(REGISTRY_PATH, EXPECTED_SEALED_RELEASE_REGISTRY_SHA256)


@pytest.mark.skipif(
    not REGISTRY_PATH.exists(),
    reason="real sealed release tree not present in this checkout",
)
def test_real_sealed_v1_release_cardinalities_match_pre_go_forensic_reconciliation() -> None:
    registry = _load()
    artifacts = [
        artifact for manifest in registry.manifests for artifact in manifest.expectation.artifacts
    ]
    placements = [
        placement
        for manifest in registry.manifests
        for placement in manifest.expectation.placements
    ]

    unique_artifact_shas = {artifact.content_sha256 for artifact in artifacts}
    unique_chunk_ids = {
        str(chunk["chunk_id"]) for artifact in artifacts for chunk in artifact.chunks
    }
    chunks_per_artifact = {artifact.content_sha256: len(artifact.chunks) for artifact in artifacts}
    # 12403 = sum, over every one of the 486 promoted PLACEMENTS, of its
    # owning artifact's chunk count -- not the deduplicated physical chunk
    # count (8324). A shared artifact's chunks are re-summed once per
    # subject placement that reaches it, exactly as issue #155's own
    # ``sealed_release_chunks=12403`` / rehearsal_v2's
    # ``unique_chunks: 8324`` distinction states.
    placement_weighted_chunks = sum(
        chunks_per_artifact[placement.artifact_id] for placement in placements
    )

    assert len(unique_artifact_shas) == 319
    assert len(placements) == 486
    assert len(unique_chunk_ids) == 8324
    assert placement_weighted_chunks == 12403


@pytest.mark.skipif(
    not REGISTRY_PATH.exists(),
    reason="real sealed release tree not present in this checkout",
)
def test_tampered_subject_chunk_byte_fails_the_real_release_load(tmp_path: Path) -> None:
    """A mutant: one byte changed in one committed subject file, everything
    else byte-identical. ``load_release_registry_file`` must refuse before
    any cardinality could even be computed -- proving the digest chain, not
    merely the four literals above, is what R1G's chunk authority rests on."""
    release_root = REGISTRY_PATH.parent
    mutated_root = tmp_path / "release"
    shutil.copytree(release_root, mutated_root)

    registry_payload = json.loads((mutated_root / "release-registry.json").read_text("utf-8"))
    aggregate_relative = registry_payload["releases"][0]["manifest_path"]
    aggregate_payload = json.loads((mutated_root / aggregate_relative).read_text("utf-8"))
    subject_relative = aggregate_payload["subjects"][0]["path"]
    subject_path = (mutated_root / aggregate_relative).parent / subject_relative

    subject_payload = json.loads(subject_path.read_text("utf-8"))
    tampered_chunk_sha = subject_payload["artifacts"][0]["chunks"][0]["chunk_sha256"]
    flipped = ("0" if tampered_chunk_sha[0] != "0" else "1") + tampered_chunk_sha[1:]
    subject_payload["artifacts"][0]["chunks"][0]["chunk_sha256"] = flipped
    subject_path.write_text(json.dumps(subject_payload), encoding="utf-8")

    with pytest.raises(ReleaseReadinessError, match="digest mismatch"):
        load_release_registry_file(
            mutated_root / "release-registry.json", EXPECTED_SEALED_RELEASE_REGISTRY_SHA256
        )
