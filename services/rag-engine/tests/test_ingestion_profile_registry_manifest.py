"""Le registre des profils reconnaît un manifeste de profils par sa nature.

La release des onze lie son manifeste SOUS le répertoire des profils
(`authority_bindings.profile_manifest_sha256`). Le registre ne doit ni le
valider « comme profil » (échec de collecte de toute la suite), ni l'ignorer en
silence : il est reconnu (`manifest_version` + `profiles`, sans `scope`) et
laissé au vérificateur de manifeste. Un fichier qui n'est ni l'un ni l'autre
reste un refus.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ingestor.ingestion_profiles.registry import ProfileRegistryLoadError, load_profile_registry

ENGINE_ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = ENGINE_ROOT / "configs" / "ingestion_profiles"
V2_DIR = PROFILES_DIR / "v2_livraison_319"


def test_the_sealed_manifest_lives_beside_the_profiles_and_is_not_a_profile() -> None:
    manifest = PROFILES_DIR / "ingestion_manifest_v2_livraison_319.yml"
    document = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert document["manifest_version"] == "1" and len(document["profiles"]) == 11
    registry = load_profile_registry(PROFILES_DIR)
    assert all(collection for collection, _version in registry)
    assert not any("manifest" in str(key) for key in registry)


def test_the_eleven_v2_profiles_load_as_a_registry() -> None:
    registry = load_profile_registry(V2_DIR)
    assert len(registry) == 11
    assert {collection for collection, _ in registry} == {
        path.stem for path in V2_DIR.glob("*.yml")
    }


def test_a_document_that_is_neither_a_profile_nor_a_manifest_is_refused(tmp_path: Path) -> None:
    (tmp_path / "stray.yml").write_text("manifest_version: '1'\nscope: {}\n", encoding="utf-8")
    with pytest.raises(ProfileRegistryLoadError, match="stray.yml"):
        load_profile_registry(tmp_path)
