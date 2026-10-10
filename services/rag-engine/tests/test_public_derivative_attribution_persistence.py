"""Attribution d'un dérivé étudiant, du catalogue scellé jusqu'au retrieval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import ingestor.governed_publisher_v2 as publisher_module
from ingestor.governed_publisher_v2 import (
    GovernedArtifact,
    PublicationChunk,
    _publication_chunks,
)
from ingestor.ingestion_worker.publication_resume import (
    PublicationResumeError,
    _sealed_derivative_attribution,
)
from ingestor.ingestion_worker.storage import (
    SealedArtifactDigestError,
    make_sealed_derivative_receipt_reader,
)
from ingestor.retrieval_pg_v2 import _map_row
from tests.test_retrieval_pg_v2 import SCOPE, _row

TEXT = b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\ncontenu natif gouverne\n"
SHA = hashlib.sha256(TEXT).hexdigest()
ATTRIBUTION = {
    "licensor": "Direction générale de l'enseignement scolaire",
    "licence_id": "ETALAB-2.0",
    "source_updated_at": "2026-10-10T06:04:23.168Z",
    "derivative_notice": "Extrait textuel dérivé, source Éduscol citée.",
}


def _derivative(**overrides: object) -> GovernedArtifact:
    fields: dict[str, object] = {
        "content": TEXT,
        "content_sha256": SHA,
        "source_label": "Ressource Éduscol",
        "source_uri": "https://eduscol.education.gouv.fr/source.pdf",
        "rights": "officiel_public",
        "official": True,
        "source_kind": "eduscol",
        "type_doc": "ressource_officielle",
        "mime_detected": "text/plain; charset=utf-8",
        "sealed_chunk_sha256": ("a" * 64,),
        "sealed_derivative_receipt": {"kind": "verified"},
        **ATTRIBUTION,
    }
    fields.update(overrides)
    fields.setdefault(
        "sealed_chunk_ids",
        tuple(
            hashlib.sha256(f"{SHA}:{index}:{chunk_sha}".encode()).hexdigest()
            for index, chunk_sha in enumerate(fields["sealed_chunk_sha256"])
        ),
    )
    return GovernedArtifact(**fields)  # type: ignore[arg-type]


def test_public_derivative_requires_complete_attribution() -> None:
    assert _derivative().source_updated_at == ATTRIBUTION["source_updated_at"]
    for field in ATTRIBUTION:
        with pytest.raises(ValueError, match="attribution"):
            _derivative(**{field: None})
    with pytest.raises(ValueError, match="receipt"):
        _derivative(sealed_derivative_receipt=None)


def test_public_derivative_chunk_ids_must_match_sealed_sha_before_write() -> None:
    with pytest.raises(ValueError, match="chunk_id"):
        _derivative(sealed_chunk_ids=("0" * 64,))
    with pytest.raises(ValueError, match="chunk_id"):
        _derivative(sealed_chunk_ids=None)


def test_sealed_derivative_citation_must_match_governed_source_and_pdf() -> None:
    entry = {
        "media_type": "text/plain; charset=utf-8",
        "source_pdf_sha256": "f" * 64,
        "citation": {
            "source_uri": "https://eduscol.education.gouv.fr/source.pdf",
            "source_label": "Ressource Éduscol",
            "source_pdf_sha256": "f" * 64,
            **ATTRIBUTION,
        },
    }
    assert _sealed_derivative_attribution(
        entry,
        source_uri="https://eduscol.education.gouv.fr/source.pdf",
        source_label="Ressource Éduscol",
    ) == ATTRIBUTION
    entry["citation"]["source_pdf_sha256"] = "e" * 64
    with pytest.raises(PublicationResumeError, match="attribution"):
        _sealed_derivative_attribution(
            entry,
            source_uri="https://eduscol.education.gouv.fr/source.pdf",
            source_label="Ressource Éduscol",
        )


def test_retrieval_projects_durable_attribution_and_legacy_is_empty() -> None:
    governed = _row(
        doc_id=SHA,
        artifact_id=SHA,
        content_sha256=SHA,
        placement_id="a" * 64,
        placement_source_scope="scope",
        placement_source_id="source-id",
        placement_source_path="source.txt",
        licensor=ATTRIBUTION["licensor"],
        licence_id=ATTRIBUTION["licence_id"],
        source_updated_at=ATTRIBUTION["source_updated_at"],
        derivative_notice=ATTRIBUTION["derivative_notice"],
        is_text_derivative=True,
    )
    candidate = _map_row(governed, "lexical", SCOPE)
    assert candidate.licensor == ATTRIBUTION["licensor"]
    assert candidate.licence_id == ATTRIBUTION["licence_id"]
    assert candidate.source_updated_at == ATTRIBUTION["source_updated_at"]
    assert candidate.derivative_notice == ATTRIBUTION["derivative_notice"]
    assert candidate.is_text_derivative is True

    legacy = _map_row(_row(), "lexical", SCOPE)
    assert legacy.licensor is None
    assert legacy.licence_id is None
    assert legacy.source_updated_at is None
    assert legacy.derivative_notice is None
    assert legacy.is_text_derivative is False


def test_derivative_marker_refuses_loss_of_all_four_attribution_fields() -> None:
    from ingestor.retrieval_hybrid_v2 import RetrievalPipelineError

    with pytest.raises(RetrievalPipelineError, match="derivative attribution"):
        _map_row(_row(is_text_derivative=True), "lexical", SCOPE)


def test_product_migration_006_is_additive_and_nullable_for_legacy_pdfs() -> None:
    migrations = Path(__file__).resolve().parents[1] / "infra/postgres/migrations"
    assert (migrations / "HEAD").read_text().strip() == (
        "006_public_derivative_attribution"
    )
    sql = (migrations / "006_public_derivative_attribution.sql").read_text()
    for field in ATTRIBUTION:
        assert f"{field} TEXT" in sql
        assert f"{field} ~ '[^[:space:]]'" in sql
    assert "is_text_derivative BOOLEAN NOT NULL DEFAULT false" in sql
    assert "is_text_derivative AND" in sql
    assert "UPDATE public.rag_artifacts" not in sql
    assert "DELETE FROM" not in sql


def test_receipt_reader_refuses_changed_cas_bytes(tmp_path: Path) -> None:
    receipt = {"kind": "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"}
    raw = json.dumps(receipt).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / "derivative_receipts" / f"{digest}.json"
    path.parent.mkdir()
    path.write_bytes(raw)
    read = make_sealed_derivative_receipt_reader(tmp_path)
    assert read(receipt_path=f"derivative_receipts/{digest}.json",
                receipt_sha256=digest) == receipt
    path.write_bytes(b"{}")
    with pytest.raises(SealedArtifactDigestError, match="digest"):
        read(receipt_path=f"derivative_receipts/{digest}.json",
             receipt_sha256=digest)


def test_publisher_never_sends_sealed_derivative_to_generic_chunker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []

    def verified(**kwargs: object) -> tuple[object, ...]:
        observed.append(kwargs["receipt"])
        return (PublicationChunk("Leçon", 1, 1),)

    monkeypatch.setattr(
        publisher_module, "chunk_publication",
        lambda **_kwargs: pytest.fail("generic chunker must not see derivative bytes"),
    )
    monkeypatch.setattr(publisher_module, "chunk_verified_derivative", verified)
    assert len(_publication_chunks(
        _derivative(sealed_chunk_sha256=(hashlib.sha256("Leçon".encode()).hexdigest(),)),
        extract_text=lambda _raw: pytest.fail("no flat text"),
        token_counter=object(),
    )) == 1
    assert observed == [{"kind": "verified"}]
