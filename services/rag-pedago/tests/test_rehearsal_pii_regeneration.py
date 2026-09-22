"""Lot CV — la répétition réémet la preuve PII au lieu de la recopier.

Le candidat `profile_gate_v2` embarquait une preuve PII recopiée de la release
source : 486 entrées pour 319 contenus, produites par un scanner (8ec8af55…)
que son manifeste ne déclare pas (388e3ed4…). Rien ne confrontait les deux.

Ces épreuves fixent :

- un miroir organisé par chemins est accepté, chaque fichier re-haché ;
- la preuve PII est produite par la fonction de production `_pii_evidence`,
  une entrée par contenu, sur la seule population conservée ;
- les chunks ne sont PAS recalculés : la découpe de la release source est
  conservée, et ses pages vides doivent être celles que le scan observe ;
- une release complète dont la preuve PII nomme un autre scanner que son
  manifeste refuse d'être écrite.

Fixtures synthétiques : aucun réseau, aucun miroir réel.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[3]
REAL_MATRIX = ROOT / "docs/reports/handoff/servability_matrix_v1.json"
REAL_EXCLUSION_REGISTRY = (
    ROOT / "docs/reports/evidence/release_currentness_exclusion_registry.json"
)
SERVED_RELEASE_ROOT = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
PHYSICAL_PATH = "01_EDUSCOL_OFFICIEL/LYCEE/NSI/commun.pdf"


def _builder() -> Any:
    from conftest import load_producer

    return load_producer()


def _pdf(*texts: str | None) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _mirror(tmp_path: Path, content: bytes) -> Path:
    root = tmp_path / "mirror"
    path = root / PHYSICAL_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return root


def _rows(sha: str) -> list[dict[str, Any]]:
    return [
        {
            "content_sha256": sha,
            "physical_path": PHYSICAL_PATH,
            "source_url": "https://eduscol.education.gouv.fr/1/nsi",
            "current_download_url": "",
            "title": "Ressource",
            "external_document_type": "ressource",
            "collection": collection,
            "source_placement_id": f"placement-{index}",
            "external_scope": "lycee/general/nsi",
            "drive_modified_time": "2026-08-04T00:00:00Z",
        }
        for index, collection in enumerate(
            ("rag_nexus_nsi_premiere_specialite", "rag_nexus_nsi_terminale_specialite")
        )
    ]


def _preflight(sha: str, ignored: list[int]) -> dict[str, dict[str, Any]]:
    return {
        sha: {
            "content_sha256": sha,
            "source_path": PHYSICAL_PATH,
            "page_count": 2,
            "ignored_empty_pages": ignored,
            "chunks": [{"chunk_id": "c" * 64}],
        }
    }


# --- miroir organisé par chemins ----------------------------------------------


def test_a_path_organized_mirror_is_read_and_every_file_rehashed(tmp_path: Path) -> None:
    builder = _builder()
    content = _pdf("Bonjour")
    sha = hashlib.sha256(content).hexdigest()
    root = _mirror(tmp_path, content)

    verified = builder.validate_pdf_mirror(
        pdf_root=root, content_sha256=[sha, sha], physical_paths={sha: PHYSICAL_PATH}
    )

    assert verified[sha].content == content
    (root / PHYSICAL_PATH).write_bytes(content + b"%altere")
    with pytest.raises(ValueError, match="digest differs"):
        builder.validate_pdf_mirror(
            pdf_root=root, content_sha256=[sha], physical_paths={sha: PHYSICAL_PATH}
        )
    with pytest.raises(ValueError, match="missing"):
        builder.validate_pdf_mirror(
            pdf_root=root,
            content_sha256=[sha],
            physical_paths={sha: "../../etc/passwd"},
        )


# --- la preuve PII réémise ----------------------------------------------------


def test_rehearsal_pii_is_regenerated_per_content_without_rechunking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _builder()
    content = _pdf(None, "Contenu pedagogique")
    sha = hashlib.sha256(content).hexdigest()
    root = _mirror(tmp_path, content)

    def no_rechunk(**_kwargs: object) -> None:
        raise AssertionError("la répétition ne recalcule pas les chunks")

    monkeypatch.setattr(builder, "chunk_publication", no_rechunk)

    evidence = builder._rehearsal_pii_evidence(
        _rows(sha),
        pdf_root=root,
        inventory_sha256="f" * 64,
        review_authority=builder.NO_REVIEW_AUTHORITY,
        preflight_by_sha=_preflight(sha, [1]),
    )

    assert evidence["scanner_sha256"] == hashlib.sha256(
        builder.PII_SCANNER_PATH.read_bytes()
    ).hexdigest()
    assert evidence["candidate_inventory_sha256"] == "f" * 64
    assert [row["content_sha256"] for row in evidence["results"]] == [sha]
    assert evidence["results"][0]["status"] == "CLEARED"
    assert evidence["results"][0]["ignored_empty_pages"] == [1]
    assert evidence["required_pdf_path_count"] == 1


def test_rehearsal_refuses_source_chunks_whose_empty_pages_the_scan_contradicts(
    tmp_path: Path,
) -> None:
    builder = _builder()
    content = _pdf(None, "Contenu pedagogique")
    sha = hashlib.sha256(content).hexdigest()
    root = _mirror(tmp_path, content)

    with pytest.raises(ValueError, match="ignored_empty_pages"):
        builder._rehearsal_pii_evidence(
            _rows(sha),
            pdf_root=root,
            inventory_sha256="f" * 64,
            review_authority=builder.NO_REVIEW_AUTHORITY,
            preflight_by_sha=_preflight(sha, []),
        )


def test_the_review_chain_bindings_name_the_four_injected_files(tmp_path: Path) -> None:
    builder = _builder()
    paths = {name: tmp_path / f"{name}.json" for name in ("d", "r", "a", "i")}
    authority = builder.ReviewAuthorityInputs(
        paths["d"], paths["r"], paths["a"], paths["i"], ("abenrhouma",)
    )

    assert builder._review_chain_authority_paths(authority) == {
        "pii_decision_set_sha256": paths["d"],
        "pii_review_receipt_sha256": paths["r"],
        "pii_review_trust_anchor_sha256": paths["a"],
        "pii_review_index_sha256": paths["i"],
    }
    assert builder._review_chain_authority_paths(builder.NO_REVIEW_AUTHORITY) == {}


# --- la garde : scanner de la preuve == scanner du manifeste -----------------


def test_the_pii_scanner_guard_refuses_the_v2_inconsistency() -> None:
    builder = _builder()
    declared = {"authorities": {"pii_scanner_sha256": "3" * 64}}

    builder.require_pii_evidence_names_the_declared_scanner(
        {"scanner_sha256": "3" * 64}, declared
    )
    with pytest.raises(ValueError, match="scanner"):
        builder.require_pii_evidence_names_the_declared_scanner(
            {"scanner_sha256": "8" * 64}, declared
        )
    with pytest.raises(ValueError, match="scanner"):
        builder.require_pii_evidence_names_the_declared_scanner(None, declared)
    with pytest.raises(ValueError, match="scanner"):
        builder.require_pii_evidence_names_the_declared_scanner(
            {"scanner_sha256": "3" * 64}, {"authorities": {}}
        )


def test_a_rehearsal_that_copies_the_old_pii_evidence_is_never_written(
    tmp_path: Path,
) -> None:
    """Sans miroir, la répétition recopie la preuve PII source — celle du
    scanner 8ec8af55… — sous un manifeste qui déclare le scanner courant.
    C'est exactement le défaut du candidat V2 : l'écriture est refusée."""
    builder = _builder()
    registry = builder.load_and_validate_exclusion_registry(REAL_EXCLUSION_REGISTRY)
    authority = builder.load_governed_currentness_authority(
        REAL_MATRIX, hashlib.sha256(REAL_MATRIX.read_bytes()).hexdigest()
    )
    documents = builder.build_release(
        release_mode="rehearsal",
        source_release_root=SERVED_RELEASE_ROOT,
        release_id="production-profile-gate-2026-2027-lot-cv-pii-guard",
        exclusion_registry=registry,
        currentness_authority=authority,
    )
    evidence = json.loads(documents[builder.RELEASE_ROOT / "pii_evidence.json"])
    aggregate = json.loads(
        documents[builder.RELEASE_ROOT / "production-profile-gate.release.json"]
    )
    assert evidence["scanner_sha256"] != aggregate["authorities"]["pii_scanner_sha256"]

    out = tmp_path / "out"
    with pytest.raises(ValueError, match="scanner"):
        builder._write_documents(documents, output_dir=out)
    assert not any(out.glob("release-*"))


# --- ADR-0059 §6 : la garde de couverture pour un index canonique ---------


def _digest(shas: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(shas)) + "\n").encode()).hexdigest()


PRODUCED = {"1" * 64, "2" * 64, "3" * 64}


def _scope(builder: Any, **overrides: Any) -> Any:
    values = {
        "reviewed_bundle_contents": frozenset({"1" * 64}),
        "produced_contents": frozenset(PRODUCED),
        "detected_contents": frozenset({"1" * 64}),
        "decided_contents": frozenset({"1" * 64}),
    }
    values.update({k: frozenset(v) for k, v in overrides.items()})
    return builder.CanonicalReviewScope(**values)


def test_a_canonical_review_covering_the_release_passes() -> None:
    builder = _builder()
    builder.require_review_covers_produced_content_set(
        reviewed_content_set_sha256=_digest(PRODUCED),
        produced_content_set_sha256=_digest(PRODUCED),
        canonical_scope=_scope(builder),
    )


@pytest.mark.parametrize(
    ("reviewed", "overrides", "motif"),
    [
        # 1. la population revue n'est pas la release
        (PRODUCED - {"3" * 64}, {}, "covered content set"),
        # 2. un paquet revu hors release
        (PRODUCED, {"reviewed_bundle_contents": {"1" * 64, "9" * 64}}, "bundle"),
        # 3a. une détection produite sans décision
        (PRODUCED, {"detected_contents": {"1" * 64, "2" * 64}}, "no human decision"),
        # 3b. une décision hors release
        (PRODUCED, {"decided_contents": {"1" * 64, "9" * 64}}, "outside the release"),
    ],
    ids=("population", "paquet-hors-release", "detection-non-decidee", "decision-hors-release"),
)
def test_each_clause_of_the_canonical_rule_refuses(
    reviewed: set[str], overrides: dict[str, Any], motif: str
) -> None:
    builder = _builder()
    with pytest.raises(ValueError, match=motif):
        builder.require_review_covers_produced_content_set(
            reviewed_content_set_sha256=_digest(reviewed),
            produced_content_set_sha256=_digest(PRODUCED),
            canonical_scope=_scope(builder, **overrides),
        )


def test_the_historical_rule_is_unchanged() -> None:
    builder = _builder()
    builder.require_review_covers_produced_content_set(
        reviewed_content_set_sha256=_digest(PRODUCED),
        produced_content_set_sha256=_digest(PRODUCED),
    )
    with pytest.raises(ValueError, match="covered content set"):
        builder.require_review_covers_produced_content_set(
            reviewed_content_set_sha256=_digest(PRODUCED | {"9" * 64}),
            produced_content_set_sha256=_digest(PRODUCED),
        )


def test_a_canonical_index_is_bound_by_its_review_input_population(tmp_path: Path) -> None:
    """Pour un index canonique, la population revue est
    `review_input_content_set_sha256` ; `content_set_sha256` n'est que
    l'ensemble des paquets et doit leur correspondre."""
    builder = _builder()
    bundles = [{"content_sha256": "1" * 64, "bundle_sha256": "f" * 64}]
    canonical = {
        "review_input_schema": "NEXUS-CANONICAL-REVIEW-INPUT-V1",
        "review_input_content_set_sha256": _digest(PRODUCED),
        "content_set_sha256": _digest({"1" * 64}),
        "bundles": bundles,
    }
    assert builder._reviewed_population(canonical) == (True, _digest(PRODUCED))
    historical = {"content_set_sha256": _digest(PRODUCED), "bundles": bundles}
    assert builder._reviewed_population(historical) == (False, _digest(PRODUCED))
    with pytest.raises(ValueError, match="bundle set"):
        builder._reviewed_population({**canonical, "content_set_sha256": _digest(PRODUCED)})
    with pytest.raises(ValueError, match="review_input_content_set_sha256"):
        builder._reviewed_population({**canonical, "review_input_content_set_sha256": None})
