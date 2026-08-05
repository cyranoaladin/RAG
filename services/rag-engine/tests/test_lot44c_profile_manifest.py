"""LOT44c : manifest de profils de production — vérification stricte.

Périmètre strict : tests unitaires purs (aucun réseau, aucun PostgreSQL).
Aucun profil pédagogique/métier n'est fabriqué : les profils utilisés ici
sont des fixtures de test génériques, jamais présentés comme réels.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from ingestor.ingestion_profiles.manifest import (
    SUPPORTED_MANIFEST_VERSION,
    ProfileManifestError,
    manifest_fingerprint,
    verify_profile_manifest,
)
from ingestor.ingestion_profiles.registry import load_profile_registry, profile_fingerprint
from ingestor.ingestion_profiles.startup_gate import (
    StartupGateResult,
    enforce_production_manifest_gate,
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
        "title": "Profil de test",
        "owner": "equipe-test",
        "expected_topics": ["sujet"],
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


def _write_profile(directory: Path, filename: str, **overrides: object) -> None:
    (directory / filename).write_text(
        yaml.safe_dump(_profile_payload(**overrides)), encoding="utf-8"
    )


def _manifest_data(
    entries: list[dict[str, str]],
    *,
    manifest_version: str = "1",
    provenance: str = "test-governance-export",
    generated_at: str = "2026-08-04T00:00:00Z",
) -> dict[str, object]:
    return {
        "manifest_version": manifest_version,
        "provenance": provenance,
        "generated_at": generated_at,
        "profiles": entries,
    }


def _write_manifest(directory: Path, entries: list[dict[str, str]], **kwargs: object) -> Path:
    path = directory / "manifest.yml"
    path.write_text(yaml.safe_dump(_manifest_data(entries, **kwargs)), encoding="utf-8")
    return path


def _entry(
    collection: str = "rag_nexus_nsi_terminale_specialite",
    profile_version: str = "v1",
    *,
    fingerprint: str | None = None,
    approved_by: str | None = "test-authority",
    approved_at: str | None = "2026-08-05T00:00:00Z",
    **profile_overrides: object,
) -> dict[str, str]:
    """Entrée de manifest correcte par défaut : empreinte calculée à partir
    du même contenu que ``_profile_payload`` (via ``_write_profile``), pour
    ne jamais produire un faux positif de dérive dans les tests positifs.
    ``**profile_overrides`` doit reproduire exactement les surcharges
    passées à ``_write_profile`` pour que l'empreinte calculée corresponde
    réellement au fichier écrit sur disque.

    ``approved_by``/``approved_at`` (LOT44f, couche d'autorité minimale,
    ADR-0031) : présents par défaut pour ne pas polluer chaque test
    préexistant qui ne teste pas spécifiquement l'autorité ; passer
    ``None`` explicitement pour construire une entrée sans l'un ou l'autre
    (utilisé par les tests dédiés à cette couche)."""
    from nexus_contracts.ingestion import CollectionProfile

    computed = fingerprint
    if computed is None:
        profile = CollectionProfile.model_validate(
            _profile_payload(profile_version=profile_version, **profile_overrides)
        )
        computed = profile_fingerprint(profile)
    entry: dict[str, str] = {
        "collection": collection,
        "profile_version": profile_version,
        "fingerprint": computed,
    }
    if approved_by is not None:
        entry["approved_by"] = approved_by
    if approved_at is not None:
        entry["approved_at"] = approved_at
    return entry


class TestManifestAbsentOrMalformed:
    def test_missing_manifest_file_fails_explicitly(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        with pytest.raises(ProfileManifestError, match="not found"):
            verify_profile_manifest(registry, tmp_path / "manifest.yml")

    def test_empty_manifest_fails_explicitly(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [])
        with pytest.raises(ProfileManifestError, match="zero profiles"):
            verify_profile_manifest(registry, manifest_path)

    def test_invalid_yaml_manifest_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = tmp_path / "manifest.yml"
        manifest_path.write_text("profiles: [unterminated", encoding="utf-8")
        with pytest.raises(ProfileManifestError):
            verify_profile_manifest(registry, manifest_path)

    def test_non_mapping_manifest_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = tmp_path / "manifest.yml"
        manifest_path.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")
        with pytest.raises(ProfileManifestError):
            verify_profile_manifest(registry, manifest_path)

    def test_missing_manifest_version_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = tmp_path / "manifest.yml"
        manifest_path.write_text(
            yaml.safe_dump({"provenance": "x", "generated_at": "x", "profiles": [_entry()]}),
            encoding="utf-8",
        )
        with pytest.raises(ProfileManifestError, match="manifest_version"):
            verify_profile_manifest(registry, manifest_path)

    def test_unsupported_manifest_version_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = _write_manifest(tmp_path, [_entry()], manifest_version="99")
        with pytest.raises(ProfileManifestError, match="manifest_version"):
            verify_profile_manifest(registry, manifest_path)

    def test_missing_provenance_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = tmp_path / "manifest.yml"
        manifest_path.write_text(
            yaml.safe_dump(
                {"manifest_version": "1", "generated_at": "x", "profiles": [_entry()]}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ProfileManifestError, match="provenance"):
            verify_profile_manifest(registry, manifest_path)

    def test_missing_generated_at_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = tmp_path / "manifest.yml"
        manifest_path.write_text(
            yaml.safe_dump(
                {"manifest_version": "1", "provenance": "x", "profiles": [_entry()]}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ProfileManifestError, match="generated_at"):
            verify_profile_manifest(registry, manifest_path)

    def test_entry_missing_collection_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = _write_manifest(
            tmp_path, [{"profile_version": "v1", "fingerprint": "a" * 64}]
        )
        with pytest.raises(ProfileManifestError, match="collection"):
            verify_profile_manifest(registry, manifest_path)

    def test_entry_missing_profile_version_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = _write_manifest(
            tmp_path,
            [{"collection": "rag_nexus_nsi_terminale_specialite", "fingerprint": "a" * 64}],
        )
        with pytest.raises(ProfileManifestError, match="profile_version"):
            verify_profile_manifest(registry, manifest_path)

    def test_entry_missing_fingerprint_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = _write_manifest(
            tmp_path,
            [{"collection": "rag_nexus_nsi_terminale_specialite", "profile_version": "v1"}],
        )
        with pytest.raises(ProfileManifestError, match="fingerprint"):
            verify_profile_manifest(registry, manifest_path)

    def test_entry_malformed_fingerprint_fails_explicitly(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = _write_manifest(
            tmp_path,
            [
                {
                    "collection": "rag_nexus_nsi_terminale_specialite",
                    "profile_version": "v1",
                    "fingerprint": "not-a-sha256-hex-digest",
                }
            ],
        )
        with pytest.raises(ProfileManifestError, match="fingerprint"):
            verify_profile_manifest(registry, manifest_path)


class TestManifestAuthority:
    """LOT44f, couche d'autorité minimale (ADR-0031) : ``approved_by``/
    ``approved_at`` sont des conditions d'acceptation, au même titre que
    ``fingerprint`` — jamais une métadonnée optionnelle. Ne teste PAS LOT41A/
    LOT42 (aucune implémentation de ces lots n'existe dans ce dépôt) : teste
    seulement le gate minimal qui empêche toute entrée sans autorité nommée
    et datée d'être acceptée."""

    def test_entry_missing_approved_by_fails_explicitly(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry(approved_by=None)])
        with pytest.raises(ProfileManifestError, match="approved_by"):
            verify_profile_manifest(registry, manifest_path)

    def test_entry_blank_approved_by_fails_explicitly(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry(approved_by="   ")])
        with pytest.raises(ProfileManifestError, match="approved_by"):
            verify_profile_manifest(registry, manifest_path)

    def test_entry_missing_approved_at_fails_explicitly(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry(approved_at=None)])
        with pytest.raises(ProfileManifestError, match="approved_at"):
            verify_profile_manifest(registry, manifest_path)

    def test_entry_malformed_approved_at_fails_explicitly(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(
            tmp_path, [_entry(approved_at="not-an-iso-8601-timestamp")]
        )
        with pytest.raises(ProfileManifestError, match="approved_at"):
            verify_profile_manifest(registry, manifest_path)

    def test_valid_entry_exposes_authority_in_verification_result(
        self, tmp_path: Path
    ) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(
            tmp_path,
            [_entry(approved_by="abenrhouma", approved_at="2026-08-05T10:00:00Z")],
        )
        verification = verify_profile_manifest(registry, manifest_path)
        key = ("rag_nexus_nsi_terminale_specialite", "v1")
        assert key in verification.authorities
        assert verification.authorities[key].approved_by == "abenrhouma"
        assert verification.authorities[key].approved_at == "2026-08-05T10:00:00Z"

    def test_tampering_approval_fields_changes_manifest_fingerprint(
        self, tmp_path: Path
    ) -> None:
        """L'autorité fait partie du contenu figé du manifest : changer qui a
        approuvé (sans rien changer d'autre) doit changer l'empreinte du
        manifest — sinon l'autorité pourrait être falsifiée sans laisser de
        trace détectable."""
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_a = _write_manifest(tmp_path, [_entry(approved_by="authority-a")])
        verification_a = verify_profile_manifest(registry, manifest_a)

        (tmp_path / "manifest.yml").unlink()
        manifest_b = _write_manifest(tmp_path, [_entry(approved_by="authority-b")])
        verification_b = verify_profile_manifest(registry, manifest_b)

        assert verification_a.manifest_fingerprint != verification_b.manifest_fingerprint


class TestManifestAmbiguity:
    def test_duplicate_entry_in_manifest_is_ambiguous(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry(), _entry()])
        with pytest.raises(ProfileManifestError, match="more than once"):
            verify_profile_manifest(registry, manifest_path)


class TestManifestRegistryConsistency:
    def test_manifest_references_profile_missing_from_registry(self, tmp_path: Path) -> None:
        registry: dict = {}
        manifest_path = _write_manifest(tmp_path, [_entry()])
        with pytest.raises(ProfileManifestError, match="not present in the loaded registry"):
            verify_profile_manifest(registry, manifest_path)

    def test_registry_contains_profile_not_declared_in_manifest(self, tmp_path: Path) -> None:
        """Aucun profil surnuméraire toléré — une dérive de configuration
        (fichier ajouté sans mise à jour du manifest) doit échouer, jamais
        être silencieusement acceptée."""
        _write_profile(tmp_path, "a.yml", profile_version="v1")
        _write_profile(tmp_path, "b.yml", profile_version="v2")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry(profile_version="v1")])
        with pytest.raises(ProfileManifestError, match="not declared in the manifest"):
            verify_profile_manifest(registry, manifest_path)

    def test_exact_match_succeeds(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry()])
        result = verify_profile_manifest(registry, manifest_path)
        assert result.declared_count == 1
        assert len(result.manifest_fingerprint) == 64
        assert result.manifest_version == SUPPORTED_MANIFEST_VERSION
        assert result.provenance == "test-governance-export"
        assert result.generated_at == "2026-08-04T00:00:00Z"


class TestManifestFingerprintDrift:
    """L'empreinte d'un profil est vérifiée, pas seulement son identité —
    une modification silencieuse d'un profil déjà déclaré est détectée."""

    def test_fingerprint_mismatch_is_rejected(self, tmp_path: Path) -> None:
        _write_profile(tmp_path, "a.yml")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry(fingerprint="0" * 64)])
        with pytest.raises(ProfileManifestError, match="Fingerprint mismatch"):
            verify_profile_manifest(registry, manifest_path)

    def test_profile_edited_after_manifest_written_is_caught(self, tmp_path: Path) -> None:
        """Scénario réaliste : le manifest est écrit pour une version du
        profil, puis le fichier profil est modifié sans mise à jour du
        manifest — la dérive est détectée au prochain chargement.

        Répertoire de profils et manifest séparés (comme en usage réel) :
        le manifest n'est jamais lui-même globbé comme un profil."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "a.yml", title="Titre initial")
        registry_before = load_profile_registry(profiles_dir)
        manifest_path = _write_manifest(tmp_path, [_entry(title="Titre initial")])
        assert verify_profile_manifest(registry_before, manifest_path).declared_count == 1

        _write_profile(profiles_dir, "a.yml", title="Titre modifié après coup")
        registry_after = load_profile_registry(profiles_dir)
        with pytest.raises(ProfileManifestError, match="Fingerprint mismatch"):
            verify_profile_manifest(registry_after, manifest_path)


class TestManifestFingerprint:
    def test_fingerprint_is_deterministic(self) -> None:
        data = _manifest_data([_entry()])
        assert manifest_fingerprint(data) == manifest_fingerprint(data)

    def test_fingerprint_differs_for_different_content(self) -> None:
        data_a = _manifest_data([_entry()])
        data_b = _manifest_data([_entry(profile_version="v2", fingerprint="1" * 64)])
        assert manifest_fingerprint(data_a) != manifest_fingerprint(data_b)

    def test_fingerprint_independent_of_key_order(self) -> None:
        data_a = {"manifest_version": "1", "profiles": [], "provenance": "x", "generated_at": "y"}
        data_b = {"profiles": [], "generated_at": "y", "manifest_version": "1", "provenance": "x"}
        assert manifest_fingerprint(data_a) == manifest_fingerprint(data_b)


class TestNoDefaultNoFallback:
    def test_no_default_manifest_path_is_assumed_without_explicit_argument(self) -> None:
        """verify_profile_manifest exige un chemin de manifest explicite —
        aucun chemin par défaut, aucune convention implicite."""
        signature = inspect.signature(verify_profile_manifest)
        assert signature.parameters["manifest_path"].default is inspect.Parameter.empty

    def test_manifest_naming_an_older_version_does_not_match_a_newer_registry_version(
        self, tmp_path: Path
    ) -> None:
        """Preuve comportementale (pas une recherche de mot-clé) : si le
        manifest déclare v1 mais que seul v2 est chargé, la vérification
        échoue — aucune tolérance "la version la plus récente convient"."""
        _write_profile(tmp_path, "a.yml", profile_version="v2")
        registry = load_profile_registry(tmp_path)
        manifest_path = _write_manifest(tmp_path, [_entry(profile_version="v1")])
        with pytest.raises(ProfileManifestError):
            verify_profile_manifest(registry, manifest_path)


class TestStartupGate:
    """Gate de démarrage : combine chargement du registre et vérification
    du manifest en un seul appel bloquant, sans aucun paramètre de
    contournement."""

    def test_no_bypass_parameter_exists(self) -> None:
        signature = inspect.signature(enforce_production_manifest_gate)
        assert set(signature.parameters) == {"profiles_dir", "manifest_path"}

    def test_valid_manifest_and_profiles_pass_the_gate(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "a.yml")
        manifest_path = _write_manifest(tmp_path, [_entry()])
        result = enforce_production_manifest_gate(profiles_dir, manifest_path)
        assert isinstance(result, StartupGateResult)
        assert result.manifest.declared_count == 1

    def test_missing_manifest_blocks_startup(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "a.yml")
        with pytest.raises(ProfileManifestError, match="not found"):
            enforce_production_manifest_gate(profiles_dir, tmp_path / "manifest.yml")

    def test_missing_profile_blocks_startup(self, tmp_path: Path) -> None:
        """Répertoire de profils vide (aucun fichier) → registre vide → le
        manifest, qui ne peut jamais être vide, échoue nécessairement :
        aucun démarrage silencieux sans aucun profil."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        manifest_path = _write_manifest(tmp_path, [_entry()])
        with pytest.raises(ProfileManifestError):
            enforce_production_manifest_gate(profiles_dir, manifest_path)

    def test_fingerprint_drift_blocks_startup(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "a.yml")
        manifest_path = _write_manifest(tmp_path, [_entry(fingerprint="f" * 64)])
        with pytest.raises(ProfileManifestError, match="Fingerprint mismatch"):
            enforce_production_manifest_gate(profiles_dir, manifest_path)

    def test_unknown_version_blocks_startup(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "a.yml", profile_version="v1")
        manifest_path = _write_manifest(
            tmp_path, [_entry(profile_version="v2", fingerprint="a" * 64)]
        )
        with pytest.raises(ProfileManifestError):
            enforce_production_manifest_gate(profiles_dir, manifest_path)

    def test_structurally_invalid_profile_blocks_startup(self, tmp_path: Path) -> None:
        """Un profil structurellement invalide fait échouer le chargement
        du registre lui-même — propagé sans interception, jamais un
        registre partiel autorisé à démarrer."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "broken.yml").write_text(
            yaml.safe_dump({"profile_version": "v1"}), encoding="utf-8"
        )
        manifest_path = _write_manifest(tmp_path, [_entry()])
        with pytest.raises(Exception):  # noqa: B017 - ProfileRegistryLoadError, importé indirectement
            enforce_production_manifest_gate(profiles_dir, manifest_path)

    def test_startup_authorized_only_with_consistent_manifest(self, tmp_path: Path) -> None:
        """Démonstration positive/négative appariée : le même répertoire de
        profils échoue avec un manifest incohérent et réussit une fois le
        manifest corrigé — la gate ne renvoie un résultat que dans le
        second cas."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "a.yml")
        inconsistent_manifest = _write_manifest(
            tmp_path, [_entry(profile_version="v2", fingerprint="a" * 64)]
        )
        with pytest.raises(ProfileManifestError):
            enforce_production_manifest_gate(profiles_dir, inconsistent_manifest)

        consistent_manifest = _write_manifest(tmp_path, [_entry()])
        result = enforce_production_manifest_gate(profiles_dir, consistent_manifest)
        assert result.manifest.declared_count == 1


class TestStartupGateCliEntryPoint:
    """Point d'entrée CLI autonome (``python -m
    ingestor.ingestion_profiles.startup_gate <profiles_dir>
    <manifest_path>``) — invocable sans modifier aucun fichier LOT43,
    utilisable comme étape de pré-démarrage/healthcheck de déploiement."""

    def test_cli_exits_zero_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ingestor.ingestion_profiles.startup_gate import _main

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "a.yml")
        manifest_path = _write_manifest(tmp_path, [_entry()])

        monkeypatch.setattr(
            "sys.argv", ["startup_gate", str(profiles_dir), str(manifest_path)]
        )
        exit_code = _main()
        assert exit_code == 0
        assert "STARTUP_GATE_PASSED" in capsys.readouterr().out

    def test_cli_exits_nonzero_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ingestor.ingestion_profiles.startup_gate import _main

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        monkeypatch.setattr(
            "sys.argv", ["startup_gate", str(profiles_dir), str(tmp_path / "manifest.yml")]
        )
        exit_code = _main()
        assert exit_code == 1
        assert "STARTUP_GATE_FAILED" in capsys.readouterr().err

    def test_cli_exits_nonzero_on_wrong_argument_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ingestor.ingestion_profiles.startup_gate import _main

        monkeypatch.setattr("sys.argv", ["startup_gate", "only-one-arg"])
        assert _main() == 2
