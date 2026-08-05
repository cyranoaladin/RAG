"""LOT44c : registre déclaratif de profils — chargement et sélection.

Périmètre strict : tests unitaires purs (aucun accès réseau, aucun
PostgreSQL). Aucun worker, aucun scheduler, aucun agent, aucun endpoint.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ingestor.ingestion_profiles.registry import (
    ProfileDisabledError,
    ProfileRegistryLoadError,
    ProfileUnknownError,
    load_profile_registry,
    profile_fingerprint,
    select_profile,
)

VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
        "title": "NSI Terminale Spécialité",
        "owner": "equipe-nsi",
        "expected_topics": ["algorithmique", "bases de données"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.6,
    }
    payload.update(overrides)
    return payload


def _write_profile(directory: Path, filename: str, **overrides: object) -> Path:
    path = directory / filename
    path.write_text(yaml.safe_dump(_profile_payload(**overrides)), encoding="utf-8")
    return path


class TestLoadProfileRegistry:
    def test_missing_directory_returns_empty_registry(self, tmp_path: Path) -> None:
        registry = load_profile_registry(tmp_path / "does-not-exist")
        assert registry == {}

    def test_empty_directory_returns_empty_registry(self, tmp_path: Path) -> None:
        registry = load_profile_registry(tmp_path)
        assert registry == {}

    def test_loads_valid_profile(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "nsi_terminale.yml")
        registry = load_profile_registry(tmp_path)
        key = ("rag_nexus_nsi_terminale_specialite", "v1")
        assert key in registry
        assert registry[key].enabled is True
        assert registry[key].profile_version == "v1"

    def test_structurally_invalid_profile_fails_entire_load(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "valid.yml")
        (tmp_path / "broken.yml").write_text(
            yaml.safe_dump({"profile_version": "v1"}), encoding="utf-8"
        )
        with pytest.raises(ProfileRegistryLoadError):
            load_profile_registry(tmp_path)

    def test_non_mapping_yaml_fails_load(self, tmp_path: Path) -> None:
        (tmp_path / "list.yml").write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")
        with pytest.raises(ProfileRegistryLoadError):
            load_profile_registry(tmp_path)

    def test_invalid_yaml_syntax_fails_load(self, tmp_path: Path) -> None:
        (tmp_path / "broken.yml").write_text("tenant: [unterminated", encoding="utf-8")
        with pytest.raises(ProfileRegistryLoadError):
            load_profile_registry(tmp_path)

    def test_duplicate_collection_and_version_across_files_is_rejected(
        self, tmp_path: Path
    ) -> None:
        _write_profile(tmp_path, "a.yml")
        _write_profile(tmp_path, "b.yml")
        with pytest.raises(ProfileRegistryLoadError, match="Duplicate"):
            load_profile_registry(tmp_path)

    def test_same_collection_different_version_is_not_a_duplicate(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml", profile_version="v1")
        _write_profile(tmp_path, "b.yml", profile_version="v2")
        registry = load_profile_registry(tmp_path)
        assert len(registry) == 2

    def test_loading_is_deterministic_regardless_of_filesystem_order(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "zzz.yml", profile_version="v1")
        _write_profile(tmp_path, "aaa.yml", profile_version="v2")
        first = load_profile_registry(tmp_path)
        second = load_profile_registry(tmp_path)
        assert first == second


class TestSelectProfile:
    def test_selects_known_enabled_profile(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "nsi.yml")
        registry = load_profile_registry(tmp_path)
        profile = select_profile(
            registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert profile.profile_version == "v1"

    def test_unknown_collection_is_rejected(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "nsi.yml")
        registry = load_profile_registry(tmp_path)
        with pytest.raises(ProfileUnknownError):
            select_profile(registry, collection="does_not_exist", profile_version="v1")

    def test_unknown_version_is_rejected(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "nsi.yml")
        registry = load_profile_registry(tmp_path)
        with pytest.raises(ProfileUnknownError):
            select_profile(
                registry,
                collection="rag_nexus_nsi_terminale_specialite",
                profile_version="v99",
            )

    def test_disabled_profile_is_rejected_distinctly_from_unknown(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "nsi.yml", enabled=False)
        registry = load_profile_registry(tmp_path)
        with pytest.raises(ProfileDisabledError):
            select_profile(
                registry,
                collection="rag_nexus_nsi_terminale_specialite",
                profile_version="v1",
            )

    def test_no_silent_default_profile_when_version_omitted_is_impossible(
        self, tmp_path: Path
    ) -> None:
        """La signature de select_profile impose collection ET profile_version :
        aucun appel ne peut omettre l'un des deux (TypeError, pas un défaut
        silencieux)."""
        _write_profile(tmp_path, "nsi.yml")
        registry = load_profile_registry(tmp_path)
        with pytest.raises(TypeError):
            select_profile(registry, collection="rag_nexus_nsi_terminale_specialite")  # type: ignore[call-arg]


class TestProfileVersionFormat:
    """L'identité d'un profil étant (collection, profile_version) — jamais
    un UUID — la stabilité de cette identité dépend de la forme de
    profile_version. Le contrat CollectionProfile (LOT44a, gelé) accepte
    n'importe quelle chaîne non vide ; le registre LOT44c impose une
    contrainte additionnelle, plus stricte, sans modifier le contrat."""

    def test_version_with_internal_whitespace_is_rejected(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "bad.yml", profile_version="v1 beta")
        with pytest.raises(ProfileRegistryLoadError, match="profile_version"):
            load_profile_registry(tmp_path)

    def test_version_that_is_only_whitespace_is_rejected(self, tmp_path: Path) -> None:
        """Passe le min_length=1 du contrat LOT44a (" " a une longueur de 1)
        mais doit être rejeté par la contrainte registre LOT44c."""
        _write_profile(tmp_path, "bad.yml", profile_version=" ")
        with pytest.raises(ProfileRegistryLoadError, match="profile_version"):
            load_profile_registry(tmp_path)

    def test_version_exceeding_max_length_is_rejected(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "bad.yml", profile_version="v" * 65)
        with pytest.raises(ProfileRegistryLoadError, match="profile_version"):
            load_profile_registry(tmp_path)

    def test_conventional_version_strings_are_accepted(self, tmp_path: Path) -> None:
        for version in ("v1", "2026.08.04", "v1_beta", "release-1"):
            (tmp_path / f"{version.replace('.', '_')}.yml").write_text(
                yaml.safe_dump(_profile_payload(profile_version=version)), encoding="utf-8"
            )
        registry = load_profile_registry(tmp_path)
        assert len(registry) == 4


class TestProfileFingerprint:
    def test_fingerprint_is_deterministic_for_identical_content(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "nsi.yml")
        registry = load_profile_registry(tmp_path)
        profile = select_profile(
            registry, collection="rag_nexus_nsi_terminale_specialite", profile_version="v1"
        )
        assert profile_fingerprint(profile) == profile_fingerprint(profile)

    def test_fingerprint_differs_for_different_content_under_a_new_identity(
        self, tmp_path: Path
    ) -> None:
        _write_profile(tmp_path, "a.yml", profile_version="v1", title="Titre A")
        _write_profile(tmp_path, "b.yml", profile_version="v2", title="Titre B")
        registry = load_profile_registry(tmp_path)
        fp_a = profile_fingerprint(
            select_profile(
                registry, collection="rag_nexus_nsi_terminale_specialite", profile_version="v1"
            )
        )
        fp_b = profile_fingerprint(
            select_profile(
                registry, collection="rag_nexus_nsi_terminale_specialite", profile_version="v2"
            )
        )
        assert fp_a != fp_b

    def test_fingerprint_is_independent_of_yaml_key_order(self, tmp_path: Path) -> None:
        """La sérialisation canonique (json.dumps sort_keys=True sur le
        modèle Pydantic déjà validé) ne dépend jamais de l'ordre des clés
        du fichier YAML source."""
        payload = _profile_payload()
        reordered = dict(reversed(list(payload.items())))
        (tmp_path / "a.yml").write_text(yaml.safe_dump(payload), encoding="utf-8")
        registry_a = load_profile_registry(tmp_path)

        (tmp_path / "a.yml").unlink()
        (tmp_path / "b.yml").write_text(yaml.safe_dump(reordered), encoding="utf-8")
        registry_b = load_profile_registry(tmp_path)

        fp_a = profile_fingerprint(registry_a[("rag_nexus_nsi_terminale_specialite", "v1")])
        fp_b = profile_fingerprint(registry_b[("rag_nexus_nsi_terminale_specialite", "v1")])
        assert fp_a == fp_b

    def test_editing_a_profile_file_in_place_changes_its_fingerprint(
        self, tmp_path: Path
    ) -> None:
        """Documente explicitement la limite : le registre n'empêche pas
        l'édition d'un fichier YAML déjà référencé (aucun verrou de
        fichier, aucune détection au chargement seul) — mais l'empreinte
        change, ce qui rend la dérive détectable a posteriori par un futur
        appelant comparant deux résultats persistés (cf. ADR-0028)."""
        path = _write_profile(tmp_path, "nsi.yml", title="Titre initial")
        registry_before = load_profile_registry(tmp_path)
        fp_before = profile_fingerprint(
            registry_before[("rag_nexus_nsi_terminale_specialite", "v1")]
        )

        path.write_text(
            yaml.safe_dump(_profile_payload(title="Titre modifié")), encoding="utf-8"
        )
        registry_after = load_profile_registry(tmp_path)
        fp_after = profile_fingerprint(
            registry_after[("rag_nexus_nsi_terminale_specialite", "v1")]
        )

        assert fp_before != fp_after
