"""Autorités fermées de placement pour l'extension multi-niveaux."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from ingestor.collection_config import (
    canonicalize_catalogue_voie,
    load_collection_config,
)
from ingestor.ingestion_profiles.registry import load_profile_registry
from ingestor.multilevel_mapping import (
    MultilevelMappingError,
    load_multilevel_mapping,
)
from ingestor.programme_registry import load_programme_index_registry
from ingestor.staging_profile_manifest import verify_staging_profile_manifest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
MAPPINGS = ENGINE_ROOT / "configs" / "mappings"
PROFILES = ENGINE_ROOT / "configs" / "ingestion_profiles" / "staging" / "multilevel"
PROFILE_MANIFEST = (
    ENGINE_ROOT / "configs" / "ingestion_profiles" / "staging" / "multilevel_manifest.json"
)
PROGRAMME_REGISTRY = (
    ENGINE_ROOT / "configs" / "programme_indexes" / "multilevel_2026_2027.yml"
)

EXPECTED = {
    "rag_nexus_maths_seconde_tc": (
        "seconde",
        "generale",
        "maths",
        "BOEN_14_2026-04-02_MENE2602914A",
    ),
    "rag_nexus_francais_seconde_tc": (
        "seconde",
        "generale",
        "francais",
        "BOEN_special_1_2019-01-22",
    ),
    "rag_nexus_maths_quatrieme_tc": (
        "quatrieme",
        "college",
        "maths",
        "BOEN_special_11_2018-07-26_aj_2020",
    ),
    "rag_nexus_francais_quatrieme_tc": (
        "quatrieme",
        "college",
        "francais",
        "BOEN_special_11_2018-07-26_aj_2020",
    ),
    "rag_nexus_maths_premiere_gen_specialite": (
        "premiere",
        "generale",
        "maths",
        "BOEN_14_2026-04-02_MENE2602917A",
    ),
    "rag_nexus_nsi_premiere_specialite": (
        "premiere",
        "generale",
        "nsi",
        "BOEN_special_1_2019-01-22",
    ),
    "rag_nexus_francais_premiere_tc": (
        "premiere",
        "generale",
        "francais",
        "BOEN_special_1_2019-01-22",
    ),
    "rag_nexus_maths_terminale_gen_specialite": (
        "terminale",
        "generale",
        "maths",
        "BOEN_special_8_2019-07-25",
    ),
    "rag_nexus_nsi_terminale_specialite": (
        "terminale",
        "generale",
        "nsi",
        "BOEN_special_8_2019-07-25",
    ),
    "rag_nexus_pc_terminale_specialite": (
        "terminale",
        "generale",
        "physique_chimie",
        "BOEN_special_8_2019-07-25",
    ),
}

EXPECTED_STATUS = {
    "rag_nexus_maths_seconde_tc": "tronc_commun",
    "rag_nexus_francais_seconde_tc": "tronc_commun",
    "rag_nexus_maths_quatrieme_tc": "tronc_commun",
    "rag_nexus_francais_quatrieme_tc": "tronc_commun",
    "rag_nexus_maths_premiere_gen_specialite": "specialite",
    "rag_nexus_nsi_premiere_specialite": "specialite",
    "rag_nexus_francais_premiere_tc": "tronc_commun",
    "rag_nexus_maths_terminale_gen_specialite": "specialite",
    "rag_nexus_nsi_terminale_specialite": "specialite",
    "rag_nexus_pc_terminale_specialite": "specialite",
}


def _yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_multilevel_mappings_are_closed_and_exact() -> None:
    levels = _yaml(MAPPINGS / "eduscol_multilevel_levels.yml")
    subjects = _yaml(MAPPINGS / "eduscol_multilevel_subjects.yml")
    document_types = _yaml(MAPPINGS / "eduscol_multilevel_document_types.yml")

    assert levels == {
        "mapping_kind": "EDUSCOL_MULTILEVEL_LEVELS_V1",
        "external_levels": {
            "4e": "quatrieme",
            "seconde": "seconde",
            "premiere": "premiere",
            "terminale": "terminale",
        },
    }
    assert subjects == {
        "mapping_kind": "EDUSCOL_MULTILEVEL_SUBJECTS_V1",
        "external_subjects": {
            "mathematiques": "maths",
            "francais": "francais",
            "nsi": "nsi",
            "physique-chimie": "physique_chimie",
        },
    }
    assert document_types == {
        "mapping_kind": "EDUSCOL_MULTILEVEL_DOCUMENT_TYPES_V1",
        "document_types": {
            "diaporama": "diaporama",
            "programme-officiel": "programme_officiel",
            "reperes-attendus": "ressource_officielle",
            "ressource-accompagnement": "ressource_officielle",
        },
    }

    mapping = load_multilevel_mapping(
        levels_path=MAPPINGS / "eduscol_multilevel_levels.yml",
        expected_levels_sha256=_sha256(
            MAPPINGS / "eduscol_multilevel_levels.yml"
        ),
        subjects_path=MAPPINGS / "eduscol_multilevel_subjects.yml",
        expected_subjects_sha256=_sha256(
            MAPPINGS / "eduscol_multilevel_subjects.yml"
        ),
        document_types_path=MAPPINGS / "eduscol_multilevel_document_types.yml",
        expected_document_types_sha256=_sha256(
            MAPPINGS / "eduscol_multilevel_document_types.yml"
        ),
    )
    facts = mapping.resolve(
        external_level="terminale",
        external_subject="physique-chimie",
        external_document_type="programme-officiel",
    )
    assert facts.niveau.value == "terminale"
    assert facts.matiere == "physique_chimie"
    assert facts.type_doc.value == "programme_officiel"

    with pytest.raises(MultilevelMappingError, match="level"):
        mapping.resolve(
            external_level="cycle-4",
            external_subject="francais",
            external_document_type="reperes-attendus",
        )
    with pytest.raises(MultilevelMappingError, match="subject"):
        mapping.resolve(
            external_level="seconde",
            external_subject="hlp",
            external_document_type="programme-officiel",
        )
    with pytest.raises(MultilevelMappingError, match="document type"):
        mapping.resolve(
            external_level="premiere",
            external_subject="francais",
            external_document_type="autre",
        )


def test_multilevel_profiles_are_exact_and_fail_closed() -> None:
    registry = load_profile_registry(PROFILES)

    assert set(registry) == {(collection, "multilevel-v1") for collection in EXPECTED}
    for collection, (niveau, voie, matiere, programme) in EXPECTED.items():
        profile = registry[(collection, "multilevel-v1")]
        assert profile.enabled is True
        assert profile.scope.collection == collection
        assert profile.scope.niveau.value == niveau
        assert profile.scope.voie.value == voie
        assert profile.scope.matiere == matiere
        assert profile.scope.school_year == "2026-2027"
        assert str(profile.scope.programme_version) == programme
        assert profile.scope.visibility == "internal"
        assert profile.publication.mode == "human_review"
        assert profile.publication.auto_publish is False
        assert profile.allowed_domains == ["eduscol.education.gouv.fr"]
        assert profile.expected_topics
        assert profile.expected_resource_types

    verification = verify_staging_profile_manifest(registry, PROFILE_MANIFEST)
    assert verification.declared_count == 10
    assert verification.provenance == "Extension multi-niveaux 2026-2027 staging"
    assert verification.production_approval is False
    assert verification.authority_mode == "STAGING_LOCAL_GITHUB_ONLY"


def test_multilevel_collections_match_governed_profiles() -> None:
    collections = cast(
        Mapping[str, Mapping[str, object]],
        load_collection_config()["collections"],
    )
    for collection, (niveau, voie, matiere, _programme) in EXPECTED.items():
        definition = collections[collection]
        assert definition["niveau"] == niveau
        assert canonicalize_catalogue_voie(definition["voie"]) == voie
        assert definition["matiere"] == matiere
        assert definition["statut"] == EXPECTED_STATUS[collection]

    assert collections["rag_nexus_maths_seconde_tc"]["voie"] == "generale"
    assert collections["rag_nexus_francais_seconde_tc"]["voie"] == "generale"


def test_multilevel_taxonomies_match_collection_and_programme_authorities() -> None:
    collections = cast(
        Mapping[str, Mapping[str, object]],
        load_collection_config()["collections"],
    )
    for collection, (niveau, voie, matiere, programme) in EXPECTED.items():
        definition = collections[collection]
        taxonomy = _yaml(
            REPO_ROOT
            / "services"
            / "rag-pedago"
            / "taxonomy"
            / str(definition["taxonomy_file"])
        )
        assert taxonomy["niveau"] == niveau
        assert taxonomy["voie"] == voie
        assert taxonomy["matiere"] == matiere
        assert taxonomy["statut_enseignement"] == EXPECTED_STATUS[collection]
        assert taxonomy["programme_version"] == programme
        assert taxonomy["themes"]


@pytest.mark.parametrize(
    ("index_path", "collection", "programme"),
    [
        (
            "corpus/Lycee/Premiere/Specialites/_index.yml",
            "rag_nexus_nsi_premiere_specialite",
            "BOEN_special_1_2019-01-22",
        ),
        (
            "corpus/Lycee/Terminale/Specialites/_index.yml",
            "rag_nexus_nsi_terminale_specialite",
            "BOEN_special_8_2019-07-25",
        ),
    ],
)
def test_nsi_has_grade_specific_canonical_programme_index(
    index_path: str, collection: str, programme: str
) -> None:
    document = _yaml(REPO_ROOT / index_path)
    raw_fiches = cast(list[Mapping[str, Any]], document["fiches"])
    entries = [
        entry
        for entry in raw_fiches
        if entry.get("collection_cible") == collection
    ]
    assert len(entries) == 1
    assert entries[0]["programme_version"] == programme
    assert (REPO_ROOT / Path(index_path).parent / entries[0]["fichier"]).is_file()


def test_programme_registry_loads_multiple_grade_indexes(tmp_path: Path) -> None:
    relative_paths = [
        "corpus/Lycee/Seconde/_index.yml",
        "corpus/Lycee/Premiere/Specialites/_index.yml",
        "corpus/Lycee/Premiere/Tronc_commun/_index.yml",
        "corpus/Lycee/Terminale/Specialites/_index.yml",
    ]
    registry_path = tmp_path / "programmes.yml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "registry_kind": "NEXUS_PROGRAMME_INDEX_REGISTRY_V2",
                "school_year": "2026-2027",
                "indexes": [
                    {"path": path, "sha256": _sha256(REPO_ROOT / path)}
                    for path in relative_paths
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    registry = load_programme_index_registry(
        registry_path=registry_path,
        expected_registry_sha256=_sha256(registry_path),
        repository_root=REPO_ROOT,
    )

    assert registry.programme_for("rag_nexus_maths_seconde_tc") == (
        "BOEN_14_2026-04-02_MENE2602914A"
    )
    assert registry.programme_for("rag_nexus_nsi_premiere_specialite") == (
        "BOEN_special_1_2019-01-22"
    )
    assert registry.programme_for("rag_nexus_nsi_terminale_specialite") == (
        "BOEN_special_8_2019-07-25"
    )


def test_versioned_programme_registry_is_digest_bound_and_complete() -> None:
    registry = load_programme_index_registry(
        registry_path=PROGRAMME_REGISTRY,
        expected_registry_sha256=_sha256(PROGRAMME_REGISTRY),
        repository_root=REPO_ROOT,
    )

    for collection, (_niveau, _voie, _matiere, programme) in EXPECTED.items():
        assert registry.programme_for(collection) == programme
    assert registry.school_year == "2026-2027"

    with pytest.raises(Exception, match="digest"):
        load_programme_index_registry(
            registry_path=PROGRAMME_REGISTRY,
            expected_registry_sha256="0" * 64,
            repository_root=REPO_ROOT,
        )
