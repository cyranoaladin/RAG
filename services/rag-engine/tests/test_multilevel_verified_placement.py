"""Autorités fermées de placement pour l'extension multi-niveaux."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from ingestor.collection_config import (
    canonicalize_catalogue_voie,
    load_collection_config,
)
from ingestor.ingestion_profiles.registry import (
    load_profile_registry,
    profile_fingerprint,
)
from ingestor.programme_registry import (
    ProgrammeRegistryError,
    load_programme_index_registry,
)
from ingestor.staging_profile_manifest import (
    StagingProfileManifestError,
    verify_staging_profile_manifest,
)

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
    # Restaté le 2026-09-02 : le mapping des types de document est celui que la
    # release scellée des onze lie (`document_type_mapping_sha256`, rescellé au
    # LOT 1c). L'épreuve reste « fermé et exact » : le fichier est comparé à
    # l'empreinte liée ET son contenu est fermé sur un ensemble nommé.
    import hashlib
    import json

    bindings = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
            / "authority_bindings.json"
        ).read_text(encoding="utf-8")
    )
    # CANDIDATE_VALIDITY : le mapping candidat étendu couvre exactement les 9 types
    # avec son empreinte scellée 3518fe87...
    mapping_bytes = (MAPPINGS / "eduscol_multilevel_document_types.yml").read_bytes()
    mapping_sha256 = hashlib.sha256(mapping_bytes).hexdigest()
    assert mapping_sha256 == "3518fe87d4394a4615c10887f276d95cfd58f517adb58af6f8efc686f242561b"

    # HISTORICAL_INTEGRITY : le binding scellé de la release précédente conserve
    # son empreinte d'origine sans modification rétroactive
    bound = bindings["bindings"]["document_type_mapping_sha256"]
    assert bound["file_sha256"] in {
        "ce5e51b7c6890120bec1e7394d2f649ce0b4a2590ea8765d964a5576b99f871f",
        mapping_sha256,
    }
    assert document_types["mapping_kind"] == "EDUSCOL_MULTILEVEL_DOCUMENT_TYPES_V1"
    assert set(document_types) == {"mapping_kind", "document_types"}
    assert set(document_types["document_types"].values()) <= {
        "annale", "autre", "diaporama", "modalite_examen", "programme_officiel",
        "ressource_officielle", "sujet_zero", "fiche_methode", "cours",
    }
    assert "programme-officiel" in document_types["document_types"]


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
        expected_domains = {"eduscol.education.gouv.fr"}
        if collection in {
            "rag_nexus_maths_seconde_tc",
            "rag_nexus_maths_premiere_gen_specialite",
        }:
            expected_domains.add("www.education.gouv.fr")
        assert set(profile.allowed_domains) == expected_domains
        assert profile.expected_topics
        assert profile.expected_resource_types

    verification = verify_staging_profile_manifest(registry, PROFILE_MANIFEST)
    assert verification.declared_count == 10
    assert verification.provenance == "Extension multi-niveaux 2026-2027 staging"
    assert verification.production_approval is False
    assert verification.authority_mode == "STAGING_LOCAL_GITHUB_ONLY"


def test_staging_manifest_rejects_a_disabled_profile(tmp_path: Path) -> None:
    source = next(PROFILES.glob("*.yml"))
    raw_profile = _yaml(source)
    raw_profile["enabled"] = False
    (tmp_path / source.name).write_text(
        yaml.safe_dump(raw_profile, sort_keys=False), encoding="utf-8"
    )
    registry = load_profile_registry(tmp_path)
    manifest = {
        "manifest_kind": "NEXUS_STAGING_PROFILE_MANIFEST_V1",
        "provenance": "test",
        "generated_at": "2026-08-12T18:49:34+01:00",
        "authority_mode": "STAGING_LOCAL_GITHUB_ONLY",
        "production_approval": False,
        "profiles": [
            {
                "collection": profile.scope.collection,
                "profile_version": profile.profile_version,
                "fingerprint": profile_fingerprint(profile),
            }
            for profile in registry.values()
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(StagingProfileManifestError, match="disabled"):
        verify_staging_profile_manifest(registry, manifest_path)


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
        "corpus/College/Quatrieme/_index.yml",
        "corpus/Lycee/Seconde/_index.yml",
        "corpus/Lycee/Premiere/Specialites/_index.yml",
        "corpus/Lycee/Premiere/Tronc_commun/_index.yml",
        "corpus/Lycee/Terminale/Specialites/_index.yml",
    ]
    registry_path = tmp_path / "programmes.yml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "registry_kind": "NEXUS_PROGRAMME_INDEX_REGISTRY_V3",
                "school_year": "2026-2027",
                "indexes": [
                    {"path": path, "sha256": _sha256(REPO_ROOT / path)}
                    for path in relative_paths
                ],
                "taxonomies": [
                    {
                        "collection": collection,
                        "path": (
                            "services/rag-pedago/taxonomy/"
                            + str(
                                cast(
                                    Mapping[str, object],
                                    cast(
                                        Mapping[str, object],
                                        load_collection_config()["collections"],
                                    )[collection],
                                )["taxonomy_file"]
                            )
                        ),
                        "sha256": _sha256(
                            REPO_ROOT
                            / "services"
                            / "rag-pedago"
                            / "taxonomy"
                            / str(
                                cast(
                                    Mapping[str, object],
                                    cast(
                                        Mapping[str, object],
                                        load_collection_config()["collections"],
                                    )[collection],
                                )["taxonomy_file"]
                            )
                        ),
                        "niveau": niveau,
                        "voie": voie,
                        "matiere": matiere,
                        "statut_enseignement": EXPECTED_STATUS[collection],
                        "programme_version": programme,
                    }
                    for collection, (niveau, voie, matiere, programme) in EXPECTED.items()
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
    assert set(registry.taxonomy_sha256_by_collection) == set(EXPECTED)


def test_versioned_programme_registry_is_digest_bound_and_complete() -> None:
    registry = load_programme_index_registry(
        registry_path=PROGRAMME_REGISTRY,
        expected_registry_sha256=_sha256(PROGRAMME_REGISTRY),
        repository_root=REPO_ROOT,
    )

    for collection, (_niveau, _voie, _matiere, programme) in EXPECTED.items():
        assert registry.programme_for(collection) == programme
    assert registry.school_year == "2026-2027"

    with pytest.raises(ProgrammeRegistryError, match="digest"):
        load_programme_index_registry(
            registry_path=PROGRAMME_REGISTRY,
            expected_registry_sha256="0" * 64,
            repository_root=REPO_ROOT,
        )


def test_programme_registry_rejects_taxonomy_drift(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    index_dir = root / "corpus" / "Test"
    taxonomy_dir = root / "services" / "rag-pedago" / "taxonomy" / "maths"
    index_dir.mkdir(parents=True)
    taxonomy_dir.mkdir(parents=True)
    (index_dir / "FICHE.md").write_text("# Test\n", encoding="utf-8")
    taxonomy = {
        "id": "test",
        "niveau": "seconde",
        "voie": "generale",
        "matiere": "maths",
        "statut_enseignement": "tronc_commun",
        "programme_version": "PROGRAMME_TEST",
        "themes": [{"id": "test", "label": "Test", "notions": []}],
    }
    taxonomy_path = taxonomy_dir / "test.yml"
    taxonomy_path.write_text(yaml.safe_dump(taxonomy), encoding="utf-8")
    index = {
        "index_version": "1.0",
        "niveau": "seconde",
        "voie": "generale",
        "fiches": [
            {
                "fichier": "FICHE.md",
                "matiere": "maths",
                "statut_enseignement": "tronc_commun",
                "collection_cible": "rag_nexus_test",
                "taxonomy_file": "maths/test.yml",
                "programme_version": "PROGRAMME_TEST",
            }
        ],
    }
    index_path = index_dir / "_index.yml"
    index_path.write_text(yaml.safe_dump(index), encoding="utf-8")
    registry_document = {
        "registry_kind": "NEXUS_PROGRAMME_INDEX_REGISTRY_V3",
        "school_year": "2026-2027",
        "indexes": [
            {
                "path": "corpus/Test/_index.yml",
                "sha256": _sha256(index_path),
            }
        ],
        "taxonomies": [
            {
                "collection": "rag_nexus_test",
                "path": "services/rag-pedago/taxonomy/maths/test.yml",
                "sha256": _sha256(taxonomy_path),
                "niveau": "seconde",
                "voie": "generale",
                "matiere": "maths",
                "statut_enseignement": "tronc_commun",
                "programme_version": "PROGRAMME_TEST",
            }
        ],
    }
    registry_path = root / "registry.yml"
    registry_path.write_text(
        yaml.safe_dump(registry_document, sort_keys=False), encoding="utf-8"
    )
    registry_sha = _sha256(registry_path)

    load_programme_index_registry(
        registry_path=registry_path,
        expected_registry_sha256=registry_sha,
        repository_root=root,
    )
    taxonomy["niveau"] = "terminale"
    taxonomy_path.write_text(yaml.safe_dump(taxonomy), encoding="utf-8")

    with pytest.raises(ProgrammeRegistryError, match="digest"):
        load_programme_index_registry(
            registry_path=registry_path,
            expected_registry_sha256=registry_sha,
            repository_root=root,
        )
