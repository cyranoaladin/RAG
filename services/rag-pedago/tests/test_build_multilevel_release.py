"""Inventaire multi-niveaux déterministe et fermé."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Protocol, cast

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
    ) -> dict[str, Any]: ...

    def canonical_json_bytes(self, value: object) -> bytes: ...

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
    return {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "verification_passed": True,
        "manifest_sha256": "a" * 64,
        "placement_catalog_sha256": "b" * 64,
        "artifacts": artifacts,
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
        local_expected = {
            candidate["content_sha256"] for candidate in collection["candidates"]
        }
        local_flattened = [
            sha
            for values in collection["candidate_partition"].values()
            for sha in values
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
    assert partition["exact_grade_gates_pending"] == [
        "rag_nexus_maths_seconde_tc"
    ]
    assert partition["placement_proof_or_corpus_delta_required"] == expected[1:]
    assert partition["unevaluated"] == []
