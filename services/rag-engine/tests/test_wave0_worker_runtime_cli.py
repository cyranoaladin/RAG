"""Câblage publiable des CLIs Worker A et Worker B."""
from __future__ import annotations

from pathlib import Path

import pytest

from ingestor.ingestion_worker import cli as worker_a_cli
from ingestor.ingestion_worker import multilevel_runtime_authority, runtime_authority


def test_worker_a_parser_requires_governed_placement_authorities() -> None:
    parser = worker_a_cli._build_arg_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--profiles-dir", "/tmp/profiles",
                "--manifest-path", "/tmp/profiles.yml",
                "--artifact-store-dir", "/tmp/artifacts",
                "--owner", "worker-a",
                "--pii-evidence-path", "/tmp/pii.json",
                "--pii-evidence-sha256", "1" * 64,
                "--rights-evidence-path", "/tmp/rights.yml",
                "--rights-evidence-sha256", "2" * 64,
                "--corpus-manifest-sha256", "3" * 64,
                "--expected-role", "ingestion_control_app",
                "--once",
            ]
        )


def test_worker_a_parser_carries_every_resolver_input() -> None:
    parser = worker_a_cli._build_arg_parser()
    governed = [
        "--catalog-path", "/proof/catalog.json",
        "--catalog-sha256", "4" * 64,
        "--candidate-inventory-path", "/proof/inventory.json",
        "--candidate-inventory-sha256", "5" * 64,
        "--currentness-evidence-path", "/proof/currentness.yml",
        "--currentness-evidence-sha256", "6" * 64,
        "--mapping-path", "/proof/mapping.yml",
        "--mapping-sha256", "7" * 64,
        "--release-manifest-path", "/proof/wave0.release.json",
        "--release-manifest-sha256", "8" * 64,
        "--programme-index-path", "/proof/programme.yml",
        "--programme-index-sha256", "9" * 64,
        "--collection-config-path", "/proof/collections.yml",
        "--collection-config-sha256", "a" * 64,
    ]
    args = parser.parse_args(
        [
            "--profiles-dir", "/tmp/profiles",
            "--manifest-path", "/tmp/profiles.yml",
            "--artifact-store-dir", "/tmp/artifacts",
            "--owner", "worker-a",
            "--pii-evidence-path", "/tmp/pii.json",
            "--pii-evidence-sha256", "1" * 64,
            "--rights-evidence-path", "/tmp/rights.yml",
            "--rights-evidence-sha256", "2" * 64,
            "--corpus-manifest-sha256", "3" * 64,
            "--expected-role", "ingestion_control_app",
            *governed,
        ]
    )

    assert args.catalog_path == Path("/proof/catalog.json")
    assert args.release_manifest_sha256 == "8" * 64
    assert args.collection_config_sha256 == "a" * 64


def test_publication_resume_cli_is_importable_and_once_is_supported() -> None:
    from ingestor.ingestion_worker import publication_resume_cli

    parser = publication_resume_cli._build_arg_parser()
    assert any(action.dest == "once" for action in parser._actions)


def test_runtime_authority_rejects_pii_policy_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # La propriété éprouvée ici est la dérive de politique PII, pas le runtime :
    # le verrou pypdf du démarrage (une seule autorité, `CANONICAL_PYPDF_VERSION`)
    # est satisfait explicitement pour que l'épreuve ne dépende pas de la
    # version installée dans le venv qui l'exécute.
    import nexus_pdf_page_policy as page_policy
    import pypdf

    monkeypatch.setattr(pypdf, "__version__", page_policy.CANONICAL_PYPDF_VERSION)
    sha = "a" * 64
    inputs = runtime_authority.RuntimeAuthorityInputs(
        catalog_path=tmp_path / "catalog.json",
        catalog_sha256=sha,
        candidate_inventory_path=tmp_path / "inventory.json",
        candidate_inventory_sha256=sha,
        currentness_evidence_path=tmp_path / "currentness.yml",
        currentness_evidence_sha256=sha,
        mapping_path=tmp_path / "mapping.yml",
        mapping_sha256=sha,
        release_manifest_path=tmp_path / "release.json",
        release_manifest_sha256=sha,
        programme_index_path=tmp_path / "programme.yml",
        programme_index_sha256=sha,
        collection_config_path=tmp_path / "collections.yml",
        collection_config_sha256=sha,
        pii_evidence_path=tmp_path / "pii.json",
        pii_evidence_sha256=sha,
        rights_evidence_path=tmp_path / "rights.yml",
        rights_evidence_sha256=sha,
        corpus_manifest_sha256=sha,
    )
    resolver = type(
        "Resolver",
        (),
        {
            "release_profile_manifest_digest": sha,
            "release_pii_evidence_sha256": sha,
            "release_pii_policy_sha256": "1" * 64,
            "release_rights_registry_sha256": sha,
        },
    )()
    pii = type(
        "PII",
        (),
        {"evidence_sha256": sha, "policy_sha256": "2" * 64},
    )()
    rights = type("Rights", (), {"registry_sha256": sha})()
    monkeypatch.setattr(runtime_authority, "require_file_digest", lambda *_a, **_k: sha)
    monkeypatch.setattr(runtime_authority, "load_collection_config", lambda _path: {})
    monkeypatch.setattr(
        runtime_authority.VerifiedPedagogicalPlacementResolver,
        "load",
        classmethod(lambda _cls, **_kwargs: resolver),
    )
    monkeypatch.setattr(
        runtime_authority.VerifiedPIIEvidenceRegistry,
        "load",
        classmethod(lambda _cls, *_args, **_kwargs: pii),
    )
    monkeypatch.setattr(
        runtime_authority.VerifiedRightsEvidenceRegistry,
        "load",
        classmethod(lambda _cls, *_args, **_kwargs: rights),
    )

    with pytest.raises(
        runtime_authority.RuntimeAuthorityStartupError,
        match="PII policy digest differs",
    ):
        runtime_authority.load_governed_runtime_authorities(
            inputs,
            profile_registry={},
            profile_manifest_digest=sha,
        )


def test_multilevel_runtime_authority_has_every_digest_bound_input() -> None:
    fields = set(multilevel_runtime_authority.MultilevelRuntimeAuthorityInputs.__dataclass_fields__)

    assert fields == {
        "candidate_inventory_path",
        "candidate_inventory_sha256",
        "currentness_evidence_path",
        "currentness_evidence_sha256",
        "levels_mapping_path",
        "levels_mapping_sha256",
        "subjects_mapping_path",
        "subjects_mapping_sha256",
        "document_types_mapping_path",
        "document_types_mapping_sha256",
        "release_manifest_path",
        "release_manifest_sha256",
        "programme_registry_path",
        "programme_registry_sha256",
        "profile_manifest_path",
        "profile_manifest_sha256",
        "collection_config_path",
        "collection_config_sha256",
        "pii_evidence_path",
        "pii_evidence_sha256",
        "rights_evidence_path",
        "rights_evidence_sha256",
        "corpus_manifest_sha256",
        "repository_root",
        # ADR-0047 : autorité de revue PII, injectée et optionnelle. Chaque
        # chemin garde son empreinte ; l'allowlist de reviewers n'est pas un
        # fichier et n'en a donc pas.
        "pii_decision_set_path",
        "pii_decision_set_sha256",
        "pii_review_receipt_path",
        "pii_review_receipt_sha256",
        "review_trust_anchor_path",
        "review_trust_anchor_sha256",
        "pii_review_reviewers",
    }

    # L'invariant que la liste ci-dessus servait à protéger, énoncé
    # directement : aucun chemin d'entrée sans l'empreinte qui le lie.
    unbound = {
        field for field in fields
        if field.endswith("_path") and f"{field[:-5]}_sha256" not in fields
    }
    assert unbound == set()


def test_multilevel_runtime_authority_module_never_uses_pilot_sha_allowlist() -> None:
    source = Path(multilevel_runtime_authority.__file__).read_text(encoding="utf-8")

    assert "49ccdca4" not in source
    assert "c8662b03" not in source
    assert "VerifiedPedagogicalPlacementResolver.load" not in source
    assert "MultilevelVerifiedPedagogicalPlacementResolver.from_authorities" in source
