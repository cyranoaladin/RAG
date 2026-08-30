"""Contrat exact du bundle de release des profils production 2026-2027."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "services"
    / "rag-pedago"
    / "scripts"
    / "build_production_profile_release.py"
)
RELEASE_ROOT = (
    ROOT
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "profile_gate"
)
AGGREGATE = RELEASE_ROOT / "production-profile-gate.release.json"
BINDINGS = RELEASE_ROOT / "authority_bindings.json"
REGISTRY = RELEASE_ROOT.parent / "release-registry.json"
FINAL_MATRIX = ROOT / "docs/reports/final_production_profile_matrix_20260825.json"
PROFILE_MANIFEST = ROOT / "services/rag-engine/configs/ingestion_manifest.yml"
FINAL_PRODUCTION_SET = (
    ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
)
ACCEPTED_PLACEMENTS = (
    ROOT / "docs/reports/production_profile_accepted_placements_20260825.json"
)
VERIFIED_PROFILES = (
    ROOT / "docs/reports/verified_production_profiles_20260825.json"
)

FINAL_SET_SHA256 = "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
PROFILE_MANIFEST_FINGERPRINT = (
    "57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c"
)


class Builder(Protocol):
    CANONICAL_EMBEDDING_MODEL: str
    CANONICAL_EMBEDDING_REVISION: str

    def canonical_json_bytes(self, value: object) -> bytes: ...

    def validate_pdf_mirror(
        self, *, pdf_root: Path, content_sha256: list[str]
    ) -> dict[str, VerifiedPdf]: ...

    def validate_authority_bindings(
        self,
        *,
        repository_root: Path,
        bindings: dict[str, Any],
        aggregate: dict[str, Any],
    ) -> None: ...

    def stable_release_order(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def require_canonical_token_counter(self, token_counter: object) -> None: ...

    def resolve_currentness_network_audit(
        self,
        records: list[dict[str, Any]],
        *,
        verify_official_downloads: bool,
        audit_path: Path,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...


class VerifiedPdf(Protocol):
    path: Path
    content: bytes


def _module() -> Builder:
    spec = importlib.util.spec_from_file_location(
        "build_production_profile_release", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(Builder, module)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _final_set() -> set[str]:
    return {
        content
        for row in _load(FINAL_MATRIX)
        for content in row["content_sha256"]
    }


def _set_digest(values: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()


def test_final_input_is_exactly_the_frozen_twenty_six() -> None:
    final_set = _final_set()
    assert len(final_set) == 26
    assert _set_digest(final_set) == FINAL_SET_SHA256


def test_registered_release_is_the_only_active_release_and_exact() -> None:
    registry = _load(REGISTRY)
    assert registry["registry_version"] == "1"
    assert registry["school_year"] == "2026-2027"
    assert len(registry["releases"]) == 1
    entry = registry["releases"][0]
    assert entry["release_id"] == "production-profile-gate-2026-2027-v1"
    assert entry["release_kind"] == "MULTILEVEL_AGGREGATE_RELEASE_V1"
    assert entry["manifest_path"] == (
        "profile_gate/production-profile-gate.release.json"
    )
    assert len(entry["collections"]) == 18
    assert entry["expected_manifest_sha256"] == _sha256(AGGREGATE)


def test_aggregate_covers_exactly_26_contents_and_18_profiles() -> None:
    aggregate = _load(AGGREGATE)
    assert aggregate["release_kind"] == "MULTILEVEL_AGGREGATE_RELEASE_V1"
    assert aggregate["release_id"] == "production-profile-gate-2026-2027-v1"
    assert aggregate["expected_counts"]["artifacts"] == 26
    assert len(aggregate["subjects"]) == 18
    assert aggregate["authorities"]["profile_manifest_sha256"] == (
        PROFILE_MANIFEST_FINGERPRINT
    )

    contents: set[str] = set()
    collections: set[str] = set()
    for subject in aggregate["subjects"]:
        subject_path = RELEASE_ROOT / subject["path"]
        assert subject["sha256"] == _sha256(subject_path)
        document = _load(subject_path)
        collections.add(document["collection"])
        for artifact in document["artifacts"]:
            assert artifact["content_sha256"] not in contents
            contents.add(artifact["content_sha256"])
            assert artifact["chunks"]
            assert {
                page
                for chunk in artifact["chunks"]
                for page in range(chunk["page_start"], chunk["page_end"] + 1)
            } == set(range(1, artifact["page_count"] + 1))
    assert contents == _final_set()
    assert len(collections) == 18


def test_release_scope_inputs_cover_the_exact_final_set_and_profiles() -> None:
    final_contents = tuple(FINAL_PRODUCTION_SET.read_text().splitlines())
    placements = _load(ACCEPTED_PLACEMENTS)
    verified = _load(VERIFIED_PROFILES)
    matrix = _load(FINAL_MATRIX)

    assert len(final_contents) == len(set(final_contents)) == 26
    assert list(final_contents) == sorted(final_contents)
    assert _set_digest(set(final_contents)) == FINAL_SET_SHA256
    assert len(placements) == 26
    assert {row["content_sha256"] for row in placements} == set(final_contents)
    assert {row["release_id"] for row in placements} == {
        "production-profile-gate-2026-2027-v1"
    }
    assert verified["profile_manifest_digest"] == PROFILE_MANIFEST_FINGERPRINT
    assert len(verified["profiles"]) == 18
    assert len({row["profile_id"] for row in verified["profiles"]}) == 18
    assert all(row["source_path"].endswith(".yml") for row in verified["profiles"])
    assert {row["partition_kind"] for row in matrix} == {
        "EXACT_VERSIONED_RELEASE_PROFILE"
    }


def test_every_authority_is_named_path_bound_and_digest_checked() -> None:
    builder = _module()
    bindings = _load(BINDINGS)
    aggregate = _load(AGGREGATE)
    builder.validate_authority_bindings(
        repository_root=ROOT,
        bindings=bindings,
        aggregate=aggregate,
    )
    assert bindings["profile_manifest_fingerprint"] == (
        PROFILE_MANIFEST_FINGERPRINT
    )
    assert bindings["profile_manifest_file_sha256"] == _sha256(PROFILE_MANIFEST)
    assert set(bindings["bindings"]) == set(aggregate["authorities"])


def test_any_authority_binding_mutation_is_refused() -> None:
    builder = _module()
    bindings = _load(BINDINGS)
    aggregate = _load(AGGREGATE)
    for name in sorted(bindings["bindings"]):
        mutated = copy.deepcopy(bindings)
        mutated["bindings"][name]["file_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="digest"):
            builder.validate_authority_bindings(
                repository_root=ROOT,
                bindings=mutated,
                aggregate=aggregate,
            )


def test_pdf_mirror_refuses_missing_and_digest_drift(tmp_path: Path) -> None:
    builder = _module()
    content = "a" * 64
    with pytest.raises(ValueError, match="missing"):
        builder.validate_pdf_mirror(pdf_root=tmp_path, content_sha256=[content])
    (tmp_path / f"{content}.pdf").write_bytes(b"not the declared content")
    with pytest.raises(ValueError, match="digest"):
        builder.validate_pdf_mirror(pdf_root=tmp_path, content_sha256=[content])


def test_pdf_mirror_returns_an_immutable_verified_snapshot(tmp_path: Path) -> None:
    builder = _module()
    original = b"verified PDF bytes"
    content_sha256 = hashlib.sha256(original).hexdigest()
    path = tmp_path / f"{content_sha256}.pdf"
    path.write_bytes(original)

    verified = builder.validate_pdf_mirror(
        pdf_root=tmp_path,
        content_sha256=[content_sha256],
    )[content_sha256]
    path.write_bytes(b"attacker replaced path after verification")

    assert verified.path == path.resolve()
    assert verified.content == original
    assert hashlib.sha256(verified.content).hexdigest() == content_sha256


def test_offline_release_replay_consumes_the_sealed_currentness_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = _module()
    network_calls: list[list[dict[str, Any]]] = []

    def unexpected_network(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        network_calls.append(records)
        raise AssertionError("offline replay must not call the network verifier")

    monkeypatch.setattr(builder, "_verify_official_downloads", unexpected_network)
    content_sha256 = "a" * 64
    record = {
        "content_sha256": content_sha256,
        "source_url": "https://eduscol.education.gouv.fr/listing",
        "current_download_url": "https://eduscol.education.gouv.fr/document.pdf",
    }
    artifact = {
        "content_sha256": content_sha256,
        "current_source_listing_url": record["source_url"],
        "current_download_url": record["current_download_url"],
        "downloaded_sha256": content_sha256,
        "byte_identity": True,
    }
    audit = {
        "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
        "verified_at": "2026-08-25T00:00:00Z",
        "network_mode": "READ_ONLY",
        "write_operations": 0,
        "counts": {"verified": 1, "digest_mismatch": 0},
        "artifacts": [artifact],
    }
    audit_path = tmp_path / "currentness_network_audit.json"
    audit_path.write_bytes(builder.canonical_json_bytes(audit))

    network_audit, rows = builder.resolve_currentness_network_audit(
        [record],
        verify_official_downloads=False,
        audit_path=audit_path,
    )

    assert network_audit == audit
    assert rows == [artifact]
    assert network_calls == []


def test_offline_release_replay_rejects_a_drifted_currentness_audit(
    tmp_path: Path,
) -> None:
    builder = _module()
    content_sha256 = "a" * 64
    record = {
        "content_sha256": content_sha256,
        "source_url": "https://eduscol.education.gouv.fr/listing",
        "current_download_url": "https://eduscol.education.gouv.fr/document.pdf",
    }
    audit = {
        "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
        "verified_at": "2026-08-25T00:00:00Z",
        "network_mode": "READ_ONLY",
        "write_operations": 0,
        "counts": {"verified": 1, "digest_mismatch": 0},
        "artifacts": [
            {
                "content_sha256": content_sha256,
                "current_source_listing_url": record["source_url"],
                "current_download_url": record["current_download_url"],
                "downloaded_sha256": "b" * 64,
                "byte_identity": True,
            }
        ],
    }
    audit_path = tmp_path / "currentness_network_audit.json"
    audit_path.write_bytes(builder.canonical_json_bytes(audit))

    with pytest.raises(ValueError, match="sealed currentness audit differs"):
        builder.resolve_currentness_network_audit(
            [record],
            verify_official_downloads=False,
            audit_path=audit_path,
        )


def test_release_order_is_stable_and_duplicate_content_is_refused() -> None:
    builder = _module()
    rows = [
        {"collection": "z", "content_sha256": "b" * 64},
        {"collection": "a", "content_sha256": "c" * 64},
        {"collection": "a", "content_sha256": "a" * 64},
    ]
    assert builder.stable_release_order(rows) == [rows[2], rows[1], rows[0]]
    with pytest.raises(ValueError, match="duplicate"):
        builder.stable_release_order([rows[0], copy.deepcopy(rows[0])])


def test_noncanonical_e5_counter_is_refused() -> None:
    builder = _module()
    impostor = type(
        "Counter",
        (),
        {
            "model_id": builder.CANONICAL_EMBEDDING_MODEL,
            "model_revision": "mutable-main",
            "max_sequence_length": 512,
            "passage_token_count": lambda _self, _text: 1,
        },
    )()
    with pytest.raises(ValueError, match="revision"):
        builder.require_canonical_token_counter(impostor)


def test_preflight_proves_real_e5_bounds_and_no_empty_page() -> None:
    preflight_path = Path(
        _load(BINDINGS)["bindings"]["preflight_evidence_sha256"]["path"]
    )
    preflight = _load(ROOT / preflight_path)
    assert preflight["model_id"] == "intfloat/multilingual-e5-large"
    assert preflight["model_revision"] == (
        "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
    )
    assert preflight["counts"]["artifacts"] == 26
    assert preflight["counts"]["empty_pages"] == 0
    assert preflight["counts"]["empty_chunks"] == 0
    assert preflight["counts"]["oversized_chunks"] == 0
    assert max(
        chunk["token_count"]
        for artifact in preflight["artifacts"]
        for chunk in artifact["chunks"]
    ) <= 384


# --- LOT 1c : l'inventaire de modèle doit décrire exactement l'artefact ---------


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def _minimal_snapshot(root: Path) -> Path:
    """Artefact e5 minimal : des fichiers racine et un sous-répertoire de pooling."""
    _write(root / "model.safetensors", b"poids")
    _write(root / "config.json", '{"hidden_size": 1024}')
    _write(root / "modules.json", '[{"idx": 1, "path": "1_Pooling"}]')
    _write(root / "1_Pooling" / "config.json", '{"pooling_mode_mean_tokens": true}')
    return root


def _inventory_paths(inventory: bytes) -> list[str]:
    return [line.split("  ", 1)[1] for line in inventory.decode("utf-8").splitlines()]


MANIFEST = {"model_id": "intfloat/multilingual-e5-large", "canonical_dim": 1024}


def test_model_inventory_covers_files_in_subdirectories(tmp_path: Path) -> None:
    """Le défaut de production : `1_Pooling/config.json` était omis de l'inventaire.

    Ce fichier fixe le mode de pooling, donc l'espace vectoriel. Un inventaire qui
    l'omet scelle un artefact dont le sens des vecteurs n'est pas attesté — et le
    vérificateur d'exécution, qui exige une couverture exacte, refuse alors tout
    artefact réel.
    """
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")

    _manifest, inventory = module._model_inventory(
        snapshot=snapshot, manifest=MANIFEST
    )

    assert "1_Pooling/config.json" in _inventory_paths(inventory)


def test_model_inventory_covers_the_snapshot_exactly(tmp_path: Path) -> None:
    """Couverture exacte : ni omission, ni entrée sans fichier correspondant."""
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")

    _manifest, inventory = module._model_inventory(
        snapshot=snapshot, manifest=MANIFEST
    )

    on_disk = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if path.is_file()
    }
    assert set(_inventory_paths(inventory)) == on_disk | {"manifest.json"}


def test_model_inventory_digests_are_those_of_the_named_files(tmp_path: Path) -> None:
    """Le chemin listé et l'empreinte listée doivent désigner le même fichier."""
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")

    _manifest, inventory = module._model_inventory(
        snapshot=snapshot, manifest=MANIFEST
    )

    for line in inventory.decode("utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        if relative == "manifest.json":
            continue
        assert digest == _sha256(snapshot / relative), relative


def test_model_inventory_is_deterministic(tmp_path: Path) -> None:
    """Deux exécutions sur le même artefact rendent le même octet."""
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")

    first = module._model_inventory(snapshot=snapshot, manifest=MANIFEST)[1]
    second = module._model_inventory(snapshot=snapshot, manifest=MANIFEST)[1]

    assert first == second


def test_model_inventory_refuses_a_snapshot_already_carrying_its_inventory(
    tmp_path: Path,
) -> None:
    """`manifest.json` et `SHA256SUMS` sont des PRODUITS, pas des entrées.

    Les laisser passer produit une ligne `manifest.json` en double et une entrée
    `SHA256SUMS` qui ne peut jamais s'auto-décrire : un inventaire que le
    vérificateur d'exécution refusera toujours, sans que rien ne l'ait signalé
    au moment de la production.
    """
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")
    _write(snapshot / "SHA256SUMS", "ancien\n")

    with pytest.raises(ValueError, match="SHA256SUMS"):
        module._model_inventory(snapshot=snapshot, manifest=MANIFEST)


def test_model_inventory_refuses_a_snapshot_carrying_a_manifest(
    tmp_path: Path,
) -> None:
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")
    _write(snapshot / "manifest.json", "{}")

    with pytest.raises(ValueError, match="manifest.json"):
        module._model_inventory(snapshot=snapshot, manifest=MANIFEST)


def test_model_inventory_refuses_a_symlink(tmp_path: Path) -> None:
    """Le vérificateur d'exécution refuse tout lien symbolique sous la racine.

    Un inventaire qui en accepte un produit un artefact que rien ne pourra
    vérifier. Le refus doit intervenir à la production, pas au démarrage.
    """
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")
    (snapshot / "alias.json").symlink_to(snapshot / "config.json")

    with pytest.raises(ValueError, match="symlink"):
        module._model_inventory(snapshot=snapshot, manifest=MANIFEST)


def test_model_inventory_still_requires_weights(tmp_path: Path) -> None:
    """Garde préexistante : elle ne doit pas être perdue par la correction."""
    module = cast(Any, _module())
    snapshot = tmp_path / "e5"
    _write(snapshot / "config.json", "{}")
    _write(snapshot / "1_Pooling" / "config.json", "{}")

    with pytest.raises(ValueError, match="weights"):
        module._model_inventory(snapshot=snapshot, manifest=MANIFEST)
