"""Inventaire multi-niveaux déterministe et fermé."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "services" / "rag-pedago" / "scripts" / "build_multilevel_release.py"


class MultilevelBuilder(Protocol):
    TARGET_MATRIX: tuple[dict[str, str], ...]

    def build_candidate_inventory(
        self,
        catalog: dict[str, Any],
        *,
        sealed_catalog_sha256: str,
        official_sources: dict[str, Any],
        catalog_delta: dict[str, Any] | None = None,
        catalog_delta_sha256: str | None = None,
    ) -> dict[str, Any]: ...

    def canonical_json_bytes(self, value: object) -> bytes: ...

    def build_currentness_evidence(
        self,
        inventory: dict[str, Any],
        *,
        candidate_inventory_sha256: str,
        audited_currentness: dict[str, Any],
        audited_currentness_sha256: str,
    ) -> dict[str, Any]: ...

    def main(self, argv: list[str] | None = None) -> int: ...


def _module() -> MultilevelBuilder:
    spec = importlib.util.spec_from_file_location("build_multilevel_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(MultilevelBuilder, module)


def test_target_matrix_is_exact_and_ordered() -> None:
    builder = _module()

    assert builder.TARGET_MATRIX == (
        {
            "phase": "A",
            "collection": "rag_nexus_maths_seconde_tc",
            "external_level": "seconde",
            "external_subject": "mathematiques",
            "external_scope": "lycee/commun/mathematiques",
        },
        {
            "phase": "A",
            "collection": "rag_nexus_francais_seconde_tc",
            "external_level": "seconde",
            "external_subject": "francais",
            "external_scope": "lycee/commun/francais",
        },
        {
            "phase": "A",
            "collection": "rag_nexus_maths_quatrieme_tc",
            "external_level": "4e",
            "external_subject": "mathematiques",
            "external_scope": "college/cycle-4/mathematiques",
        },
        {
            "phase": "A",
            "collection": "rag_nexus_francais_quatrieme_tc",
            "external_level": "4e",
            "external_subject": "francais",
            "external_scope": "college/cycle-4/francais",
        },
        {
            "phase": "B",
            "collection": "rag_nexus_maths_premiere_gen_specialite",
            "external_level": "premiere",
            "external_subject": "mathematiques",
            "external_scope": "lycee/commun/mathematiques",
        },
        {
            "phase": "B",
            "collection": "rag_nexus_nsi_premiere_specialite",
            "external_level": "premiere",
            "external_subject": "nsi",
            "external_scope": "lycee/general/nsi",
        },
        {
            "phase": "B",
            "collection": "rag_nexus_francais_premiere_tc",
            "external_level": "premiere",
            "external_subject": "francais",
            "external_scope": "lycee/commun/francais",
        },
        {
            "phase": "C",
            "collection": "rag_nexus_maths_terminale_gen_specialite",
            "external_level": "terminale",
            "external_subject": "mathematiques",
            "external_scope": "lycee/commun/mathematiques",
        },
        {
            "phase": "C",
            "collection": "rag_nexus_nsi_terminale_specialite",
            "external_level": "terminale",
            "external_subject": "nsi",
            "external_scope": "lycee/general/nsi",
        },
        {
            "phase": "C",
            "collection": "rag_nexus_pc_terminale_specialite",
            "external_level": "terminale",
            "external_subject": "physique-chimie",
            "external_scope": "lycee/seconde/physique-chimie",
        },
    )


def _placement(
    sha: str,
    *,
    level: str,
    subject: str,
    scope: str,
    placement_id: str,
) -> dict[str, object]:
    return {
        "content_sha256": sha,
        "level": level,
        "subject": subject,
        "scope": scope,
        "document_type": "programme-officiel",
        "status": "actuel",
        "title": f"Programme {level} {subject}",
        "year": "2019",
        "source_url": f"https://eduscol.education.fr/{placement_id}",
        "scope_path": placement_id,
    }


def _artifact(sha: str, placements: list[dict[str, object]]) -> dict[str, object]:
    return {
        "sha256": sha,
        "physical_object_count": 1,
        "physical_objects": [
            {
                "content_sha256": sha,
                "path": f"01_EDUSCOL_OFFICIEL/LYCEE/{sha[:8]}.pdf",
                "currentness": "unclassified",
                "disposition": "REVIEW_REQUIRED",
            }
        ],
        "pedagogical_placement_count": len(placements),
        "pedagogical_placements": placements,
    }


def _catalog(artifacts: dict[str, dict[str, object]]) -> dict[str, Any]:
    placement_count = sum(
        cast(int, artifact["pedagogical_placement_count"]) for artifact in artifacts.values()
    )
    return {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "verification_passed": True,
        "manifest_sha256": "a" * 64,
        "placement_catalog_sha256": "b" * 64,
        "content_artifact_count": len(artifacts),
        "physical_object_count": len(artifacts),
        "eduscol_placement_count": placement_count,
        "artifacts": artifacts,
    }


def _delta_addition(
    sha: str,
    *,
    source_placement: dict[str, object],
    target_collection: str,
    level: str,
    subject: str,
    scope: str,
    physical_path: str,
) -> dict[str, Any]:
    filename = f"programme-{sha[:10]}.pdf"
    return {
        "content_sha256": sha,
        "target_collection": target_collection,
        "physical_path": physical_path,
        "source_placement_id": source_placement["scope_path"],
        "reason_code": "EXACT_GRADE_PLACEMENT_PROOF",
        "placement_proof": {
            "proof_kind": "EXPLICIT_GOVERNED_EXACT_GRADE_PLACEMENT_V1",
            "source_catalog_placement_id": source_placement["scope_path"],
            "physical_object_reused": True,
            "pdf_bytes_added": False,
        },
        "placement": {
            "content_sha256": sha,
            "level": level,
            "subject": subject,
            "scope": scope,
            "document_type": source_placement["document_type"],
            "status": source_placement["status"],
            "title": source_placement["title"],
            "year": source_placement["year"],
            "source_url": source_placement["source_url"],
            "scope_path": f"par-scope/{scope}/{level}/programme-officiel/2019/{filename}",
            "level_path": (f"par-niveau/{level}/{subject}/programme-officiel/2019/{filename}"),
            "technical_path": (f"by_scope/{scope}/{level}/programme-officiel/2019/{filename}"),
            "source_object": source_placement.get(
                "source_object", f"objects/sha256/{sha[:2]}/{sha}.pdf"
            ),
            "family": "lycee-commun",
        },
    }


def _catalog_delta(
    builder: MultilevelBuilder,
    catalog: dict[str, Any],
    additions: list[dict[str, Any]],
    *,
    parent_catalog_sha256: str = "c" * 64,
) -> dict[str, Any]:
    return {
        "descriptor_kind": "MULTILEVEL_CATALOG_VNEXT_DESCRIPTOR_V1",
        "school_year": "2026-2027",
        "parent": {
            "sealed_catalog_sha256": parent_catalog_sha256,
            "corpus_manifest_sha256": catalog["manifest_sha256"],
            "placement_catalog_sha256": catalog["placement_catalog_sha256"],
            "content_artifact_count": catalog["content_artifact_count"],
            "physical_object_count": catalog["physical_object_count"],
            "pedagogical_placement_count": catalog["eduscol_placement_count"],
        },
        "delta": {
            "delta_kind": "APPEND_ONLY_EXACT_PLACEMENT_DELTA_V1",
            "physical_object_additions": [],
            "placement_additions": additions,
            "placement_additions_sha256": hashlib.sha256(
                builder.canonical_json_bytes(additions)
            ).hexdigest(),
        },
        "expected_vnext_counts": {
            "content_artifacts": catalog["content_artifact_count"],
            "physical_objects": catalog["physical_object_count"],
            "pedagogical_placements": catalog["eduscol_placement_count"] + len(additions),
        },
    }


def test_inventory_deduplicates_artifacts_and_counts_placements() -> None:
    builder = _module()
    maths_sha = "1" * 64
    french_sha = "2" * 64
    unrelated_sha = "3" * 64
    catalog = _catalog(
        {
            maths_sha: _artifact(
                maths_sha,
                [
                    _placement(
                        maths_sha,
                        level="seconde",
                        subject="mathematiques",
                        scope="lycee/commun/mathematiques",
                        placement_id="maths/programme",
                    ),
                    _placement(
                        maths_sha,
                        level="seconde",
                        subject="mathematiques",
                        scope="lycee/commun/mathematiques",
                        placement_id="maths/ressource",
                    ),
                ],
            ),
            french_sha: _artifact(
                french_sha,
                [
                    _placement(
                        french_sha,
                        level="seconde",
                        subject="francais",
                        scope="lycee/commun/francais",
                        placement_id="francais/programme",
                    )
                ],
            ),
            unrelated_sha: _artifact(
                unrelated_sha,
                [
                    _placement(
                        unrelated_sha,
                        level="cycle-4",
                        subject="mathematiques",
                        scope="college/cycle-4/mathematiques",
                        placement_id="maths/cycle4",
                    )
                ],
            ),
        }
    )

    inventory = builder.build_candidate_inventory(
        catalog,
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )

    assert inventory["counts"] == {
        "target_collections": 10,
        "unique_artifacts": 2,
        "placements": 3,
        "physical_objects": 2,
        "multi_placement_artifacts": 1,
    }
    maths = inventory["collections"][0]
    french = inventory["collections"][1]
    assert maths["counts"] == {
        "unique_artifacts": 1,
        "placements": 2,
        "physical_objects": 1,
        "multi_placement_artifacts": 1,
    }
    assert len(maths["candidates"]) == 1
    assert len(maths["candidates"][0]["placements"]) == 2
    assert french["counts"]["unique_artifacts"] == 1
    assert unrelated_sha not in {
        candidate["content_sha256"]
        for collection in inventory["collections"]
        for candidate in collection["candidates"]
    }


def test_empty_or_no_eligible_collection_records_six_discovery_routes() -> None:
    builder = _module()
    multi_sha = "4" * 64
    non_classe_sha = "5" * 64
    other_programme_sha = "6" * 64
    catalog = _catalog(
        {
            multi_sha: _artifact(
                multi_sha,
                [
                    _placement(
                        multi_sha,
                        level="multi-niveaux",
                        subject="physique-chimie",
                        scope="lycee/seconde/physique-chimie",
                        placement_id="pc/multi",
                    )
                ],
            ),
            non_classe_sha: _artifact(
                non_classe_sha,
                [
                    _placement(
                        non_classe_sha,
                        level="non-classe",
                        subject="physique-chimie",
                        scope="lycee/seconde/physique-chimie",
                        placement_id="pc/non-classe",
                    )
                ],
            ),
            other_programme_sha: _artifact(
                other_programme_sha,
                [
                    _placement(
                        other_programme_sha,
                        level="cycle-4",
                        subject="physique-chimie",
                        scope="college/cycle-4/physique-chimie",
                        placement_id="pc/programme",
                    )
                ],
            ),
        }
    )
    catalog["artifacts"][multi_sha]["physical_objects"][0]["path"] = (
        "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/PHYSIQUE_CHIMIE/programme.pdf"
    )
    inventory = builder.build_candidate_inventory(
        catalog,
        sealed_catalog_sha256="c" * 64,
        official_sources={
            "sources": [
                {
                    "id": "eduscol_pc_voie_gt",
                    "url": "https://eduscol.education.fr/5829/pc",
                    "status": "to_verify",
                    "collections_cibles": ["rag_nexus_pc_terminale_specialite"],
                }
            ]
        },
    )

    pc = inventory["collections"][-1]
    assert pc["counts"]["unique_artifacts"] == 0
    assert [route["route_id"] for route in pc["discovery_routes"]] == [
        "exact_placements",
        "physical_paths",
        "multi_niveaux",
        "non_classe",
        "subject_programme",
        "configured_official_sources",
    ]
    assert [route["unique_artifacts"] for route in pc["discovery_routes"]] == [
        0,
        1,
        1,
        1,
        3,
        0,
    ]
    assert pc["discovery_routes"][-1]["source_count"] == 1
    assert pc["discovery_routes"][-1]["sources"] == [
        {
            "id": "eduscol_pc_voie_gt",
            "status": "to_verify",
            "url": "https://eduscol.education.fr/5829/pc",
        }
    ]
    assert pc["inventory_disposition"] == "PLACEMENT_PROOF_OR_CORPUS_DELTA_REQUIRED"


def test_candidate_partition_has_no_gap() -> None:
    builder = _module()
    maths_sha = "1" * 64
    french_sha = "2" * 64
    inventory = builder.build_candidate_inventory(
        _catalog(
            {
                maths_sha: _artifact(
                    maths_sha,
                    [
                        _placement(
                            maths_sha,
                            level="seconde",
                            subject="mathematiques",
                            scope="lycee/commun/mathematiques",
                            placement_id="maths/programme",
                        )
                    ],
                ),
                french_sha: _artifact(
                    french_sha,
                    [
                        _placement(
                            french_sha,
                            level="seconde",
                            subject="francais",
                            scope="lycee/commun/francais",
                            placement_id="francais/programme",
                        )
                    ],
                ),
            }
        ),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )

    expected = {
        candidate["content_sha256"]
        for collection in inventory["collections"]
        for candidate in collection["candidates"]
    }
    categories = inventory["candidate_partition"]
    flattened = [sha for values in categories.values() for sha in values]
    assert set(flattened) == expected
    assert len(flattened) == len(set(flattened))
    assert categories == {
        "exact_grade_gate_pending": [maths_sha, french_sha],
        "named_noneligible": [],
        "unevaluated": [],
    }
    for collection in inventory["collections"]:
        local_expected = {candidate["content_sha256"] for candidate in collection["candidates"]}
        local_flattened = [
            sha for values in collection["candidate_partition"].values() for sha in values
        ]
        assert set(local_flattened) == local_expected
        assert len(local_flattened) == len(set(local_flattened))


def test_inventory_records_observed_values_and_is_byte_deterministic() -> None:
    builder = _module()
    sha = "1" * 64
    placements = [
        _placement(
            sha,
            level="seconde",
            subject="mathematiques",
            scope="lycee/commun/mathematiques",
            placement_id="z/placement",
        ),
        {
            **_placement(
                sha,
                level="seconde",
                subject="mathematiques",
                scope="lycee/commun/mathematiques",
                placement_id="a/placement",
            ),
            "document_type": "ressource-accompagnement",
            "status": "a-verifier",
        },
    ]
    inventory = builder.build_candidate_inventory(
        _catalog({sha: _artifact(sha, placements)}),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )

    maths = inventory["collections"][0]
    assert maths["observed_values"] == {
        "levels": ["seconde"],
        "subjects": ["mathematiques"],
        "scopes": ["lycee/commun/mathematiques"],
        "document_types": ["programme-officiel", "ressource-accompagnement"],
        "pedagogical_statuses": ["a-verifier", "actuel"],
        "physical_paths": [f"01_EDUSCOL_OFFICIEL/LYCEE/{sha[:8]}.pdf"],
    }
    first = builder.canonical_json_bytes(inventory)
    second = builder.canonical_json_bytes(
        builder.build_candidate_inventory(
            json.loads(json.dumps(_catalog({sha: _artifact(sha, placements)}))),
            sealed_catalog_sha256="c" * 64,
            official_sources={"sources": []},
        )
    )
    assert first == second
    assert first.endswith(b"\n")


def test_inventory_cli_writes_canonical_bytes(tmp_path: Path) -> None:
    builder = _module()
    sha = "1" * 64
    catalog_path = tmp_path / "catalog.json"
    sources_path = tmp_path / "sources.yml"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    catalog_path.write_text(
        json.dumps(
            _catalog(
                {
                    sha: _artifact(
                        sha,
                        [
                            _placement(
                                sha,
                                level="seconde",
                                subject="mathematiques",
                                scope="lycee/commun/mathematiques",
                                placement_id="maths/programme",
                            )
                        ],
                    )
                }
            )
        ),
        encoding="utf-8",
    )
    sources_path.write_text("sources: []\n", encoding="utf-8")

    for output in (first_path, second_path):
        assert (
            builder.main(
                [
                    "inventory",
                    "--catalog",
                    str(catalog_path),
                    "--official-sources",
                    str(sources_path),
                    "--output",
                    str(output),
                ]
            )
            == 0
        )

    assert first_path.read_bytes() == second_path.read_bytes()
    assert json.loads(first_path.read_bytes())["counts"]["target_collections"] == 10


def test_collection_partition_has_no_gap() -> None:
    builder = _module()
    sha = "1" * 64
    inventory = builder.build_candidate_inventory(
        _catalog(
            {
                sha: _artifact(
                    sha,
                    [
                        _placement(
                            sha,
                            level="seconde",
                            subject="mathematiques",
                            scope="lycee/commun/mathematiques",
                            placement_id="maths/programme",
                        )
                    ],
                )
            }
        ),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )

    expected = [row["collection"] for row in builder.TARGET_MATRIX]
    partition = inventory["collection_partition"]
    flattened = [collection for values in partition.values() for collection in values]
    assert set(flattened) == set(expected)
    assert len(flattened) == len(set(flattened)) == 10
    assert partition["exact_grade_gates_pending"] == ["rag_nexus_maths_seconde_tc"]
    assert partition["placement_proof_or_corpus_delta_required"] == expected[1:]
    assert partition["unevaluated"] == []


def test_append_only_delta_adds_exact_placements_without_mutating_parent() -> None:
    builder = _module()
    french_sha = "7" * 64
    pc_sha = "8" * 64
    french_source = _placement(
        french_sha,
        level="non-classe",
        subject="francais",
        scope="lycee/commun/francais",
        placement_id="francais/non-classe/programme",
    )
    pc_source = _placement(
        pc_sha,
        level="multi-niveaux",
        subject="physique-chimie",
        scope="lycee/seconde/physique-chimie",
        placement_id="pc/multi/programme",
    )
    catalog = _catalog(
        {
            french_sha: _artifact(french_sha, [french_source]),
            pc_sha: _artifact(pc_sha, [pc_source]),
        }
    )
    parent_snapshot = copy.deepcopy(catalog)
    additions = [
        _delta_addition(
            french_sha,
            source_placement=french_source,
            target_collection="rag_nexus_francais_premiere_tc",
            level="premiere",
            subject="francais",
            scope="lycee/commun/francais",
            physical_path=catalog["artifacts"][french_sha]["physical_objects"][0]["path"],
        ),
        _delta_addition(
            pc_sha,
            source_placement=pc_source,
            target_collection="rag_nexus_pc_terminale_specialite",
            level="terminale",
            subject="physique-chimie",
            scope="lycee/seconde/physique-chimie",
            physical_path=catalog["artifacts"][pc_sha]["physical_objects"][0]["path"],
        ),
    ]
    delta = _catalog_delta(builder, catalog, additions)

    inventory = builder.build_candidate_inventory(
        catalog,
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
        catalog_delta=delta,
        catalog_delta_sha256="d" * 64,
    )

    assert catalog == parent_snapshot
    assert inventory["catalog_delta_sha256"] == "d" * 64
    assert inventory["catalog_delta_payload_sha256"] == delta["delta"]["placement_additions_sha256"]
    assert inventory["counts"] == {
        "target_collections": 10,
        "unique_artifacts": 2,
        "placements": 2,
        "physical_objects": 2,
        "multi_placement_artifacts": 0,
    }
    french = inventory["collections"][6]
    pc = inventory["collections"][9]
    assert french["counts"]["unique_artifacts"] == 1
    assert pc["counts"]["unique_artifacts"] == 1
    assert french["candidates"][0]["placements"][0]["placement_origin"] == (
        "APPEND_ONLY_EXACT_PLACEMENT_DELTA_V1"
    )
    assert pc["candidates"][0]["placements"][0]["placement_origin"] == (
        "APPEND_ONLY_EXACT_PLACEMENT_DELTA_V1"
    )
    assert [route["route_id"] for route in pc["discovery_routes"]] == [
        "exact_placements",
        "physical_paths",
        "multi_niveaux",
        "non_classe",
        "subject_programme",
        "configured_official_sources",
    ]
    assert pc["discovery_routes"][0]["unique_artifacts"] == 1
    assert pc["discovery_routes"][2]["unique_artifacts"] == 1


def test_catalog_delta_is_digest_bound_and_fail_closed() -> None:
    builder = _module()
    sha = "8" * 64
    source = _placement(
        sha,
        level="multi-niveaux",
        subject="physique-chimie",
        scope="lycee/seconde/physique-chimie",
        placement_id="pc/multi/programme",
    )
    catalog = _catalog({sha: _artifact(sha, [source])})
    addition = _delta_addition(
        sha,
        source_placement=source,
        target_collection="rag_nexus_pc_terminale_specialite",
        level="terminale",
        subject="physique-chimie",
        scope="lycee/seconde/physique-chimie",
        physical_path=catalog["artifacts"][sha]["physical_objects"][0]["path"],
    )
    delta = _catalog_delta(builder, catalog, [addition])

    wrong_parent = copy.deepcopy(delta)
    wrong_parent["parent"]["sealed_catalog_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="parent sealed catalog SHA"):
        builder.build_candidate_inventory(
            catalog,
            sealed_catalog_sha256="c" * 64,
            official_sources={"sources": []},
            catalog_delta=wrong_parent,
            catalog_delta_sha256="d" * 64,
        )

    wrong_payload = copy.deepcopy(delta)
    wrong_payload["delta"]["placement_additions_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="placement additions digest"):
        builder.build_candidate_inventory(
            catalog,
            sealed_catalog_sha256="c" * 64,
            official_sources={"sources": []},
            catalog_delta=wrong_payload,
            catalog_delta_sha256="d" * 64,
        )

    wrong_target = copy.deepcopy(delta)
    wrong_target["delta"]["placement_additions"][0]["placement"]["level"] = "premiere"
    wrong_target["delta"]["placement_additions_sha256"] = hashlib.sha256(
        builder.canonical_json_bytes(wrong_target["delta"]["placement_additions"])
    ).hexdigest()
    with pytest.raises(ValueError, match="target matrix"):
        builder.build_candidate_inventory(
            catalog,
            sealed_catalog_sha256="c" * 64,
            official_sources={"sources": []},
            catalog_delta=wrong_target,
            catalog_delta_sha256="d" * 64,
        )


def test_catalog_never_promotes_a_route_hit_without_explicit_delta() -> None:
    builder = _module()
    sha = "8" * 64
    source = _placement(
        sha,
        level="multi-niveaux",
        subject="physique-chimie",
        scope="lycee/seconde/physique-chimie",
        placement_id="pc/multi/programme",
    )

    inventory = builder.build_candidate_inventory(
        _catalog({sha: _artifact(sha, [source])}),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )

    pc = inventory["collections"][9]
    assert pc["counts"]["unique_artifacts"] == 0
    assert pc["discovery_routes"][2]["unique_artifacts"] == 1
    assert pc["discovery_routes"][4]["unique_artifacts"] == 1
    assert pc["inventory_disposition"] == "PLACEMENT_PROOF_OR_CORPUS_DELTA_REQUIRED"


def test_inventory_cli_applies_only_the_explicit_delta(tmp_path: Path) -> None:
    builder = _module()
    sha = "8" * 64
    source = _placement(
        sha,
        level="multi-niveaux",
        subject="physique-chimie",
        scope="lycee/seconde/physique-chimie",
        placement_id="pc/multi/programme",
    )
    catalog = _catalog({sha: _artifact(sha, [source])})
    catalog_path = tmp_path / "catalog.json"
    sources_path = tmp_path / "sources.yml"
    delta_path = tmp_path / "catalog-vnext.json"
    output_path = tmp_path / "inventory.json"
    catalog_path.write_bytes(builder.canonical_json_bytes(catalog))
    catalog_sha = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    addition = _delta_addition(
        sha,
        source_placement=source,
        target_collection="rag_nexus_pc_terminale_specialite",
        level="terminale",
        subject="physique-chimie",
        scope="lycee/seconde/physique-chimie",
        physical_path=catalog["artifacts"][sha]["physical_objects"][0]["path"],
    )
    delta = _catalog_delta(
        builder,
        catalog,
        [addition],
        parent_catalog_sha256=catalog_sha,
    )
    delta_path.write_bytes(builder.canonical_json_bytes(delta))
    sources_path.write_text("sources: []\n", encoding="utf-8")

    assert (
        builder.main(
            [
                "inventory",
                "--catalog",
                str(catalog_path),
                "--catalog-delta",
                str(delta_path),
                "--official-sources",
                str(sources_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    inventory = json.loads(output_path.read_bytes())
    assert inventory["collections"][9]["counts"]["unique_artifacts"] == 1
    assert inventory["catalog_delta_sha256"] == hashlib.sha256(delta_path.read_bytes()).hexdigest()


def _audited_currentness(inventory_sha: str, current_shas: list[str]) -> dict[str, Any]:
    return {
        "audit_kind": "MULTILEVEL_CURRENTNESS_NETWORK_AUDIT_V1",
        "school_year": "2026-2027",
        "candidate_inventory_sha256": inventory_sha,
        "audit_mode": "READ_ONLY_REUSED_RESULTS",
        "results": [
            {
                "content_sha256": sha,
                "current_source_listing_url": (
                    f"https://eduscol.education.gouv.fr/{index}/listing"
                ),
                "current_download_url": (f"https://eduscol.education.gouv.fr/{index}/document.pdf"),
                "current_download_sha256": sha,
                "byte_identity": True,
                "current_for_school_year": "2026-2027",
            }
            for index, sha in enumerate(current_shas, start=1)
        ],
    }


def test_currentness_evidence_partitions_every_unique_artifact() -> None:
    builder = _module()
    current_sha = "1" * 64
    review_sha = "2" * 64
    inventory = builder.build_candidate_inventory(
        _catalog(
            {
                current_sha: _artifact(
                    current_sha,
                    [
                        _placement(
                            current_sha,
                            level="seconde",
                            subject="mathematiques",
                            scope="lycee/commun/mathematiques",
                            placement_id="maths/current",
                        )
                    ],
                ),
                review_sha: _artifact(
                    review_sha,
                    [
                        _placement(
                            review_sha,
                            level="seconde",
                            subject="francais",
                            scope="lycee/commun/francais",
                            placement_id="francais/review",
                        )
                    ],
                ),
            }
        ),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )
    inventory_sha = hashlib.sha256(builder.canonical_json_bytes(inventory)).hexdigest()
    audit = _audited_currentness(inventory_sha, [current_sha])

    evidence = builder.build_currentness_evidence(
        inventory,
        candidate_inventory_sha256=inventory_sha,
        audited_currentness=audit,
        audited_currentness_sha256="d" * 64,
    )

    assert evidence["evidence_kind"] == "MULTILEVEL_ARTIFACT_CURRENTNESS_V1"
    assert evidence["counts"] == {
        "artifacts": 2,
        "evaluated": 2,
        "current": 1,
        "review_required": 1,
        "unevaluated": 0,
        "by_collection": {
            "rag_nexus_maths_seconde_tc": {
                "artifacts": 1,
                "current": 1,
                "review_required": 0,
            },
            "rag_nexus_francais_seconde_tc": {
                "artifacts": 1,
                "current": 0,
                "review_required": 1,
            },
        },
    }
    assert evidence["partition"] == {
        "current": [current_sha],
        "review_required": [review_sha],
        "unevaluated": [],
    }
    by_sha = {row["content_sha256"]: row for row in evidence["artifacts"]}
    assert by_sha[current_sha]["decision"] == "CURRENT"
    assert by_sha[current_sha]["effective_currentness"] == "actuel"
    assert by_sha[current_sha]["byte_identity"] is True
    assert by_sha[current_sha]["current_download_sha256"] == current_sha
    assert by_sha[review_sha]["decision"] == "REVIEW_REQUIRED"
    assert by_sha[review_sha]["effective_currentness"] is None
    assert by_sha[review_sha]["byte_identity"] is None
    assert by_sha[review_sha]["reason_codes"] == [
        "CURRENT_SOURCE_BYTE_IDENTITY_NOT_AUDITED",
        "PROGRAMME_ALIGNMENT_REVIEW_REQUIRED",
    ]


def test_currentness_evidence_refuses_audit_drift_and_duplicate_sha() -> None:
    builder = _module()
    sha = "1" * 64
    inventory = builder.build_candidate_inventory(
        _catalog(
            {
                sha: _artifact(
                    sha,
                    [
                        _placement(
                            sha,
                            level="seconde",
                            subject="mathematiques",
                            scope="lycee/commun/mathematiques",
                            placement_id="maths/current",
                        )
                    ],
                )
            }
        ),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )
    inventory_sha = hashlib.sha256(builder.canonical_json_bytes(inventory)).hexdigest()
    audit = _audited_currentness(inventory_sha, [sha])

    wrong_inventory = copy.deepcopy(audit)
    wrong_inventory["candidate_inventory_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="candidate inventory"):
        builder.build_currentness_evidence(
            inventory,
            candidate_inventory_sha256=inventory_sha,
            audited_currentness=wrong_inventory,
            audited_currentness_sha256="d" * 64,
        )

    duplicate = copy.deepcopy(audit)
    duplicate["results"].append(copy.deepcopy(duplicate["results"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        builder.build_currentness_evidence(
            inventory,
            candidate_inventory_sha256=inventory_sha,
            audited_currentness=duplicate,
            audited_currentness_sha256="d" * 64,
        )

    unknown = _audited_currentness(inventory_sha, ["9" * 64])
    with pytest.raises(ValueError, match="outside candidate inventory"):
        builder.build_currentness_evidence(
            inventory,
            candidate_inventory_sha256=inventory_sha,
            audited_currentness=unknown,
            audited_currentness_sha256="d" * 64,
        )


def test_currentness_never_infers_current_from_catalog_status() -> None:
    builder = _module()
    sha = "1" * 64
    artifact = _artifact(
        sha,
        [
            _placement(
                sha,
                level="seconde",
                subject="mathematiques",
                scope="lycee/commun/mathematiques",
                placement_id="maths/status-current",
            )
        ],
    )
    physical_objects = cast(list[dict[str, Any]], artifact["physical_objects"])
    physical_objects[0]["currentness"] = "actuel"
    inventory = builder.build_candidate_inventory(
        _catalog({sha: artifact}),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )
    inventory_sha = hashlib.sha256(builder.canonical_json_bytes(inventory)).hexdigest()

    evidence = builder.build_currentness_evidence(
        inventory,
        candidate_inventory_sha256=inventory_sha,
        audited_currentness=_audited_currentness(inventory_sha, []),
        audited_currentness_sha256="d" * 64,
    )

    assert evidence["partition"]["current"] == []
    assert evidence["partition"]["review_required"] == [sha]


def test_currentness_cli_writes_digest_bound_canonical_evidence(tmp_path: Path) -> None:
    builder = _module()
    sha = "1" * 64
    inventory = builder.build_candidate_inventory(
        _catalog(
            {
                sha: _artifact(
                    sha,
                    [
                        _placement(
                            sha,
                            level="seconde",
                            subject="mathematiques",
                            scope="lycee/commun/mathematiques",
                            placement_id="maths/current",
                        )
                    ],
                )
            }
        ),
        sealed_catalog_sha256="c" * 64,
        official_sources={"sources": []},
    )
    inventory_path = tmp_path / "inventory.json"
    audit_path = tmp_path / "audit.json"
    output_path = tmp_path / "currentness.yml"
    inventory_path.write_bytes(builder.canonical_json_bytes(inventory))
    inventory_sha = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    audit_path.write_bytes(builder.canonical_json_bytes(_audited_currentness(inventory_sha, [sha])))

    assert (
        builder.main(
            [
                "currentness",
                "--inventory",
                str(inventory_path),
                "--audit-results",
                str(audit_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    evidence = json.loads(output_path.read_bytes())
    assert evidence["candidate_inventory_sha256"] == inventory_sha
    assert (
        evidence["currentness_audit_sha256"] == hashlib.sha256(audit_path.read_bytes()).hexdigest()
    )
    assert evidence["counts"]["evaluated"] == 1


def test_materialized_currentness_evidence_matches_exact_inventory_and_audit() -> None:
    builder = _module()
    release_dir = (
        ROOT
        / "services"
        / "rag-pedago"
        / "data"
        / "releases"
        / "prerentree_2026_2027"
        / "multilevel"
    )
    inventory_path = release_dir / "candidate_inventory.json"
    audit_path = release_dir / "currentness_network_audit.json"
    evidence_path = (
        ROOT
        / "services"
        / "rag-pedago"
        / "configs"
        / "prerentree_2026_2027"
        / "multilevel_currentness_evidence.yml"
    )
    inventory = json.loads(inventory_path.read_bytes())
    audit = json.loads(audit_path.read_bytes())
    evidence = json.loads(evidence_path.read_bytes())
    inventory_sha = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    audit_sha = hashlib.sha256(audit_path.read_bytes()).hexdigest()

    expected_current = {
        "05c5403d45bfc3631fa13b5c334822de09bcd68d850d0611044045cddba270de",
        "10ce34666edd722a3d8d86642a9f1ac205c7a9d128d6142a17effcba2fb85e69",
        "447bdee89af9f0ab07460bd279f81647824c2d91ba7be1eff6daa133c5e8467d",
        "5303df0fcf6335f06d00c969a61dcd82cc3fdfd105271ae5c2ef580ff49b6c08",
        "73c001b93cf2151924da5245c4d740b56a5194c17e29c37cda2e1c0593711fae",
        "7ca9a32e1823be6c1120cb0417324c3cb01688d1d194c7614a88ea851ccc60b0",
        "b54b6422d0eb2fb906e6ad6c79a2e95e6cae00e3fa113da5f7499eee4cc53ae7",
        "b88b5c685ec05d44b0c22d64f491443759fc0f544fe9ad33e626fb6cc29bf65a",
        "c07f8b2db9d22a6c2b9ab8386cf7ba323bc2c56abacb3f560dd97d02b383de18",
        "c4e3cc6fb201f4dabc78fa47206c1b498b3ed46496cf05165a74e0ecd8856fb1",
        "d0edabd6a21d6345d36d32c5506ddcf225e819ddca25d27c1ecc3f97b87a8966",
        "eb8369e7c1611e90f51491fecc5a7c2081a9c57f9c7fbb08d0414677b56ce16f",
    }
    inventory_shas = {
        candidate["content_sha256"]
        for collection in inventory["collections"]
        for candidate in collection["candidates"]
    }
    evidence_shas = {row["content_sha256"] for row in evidence["artifacts"]}

    assert inventory_sha == ("86531933e0779a739f20c347d32dd02e54672f058024d16e1198809cef965300")
    assert evidence["candidate_inventory_sha256"] == inventory_sha
    assert evidence["currentness_audit_sha256"] == audit_sha
    assert inventory_shas == evidence_shas
    assert set(evidence["partition"]["current"]) == expected_current
    assert {row["content_sha256"] for row in audit["results"]} == expected_current
    assert evidence["counts"]["artifacts"] == 150
    assert evidence["counts"]["evaluated"] == 150
    assert evidence["counts"]["current"] == 12
    assert evidence["counts"]["review_required"] == 138
    assert evidence["counts"]["unevaluated"] == 0
    assert evidence["partition"]["unevaluated"] == []
    assert all(
        row["reason_codes"] for row in evidence["artifacts"] if row["decision"] == "REVIEW_REQUIRED"
    )

    regenerated = builder.build_currentness_evidence(
        inventory,
        candidate_inventory_sha256=inventory_sha,
        audited_currentness=audit,
        audited_currentness_sha256=audit_sha,
    )
    assert builder.canonical_json_bytes(regenerated) == evidence_path.read_bytes()
