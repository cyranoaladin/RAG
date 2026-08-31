from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    CorpusChunkBinding,
    CorpusResourceVersion,
    RetrievalScopeArtifactV3,
    ServableCorpus,
    ServableCorpusIndexPayload,
    ServableCorpusManifestPayload,
    SupportedManifest,
    seal_servable_corpus_index,
    seal_servable_corpus_manifest,
)
from test_aria_retrieval_scope_v3 import aria_scope_payload


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")


def _manifest_payload() -> ServableCorpusManifestPayload:
    scope = deepcopy(aria_scope_payload())
    scope["scope_id"] = "aria_maths_terminale_v1"
    scope["target_policy"]["niveau"] = "terminale"  # type: ignore[index]
    scope["evidence_subject"]["niveau"] = "terminale"  # type: ignore[index]
    scope["evidence_subject"]["collection"] = "terminale_maths"  # type: ignore[index]
    return ServableCorpusManifestPayload(
        protocol_version="1",
        manifest_version="2026-08-30.1",
        resource_registry_version="1",
        resource_registry_sha256=SHA_A,
        producer_repository="cyranoaladin/RAG",
        producer_commit=SHA_B[:40],
        generated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        corpora=[
            ServableCorpus(
                corpus_id="aria-maths-terminale",
                corpus_version_id="2026-08-30.1",
                academic_year="2026-2027",
                curriculum_version="fr-national-2026",
                physical_collection="terminale_maths",
                retrieval_scope=RetrievalScopeArtifactV3.model_validate(scope),
                resources=[
                    CorpusResourceVersion(
                        resource_id=RESOURCE_ID,
                        resource_version_id=VERSION_ID,
                        content_sha256=SHA_B,
                        chunks=[
                            CorpusChunkBinding(
                                chunk_id="chunk-001",
                                locator={"page": 3},
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_manifest_sealing_is_deterministic_and_self_verifying() -> None:
    first = seal_servable_corpus_manifest(_manifest_payload())
    second = seal_servable_corpus_manifest(_manifest_payload())

    assert first == second
    assert first.manifest_sha256 == first.compute_sha256()
    assert first.corpora[0].resources[0].resource_version_id == VERSION_ID
    assert first.corpora[0].resources[0].content_sha256 == SHA_B
    assert first.corpora[0].retrieval_scope.scope_id == "aria_maths_terminale_v1"


def test_manifest_cannot_carry_scope_id_or_digest_that_drift_from_policy() -> None:
    payload = _manifest_payload().model_dump(mode="python")
    payload["corpora"][0]["scope_id"] = "other_scope"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ServableCorpusManifestPayload.model_validate(payload)

    payload = _manifest_payload().model_dump(mode="python")
    payload["corpora"][0]["scope_sha256"] = SHA_C
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ServableCorpusManifestPayload.model_validate(payload)


def test_manifest_rejects_duplicate_resource_versions_and_chunks() -> None:
    payload = _manifest_payload().model_dump(mode="python")
    resource = payload["corpora"][0]["resources"][0]
    payload["corpora"][0]["resources"].append(dict(resource))
    with pytest.raises(ValidationError, match="resource_version_id"):
        ServableCorpusManifestPayload.model_validate(payload)

    payload = _manifest_payload().model_dump(mode="python")
    chunk = payload["corpora"][0]["resources"][0]["chunks"][0]
    payload["corpora"][0]["resources"][0]["chunks"].append(dict(chunk))
    with pytest.raises(ValidationError, match="chunk_id"):
        ServableCorpusManifestPayload.model_validate(payload)


def test_manifest_contract_is_strict() -> None:
    payload = _manifest_payload().model_dump(mode="python")
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ServableCorpusManifestPayload.model_validate(payload)


def test_manifest_requires_explicit_academic_applicability() -> None:
    payload = _manifest_payload().model_dump(mode="python")
    del payload["corpora"][0]["academic_year"]
    with pytest.raises(ValidationError, match="academic_year"):
        ServableCorpusManifestPayload.model_validate(payload)

    payload = _manifest_payload().model_dump(mode="python")
    payload["corpora"][0]["academic_year"] = "2026-2028"
    with pytest.raises(ValidationError, match="academic_year"):
        ServableCorpusManifestPayload.model_validate(payload)


def test_index_supports_only_active_n_and_optional_n_minus_one() -> None:
    active = seal_servable_corpus_manifest(_manifest_payload())
    previous_payload = _manifest_payload().model_copy(
        update={"manifest_version": "2026-08-29.1"}
    )
    previous = seal_servable_corpus_manifest(previous_payload)
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)

    index = seal_servable_corpus_index(
        ServableCorpusIndexPayload(
            protocol_version="1",
            producer_repository="cyranoaladin/RAG",
            producer_commit=SHA_B[:40],
            generated_at=now,
            resource_registry_sha256=SHA_A,
            active_manifest_sha256=active.manifest_sha256,
            supported_manifests=[
                SupportedManifest(
                    manifest_version=active.manifest_version,
                    manifest_sha256=active.manifest_sha256,
                    retire_at=None,
                ),
                SupportedManifest(
                    manifest_version=previous.manifest_version,
                    manifest_sha256=previous.manifest_sha256,
                    retire_at=now + timedelta(days=14),
                ),
            ],
        )
    )

    assert len(index.supported_manifests) == 2
    assert index.index_sha256 == index.compute_sha256()

    bad = index.payload().model_copy(
        update={"active_manifest_sha256": SHA_C}
    )
    with pytest.raises(ValidationError, match="active_manifest_sha256"):
        ServableCorpusIndexPayload.model_validate(bad.model_dump(mode="python"))


def test_index_rejects_n_minus_two() -> None:
    active = seal_servable_corpus_manifest(_manifest_payload())
    entry = SupportedManifest(
        manifest_version=active.manifest_version,
        manifest_sha256=active.manifest_sha256,
        retire_at=None,
    )
    with pytest.raises(ValidationError, match="at most 2"):
        ServableCorpusIndexPayload(
            protocol_version="1",
            producer_repository="cyranoaladin/RAG",
            producer_commit=SHA_B[:40],
            generated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
            resource_registry_sha256=SHA_A,
            active_manifest_sha256=active.manifest_sha256,
            supported_manifests=[entry, entry.model_copy(), entry.model_copy()],
        )
