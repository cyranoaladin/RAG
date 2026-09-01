"""Contrat exact du bundle de release des profils production 2026-2027."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

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


def test_model_inventory_ignore_ses_propres_produits(tmp_path: Path) -> None:
    """`manifest.json` et `SHA256SUMS` sont des PRODUITS : ils sont IGNORÉS.

    J'avais écrit ici l'exigence inverse — que l'outil REFUSE un instantané portant
    déjà sa sortie précédente. La version de `rag-pedago/release-chain-ingestion-319`,
    antérieure de quatre jours, les ignore. Son choix est meilleur : ignorer rend le
    producteur **idempotent**, la même entrée rendant le même inventaire que la sortie
    précédente y traîne ou non. Refuser attrapait une erreur d'opérateur au prix de
    l'idempotence.
    """
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")
    _manifest, attendu = module._model_inventory(snapshot=snapshot, manifest=MANIFEST)

    _write(snapshot / "SHA256SUMS", "sortie précédente\n")
    _write(snapshot / "manifest.json", "{}")
    _manifest2, obtenu = module._model_inventory(snapshot=snapshot, manifest=MANIFEST)

    assert obtenu == attendu, "la présence des produits change l'inventaire"


def test_model_inventory_suit_les_liens_symboliques(tmp_path: Path) -> None:
    """Les liens symboliques sont SUIVIS, et c'est requis.

    J'avais écrit ici l'exigence inverse. Le vérificateur d'exécution refuse les liens
    sous la racine de l'ARTEFACT MONTÉ, et il a raison ; mais le producteur reçoit un
    INSTANTANÉ DE CONSTRUCTION, qui n'est pas le même objet. Le cache hub HuggingFace,
    passé tel quel en `--embedding-snapshot`, n'est fait que de liens vers
    `../../blobs` : les exclure viderait l'inventaire.

    Deux objets, deux moments, deux exigences.
    """
    module = cast(Any, _module())
    snapshot = _minimal_snapshot(tmp_path / "e5")
    cible = tmp_path / "hors" / "poids.bin"
    _write(cible, b"contenu pointe")
    (snapshot / "alias.bin").symlink_to(cible)

    _manifest, inventaire = module._model_inventory(snapshot=snapshot, manifest=MANIFEST)

    chemins = _inventory_paths(inventaire)
    assert "alias.bin" in chemins, "le lien symbolique a été exclu de l'inventaire"


def test_model_inventory_still_requires_weights(tmp_path: Path) -> None:
    """Garde préexistante : elle ne doit pas être perdue par la correction."""
    module = cast(Any, _module())
    snapshot = tmp_path / "e5"
    _write(snapshot / "config.json", "{}")
    _write(snapshot / "1_Pooling" / "config.json", "{}")

    with pytest.raises(ValueError, match="weights"):
        module._model_inventory(snapshot=snapshot, manifest=MANIFEST)


# --- LOT 1.2 / Option A : un artefact global, N placements ------------------


V2_ARTIFACT_SHA = "a" * 64
V2_CHUNK_ID = "b" * 64
V2_CHUNK_SHA = "c" * 64
V2_PROFILE_DIGEST = "d" * 64
V2_COLLECTIONS = (
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
)


def _v2_authorities() -> dict[str, str]:
    names = (
        "corpus_manifest_sha256",
        "parent_sealed_catalog_sha256",
        "placement_catalog_sha256",
        "catalog_delta_sha256",
        "effective_catalog_authority_sha256",
        "candidate_inventory_sha256",
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "pii_policy_sha256",
        "pii_scanner_sha256",
        "rights_registry_sha256",
        "preflight_evidence_sha256",
        "programme_registry_sha256",
        "profile_manifest_sha256",
        "level_mapping_sha256",
        "subject_mapping_sha256",
        "document_type_mapping_sha256",
        "embedding_inventory_sha256",
        "reranker_inventory_sha256",
    )
    result = {name: hashlib.sha256(name.encode()).hexdigest() for name in names}
    result["profile_manifest_sha256"] = V2_PROFILE_DIGEST
    return result


def _v2_profile(collection: str, index: int) -> SimpleNamespace:
    niveau = "premiere" if index == 0 else "terminale"
    return SimpleNamespace(
        profile_version="2.0.0",
        scope=SimpleNamespace(
            audience=(SimpleNamespace(value="both"),),
            candidat=SimpleNamespace(value="both"),
            collection=collection,
            matiere="nsi",
            niveau=SimpleNamespace(value=niveau),
            programme_version="BOEN_special_1_2019-01-22",
            school_year="2026-2027",
            tenant=f"libre_{niveau}",
            visibility="internal",
            voie=SimpleNamespace(value="generale"),
        ),
    )


def _v2_placement_rows() -> list[dict[str, Any]]:
    common = {
        "content_sha256": V2_ARTIFACT_SHA,
        "physical_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/commun.pdf",
        "source_url": "https://eduscol.education.fr/commun",
        "current_download_url": "https://eduscol.education.fr/commun.pdf",
        "title": "Ressource commune Premiere et Terminale",
        "external_document_type": "ressource",
    }
    return [
        {
            **common,
            "collection": collection,
            "source_placement_id": f"source-placement-{index}",
            "external_scope": f"lycee/{'premiere' if index == 0 else 'terminale'}/nsi",
        }
        for index, collection in enumerate(V2_COLLECTIONS)
    ]


def _v2_preflight_artifact() -> dict[str, Any]:
    return {
        "content_sha256": V2_ARTIFACT_SHA,
        "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/commun.pdf",
        "page_count": 1,
        "ignored_empty_pages": [],
        "chunks": [
            {
                "chunk_index": 0,
                "chunk_id": V2_CHUNK_ID,
                "chunk_sha256": V2_CHUNK_SHA,
                "page_start": 1,
                "page_end": 1,
                "token_count": 7,
                "character_count": 42,
            }
        ],
    }


def _v2_pii_evidence(
    *,
    content_sha256: str = V2_ARTIFACT_SHA,
    ignored_empty_pages: list[int] | None = None,
) -> dict[str, Any]:
    """Preuve minimale portée par l'extraction PII faisant autorité."""
    return {
        "results": [
            {
                "content_sha256": content_sha256,
                "ignored_empty_pages": list(ignored_empty_pages or []),
            }
        ]
    }


def _pdf_with_physical_pages(*texts: str | None) -> bytes:
    """PDF réel : ``None`` est une page structurellement vide conservée."""
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
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(
            f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _v2_rows_for_pdf(content: bytes) -> tuple[str, list[dict[str, Any]]]:
    sha = hashlib.sha256(content).hexdigest()
    rows = _v2_placement_rows()
    for row in rows:
        row["content_sha256"] = sha
    return sha, rows


def _v2_token_counter(builder: Any) -> SimpleNamespace:
    return SimpleNamespace(
        model_id=builder.CANONICAL_EMBEDDING_MODEL,
        model_revision=builder.CANONICAL_EMBEDDING_REVISION,
        max_sequence_length=512,
        passage_token_count=lambda text: len(text.split()) + 2,
    )


def _v2_models(builder: Any) -> dict[str, Any]:
    return {
        "embedding": {
            "model_id": builder.CANONICAL_EMBEDDING_MODEL,
            "inventory_sha256": "1" * 64,
            "dimension": 1024,
        },
        "reranker": {
            "model_id": builder.CANONICAL_RERANKER_MODEL,
            "inventory_sha256": "2" * 64,
        },
    }


def _v2_topology_documents(
    builder: Any,
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[Path, bytes]:
    profiles = {
        collection: _v2_profile(collection, index)
        for index, collection in enumerate(V2_COLLECTIONS)
    }
    monkeypatch.setattr(builder, "profile_fingerprint", lambda _profile: "e" * 64)
    return builder._release_topology_documents(
        _v2_placement_rows(),
        profiles=profiles,
        profile_manifest_digest=V2_PROFILE_DIGEST,
        collection_config={
            collection: {"statut": "specialite"} for collection in V2_COLLECTIONS
        },
        preflight_by_sha={V2_ARTIFACT_SHA: _v2_preflight_artifact()},
        type_doc_mapping={"ressource": "ressource_officielle"},
        authorities=_v2_authorities(),
        models=_v2_models(builder),
        release_root=release_root,
        release_id="lot-1-2-option-a",
        school_year="2026-2027",
    )


def _decode_documents(documents: dict[Path, bytes]) -> dict[str, dict[str, Any]]:
    return {
        path.name: json.loads(raw.decode("utf-8"))
        for path, raw in documents.items()
    }


def test_v2_producer_groups_two_placements_into_one_global_artifact() -> None:
    builder = cast(Any, _module())

    grouped = builder._group_artifact_rows(_v2_placement_rows())

    assert list(grouped) == [V2_ARTIFACT_SHA]
    assert grouped[V2_ARTIFACT_SHA]["artifact_row"]["content_sha256"] == (
        V2_ARTIFACT_SHA
    )
    assert grouped[V2_ARTIFACT_SHA]["placement_rows"] == _v2_placement_rows()


@pytest.mark.parametrize(
    "field,drifted_value",
    [
        ("physical_path", "autre/commun.pdf"),
        ("title", "Titre divergent"),
        ("source_url", "https://eduscol.education.fr/autre"),
        ("current_download_url", "https://eduscol.education.fr/autre.pdf"),
        ("external_document_type", "annale"),
    ],
)
def test_v2_producer_refuses_divergent_intrinsic_facts(
    field: str,
    drifted_value: str,
) -> None:
    builder = cast(Any, _module())
    rows = _v2_placement_rows()
    rows[1][field] = drifted_value

    with pytest.raises(ValueError, match=rf"intrinsic.*{field}|{field}.*intrinsic"):
        builder._group_artifact_rows(rows)


def test_v2_producer_pii_scans_unique_contents_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    calls: list[str] = []

    def scan_once(content: bytes, **_kwargs: object) -> SimpleNamespace:
        calls.append(hashlib.sha256(content).hexdigest())
        return SimpleNamespace(
            sha256=V2_ARTIFACT_SHA,
            pages_scanned=1,
            characters_scanned=42,
            ignored_empty_pages=(),
            # Le double porte la mesure que le producteur lit desormais : un scan
            # sans correspondance. Sans ce champ, la preuve ne peut plus etre ecrite.
            pii_detected=False,
            matches=(),
            extraction_error=None,
        )

    monkeypatch.setattr(builder, "load_patterns_from_config", lambda _path: ())
    monkeypatch.setattr(builder, "scan_pdf_bytes", scan_once)
    pdf = builder.VerifiedPdf(tmp_path / "commun.pdf", b"pdf-factice")

    evidence = builder._pii_evidence(
        _v2_placement_rows(),
        pdfs={V2_ARTIFACT_SHA: pdf},
        inventory_sha256="f" * 64,
    )

    assert calls == [hashlib.sha256(b"pdf-factice").hexdigest()]
    assert evidence["required_pdf_path_count"] == 1
    assert evidence["summary"]["unique_contents_required"] == 1
    assert evidence["summary"]["unique_contents_scanned"] == 1
    assert evidence["summary"]["pii_scan_coverage"] == 1.0
    assert "placements" not in evidence["summary"]
    assert [row["content_sha256"] for row in evidence["results"]] == [
        V2_ARTIFACT_SHA
    ]
    assert evidence["results"][0]["ignored_empty_pages"] == []


def test_v2_producer_never_rewrites_a_positive_pii_scan_as_cleared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())

    def positive_scan(_content: bytes, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            sha256=V2_ARTIFACT_SHA,
            pages_scanned=1,
            characters_scanned=42,
            ignored_empty_pages=(),
            pii_detected=True,
            matches=(SimpleNamespace(pattern_id="email_address"),),
            extraction_error=None,
        )

    monkeypatch.setattr(builder, "load_patterns_from_config", lambda _path: ())
    monkeypatch.setattr(builder, "scan_pdf_bytes", positive_scan)
    pdf = builder.VerifiedPdf(tmp_path / "commun.pdf", b"pdf-factice")

    evidence = builder._pii_evidence(
        _v2_placement_rows(),
        pdfs={V2_ARTIFACT_SHA: pdf},
        inventory_sha256="f" * 64,
    )
    result = evidence["results"][0]

    assert result["pii_detected"] is True
    assert result["status"] != "CLEARED"


def test_v2_producer_preflight_chunks_unique_contents_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    calls: list[bytes] = []
    content = _pdf_with_physical_pages("Contenu physique unique")
    sha, rows = _v2_rows_for_pdf(content)
    pdf = builder.VerifiedPdf(tmp_path / f"{sha}.pdf", content)
    pii_evidence = builder._pii_evidence(
        rows,
        pdfs={sha: pdf},
        inventory_sha256="f" * 64,
    )

    def chunk_once(**kwargs: object) -> list[SimpleNamespace]:
        content = cast(bytes, kwargs["content"])
        calls.append(content)
        return [SimpleNamespace(text="un chunk", page_start=1, page_end=1)]

    monkeypatch.setattr(builder, "chunk_publication", chunk_once)
    counter = SimpleNamespace(
        model_id=builder.CANONICAL_EMBEDDING_MODEL,
        model_revision=builder.CANONICAL_EMBEDDING_REVISION,
        max_sequence_length=512,
        passage_token_count=lambda _text: 2,
    )
    evidence = builder._preflight(
        rows,
        pdfs={sha: pdf},
        token_counter=counter,
        pii_evidence=pii_evidence,
    )

    assert calls == [content]
    assert evidence["counts"]["unique_artifacts"] == 1
    assert "placements" not in evidence["counts"]
    assert len(evidence["artifacts"]) == 1
    assert evidence["artifacts"][0]["ignored_empty_pages"] == []


@pytest.mark.parametrize(
    ("physical_pages", "expected_ignored", "expected_covered"),
    [
        ((None, "Page physique deux"), [1], [2]),
        (("Page physique un", None, "Page physique trois"), [2], [1, 3]),
        (("Page physique un", None), [2], [1]),
        ((None, "Page deux", None, "Page quatre", None), [1, 3, 5], [2, 4]),
    ],
    ids=("initiale", "milieu", "finale", "multiples"),
)
def test_v2_preflight_derives_empty_pages_from_authoritative_pii_extraction(
    physical_pages: tuple[str | None, ...],
    expected_ignored: list[int],
    expected_covered: list[int],
    tmp_path: Path,
) -> None:
    builder = cast(Any, _module())
    content = _pdf_with_physical_pages(*physical_pages)
    sha, rows = _v2_rows_for_pdf(content)
    pdf = builder.VerifiedPdf(tmp_path / f"{sha}.pdf", content)

    pii_evidence = builder._pii_evidence(
        rows,
        pdfs={sha: pdf},
        inventory_sha256="f" * 64,
    )
    preflight = builder._preflight(
        rows,
        pdfs={sha: pdf},
        token_counter=_v2_token_counter(builder),
        pii_evidence=pii_evidence,
    )

    assert pii_evidence["results"][0]["ignored_empty_pages"] == expected_ignored
    artifact = preflight["artifacts"][0]
    assert artifact["ignored_empty_pages"] == expected_ignored
    assert sorted({chunk["page_start"] for chunk in artifact["chunks"]}) == (
        expected_covered
    )


def test_v2_preflight_refuses_a_nonempty_page_removed_from_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Face négative majeure : la nouvelle exception ne justifie pas un trou."""
    builder = cast(Any, _module())
    content = _pdf_with_physical_pages(
        "Page physique un",
        None,
        "Page physique trois non vide",
    )
    sha, rows = _v2_rows_for_pdf(content)
    pdf = builder.VerifiedPdf(tmp_path / f"{sha}.pdf", content)
    pii_evidence = builder._pii_evidence(
        rows,
        pdfs={sha: pdf},
        inventory_sha256="f" * 64,
    )
    monkeypatch.setattr(
        builder,
        "chunk_publication",
        lambda **_kwargs: [
            SimpleNamespace(text="Page physique un", page_start=1, page_end=1)
        ],
    )

    with pytest.raises(ValueError, match=r"partition|coverage|uncovered|page 3"):
        builder._preflight(
            rows,
            pdfs={sha: pdf},
            token_counter=_v2_token_counter(builder),
            pii_evidence=pii_evidence,
        )


def test_v2_preflight_refuses_an_ignored_page_that_a_chunk_covers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    content = _pdf_with_physical_pages("Page un", None, "Page trois")
    sha, rows = _v2_rows_for_pdf(content)
    pdf = builder.VerifiedPdf(tmp_path / f"{sha}.pdf", content)
    pii_evidence = builder._pii_evidence(
        rows,
        pdfs={sha: pdf},
        inventory_sha256="f" * 64,
    )
    monkeypatch.setattr(
        builder,
        "chunk_publication",
        lambda **_kwargs: [
            SimpleNamespace(text=f"Page {page}", page_start=page, page_end=page)
            for page in (1, 2, 3)
        ],
    )

    with pytest.raises(ValueError, match=r"overlap|disjoint|ignored|page 2"):
        builder._preflight(
            rows,
            pdfs={sha: pdf},
            token_counter=_v2_token_counter(builder),
            pii_evidence=pii_evidence,
        )


def test_v2_preflight_refuses_a_nonempty_page_declared_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une liste déclarative ne peut pas transformer du texte en page vide."""
    builder = cast(Any, _module())
    content = _pdf_with_physical_pages("Page un", "Page deux non vide")
    sha, rows = _v2_rows_for_pdf(content)
    pdf = builder.VerifiedPdf(tmp_path / f"{sha}.pdf", content)
    fabricated_pii_evidence = _v2_pii_evidence(
        content_sha256=sha,
        ignored_empty_pages=[2],
    )
    monkeypatch.setattr(
        builder,
        "chunk_publication",
        lambda **_kwargs: [
            SimpleNamespace(text="Page un", page_start=1, page_end=1)
        ],
    )

    with pytest.raises(
        ValueError,
        match=r"authoritative|extraction|nonempty|non.?vide|ignored",
    ):
        builder._preflight(
            rows,
            pdfs={sha: pdf},
            token_counter=_v2_token_counter(builder),
            pii_evidence=fabricated_pii_evidence,
        )


def test_v2_preflight_keeps_physical_citation_numbers_after_an_empty_page(
    tmp_path: Path,
) -> None:
    builder = cast(Any, _module())
    content = _pdf_with_physical_pages("Avant", None, "Apres la page vide")
    sha, rows = _v2_rows_for_pdf(content)
    pdf = builder.VerifiedPdf(tmp_path / f"{sha}.pdf", content)
    pii_evidence = builder._pii_evidence(
        rows,
        pdfs={sha: pdf},
        inventory_sha256="f" * 64,
    )

    preflight = builder._preflight(
        rows,
        pdfs={sha: pdf},
        token_counter=_v2_token_counter(builder),
        pii_evidence=pii_evidence,
    )

    artifact = preflight["artifacts"][0]
    assert artifact["ignored_empty_pages"] == [2]
    assert [(chunk["page_start"], chunk["page_end"]) for chunk in artifact["chunks"]] == [
        (1, 1),
        (3, 3),
    ]


def test_v2_producer_keeps_an_entirely_empty_pdf_nonservable(tmp_path: Path) -> None:
    builder = cast(Any, _module())
    content = _pdf_with_physical_pages(None, None)
    sha, rows = _v2_rows_for_pdf(content)
    pdf = builder.VerifiedPdf(tmp_path / f"{sha}.pdf", content)

    with pytest.raises(ValueError, match=r"EXTRACTION|EMPTY|no text"):
        builder._pii_evidence(
            rows,
            pdfs={sha: pdf},
            inventory_sha256="f" * 64,
        )


def test_v2_producer_keeps_an_ambiguous_image_page_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())

    def refused_scan(_content: bytes, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            sha256=V2_ARTIFACT_SHA,
            pages_scanned=0,
            characters_scanned=0,
            ignored_empty_pages=(),
            extraction_error="PAGE_IMAGE_NON_LISIBLE:pages 2",
        )

    monkeypatch.setattr(builder, "load_patterns_from_config", lambda _path: ())
    monkeypatch.setattr(builder, "scan_pdf_bytes", refused_scan)
    pdf = builder.VerifiedPdf(tmp_path / "ambigu.pdf", b"pdf-factice")

    with pytest.raises(ValueError, match="PAGE_IMAGE_NON_LISIBLE"):
        builder._pii_evidence(
            _v2_placement_rows(),
            pdfs={V2_ARTIFACT_SHA: pdf},
            inventory_sha256="f" * 64,
        )


def test_v2_producer_emits_normalized_content_addressed_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    release_root = tmp_path / "profile_gate"

    documents = _v2_topology_documents(builder, release_root, monkeypatch)
    decoded = _decode_documents(documents)
    registry = decoded["artifacts.release.json"]
    aggregate = decoded["production-profile-gate.release.json"]
    release_registry = decoded["release-registry.json"]
    subjects = [
        json.loads(documents[release_root / entry["path"]])
        for entry in aggregate["subjects"]
    ]

    assert registry["release_kind"] == "MULTILEVEL_ARTIFACT_REGISTRY_V2"
    assert registry["expected_counts"] == {
        "unique_artifacts": 1,
        "unique_chunks": 1,
    }
    assert len(registry["artifacts"]) == 1
    artifact = registry["artifacts"][0]
    assert artifact["artifact_id"] == artifact["content_sha256"] == V2_ARTIFACT_SHA
    assert artifact["ignored_empty_pages"] == []
    assert artifact["chunks"] == [
        {
            "chunk_index": 0,
            "chunk_id": V2_CHUNK_ID,
            "chunk_sha256": V2_CHUNK_SHA,
            "page_start": 1,
            "page_end": 1,
        }
    ]
    assert "collection" not in artifact
    assert "placements" not in artifact

    assert aggregate["release_kind"] == "MULTILEVEL_AGGREGATE_RELEASE_V2"
    assert aggregate["expected_counts"] == {
        "unique_artifacts": 1,
        "placements": 2,
        "unique_chunks": 1,
        "subjects": 2,
    }
    assert len(subjects) == 2
    for subject in subjects:
        assert subject["release_kind"] == "MULTILEVEL_SUBJECT_RELEASE_V2"
        assert "artifacts" not in subject
        assert "chunks" not in subject
        assert len(subject["placements"]) == 1
        assert subject["placements"][0]["artifact_id"] == V2_ARTIFACT_SHA
    assert release_registry["releases"][0]["release_kind"] == (
        "MULTILEVEL_AGGREGATE_RELEASE_V2"
    )


def test_v2_producer_output_is_accepted_by_both_release_readers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.release_readiness import (
        load_release_expectation,
        load_release_registry_file,
    )

    builder = cast(Any, _module())
    release_root = tmp_path / "profile_gate"
    documents = _v2_topology_documents(builder, release_root, monkeypatch)
    for path, raw in documents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    aggregate_path = release_root / "production-profile-gate.release.json"
    aggregate_sha = hashlib.sha256(aggregate_path.read_bytes()).hexdigest()
    registry_path = release_root.parent / "release-registry.json"
    registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()

    expectation = load_release_expectation(aggregate_path, aggregate_sha)
    registered = load_release_registry_file(registry_path, registry_sha)

    assert len(expectation.artifacts) == 1
    assert len(expectation.placements) == 2
    assert len(registered.manifests) == 1


@pytest.mark.parametrize("target", ["artifact-registry", "subject"])
def test_v2_producer_output_detects_unresealed_sabotage(
    target: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.release_readiness import ReleaseReadinessError, load_release_expectation

    builder = cast(Any, _module())
    release_root = tmp_path / "profile_gate"
    documents = _v2_topology_documents(builder, release_root, monkeypatch)
    for path, raw in documents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    aggregate_path = release_root / "production-profile-gate.release.json"
    aggregate_sha = hashlib.sha256(aggregate_path.read_bytes()).hexdigest()

    if target == "artifact-registry":
        sabotaged_path = release_root / "artifacts.release.json"
        payload = _load(sabotaged_path)
        payload["artifacts"][0]["title"] = "Titre sabote"
    else:
        aggregate = _load(aggregate_path)
        sabotaged_path = release_root / aggregate["subjects"][0]["path"]
        payload = _load(sabotaged_path)
        payload["placements"].clear()
    sabotaged_path.write_bytes(builder.canonical_json_bytes(payload))

    with pytest.raises(ReleaseReadinessError, match="digest"):
        load_release_expectation(aggregate_path, aggregate_sha)


def test_v2_placement_id_keeps_the_historical_algorithm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    profile = _v2_profile(V2_COLLECTIONS[0], 0)
    historical = builder._artifact(
        _v2_placement_rows()[0],
        profile=profile,
        status="specialite",
        preflight=_v2_preflight_artifact(),
        type_doc_mapping={"ressource": "ressource_officielle"},
    )["placements"][0]["placement_id"]
    release_root = tmp_path / "profile_gate"
    documents = _v2_topology_documents(builder, release_root, monkeypatch)
    aggregate = json.loads(
        documents[release_root / "production-profile-gate.release.json"]
    )
    subject = json.loads(documents[release_root / aggregate["subjects"][0]["path"]])

    assert subject["placements"][0]["placement_id"] == historical


def _v2_population_rows() -> list[dict[str, Any]]:
    """Deux placements réels pour une seule population documentaire."""
    rows = _v2_placement_rows()
    for index, row in enumerate(rows):
        row.update(
            {
                "drive_modified_time": "2026-08-04T00:00:00Z",
                "external_level": "Première" if index == 0 else "Terminale",
                "external_subject": "Numérique et sciences informatiques",
                "partition_id": f"partition-{index}",
                "year": "2026",
            }
        )
    return rows


def test_v2_catalog_counts_unique_artifacts_without_ambiguous_contents() -> None:
    builder = cast(Any, _module())

    delta, _effective = builder._catalog_documents(_v2_placement_rows())

    assert delta["counts"] == {"unique_artifacts": 1, "placements": 2}
    assert "contents" not in delta["counts"]
    assert len(delta["placements"]) == 2


def test_v2_release_scope_separates_unique_final_set_from_placements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    matrix = [
        {
            "dimensions": {
                "collection": {
                    "value": collection,
                    "source_of_truth": (
                        "services/rag-engine/configs/ingestion_profiles/"
                        f"{collection}.yml"
                    ),
                }
            },
            "content_sha256": [V2_ARTIFACT_SHA],
        }
        for collection in V2_COLLECTIONS
    ]
    profiles = {
        collection: SimpleNamespace(
            profile_version="2.0.0",
            scope=SimpleNamespace(
                model_dump=lambda *, mode, collection=collection: {
                    "collection": collection
                }
            ),
        )
        for collection in V2_COLLECTIONS
    }
    monkeypatch.setattr(builder, "profile_fingerprint", lambda _profile: "e" * 64)
    monkeypatch.setenv("NEXUS_FINAL_MATRIX", str(tmp_path / "synthetic-matrix.json"))

    final_set_raw, accepted_raw, verified_raw = builder._release_scope_inputs(
        matrix=matrix,
        profiles=profiles,
        profile_manifest_digest=V2_PROFILE_DIGEST,
    )

    assert final_set_raw.decode("utf-8").splitlines() == [V2_ARTIFACT_SHA]
    accepted = json.loads(accepted_raw)
    assert len(accepted) == 2
    assert [row["collection"] for row in accepted] == list(V2_COLLECTIONS)
    assert {row["content_sha256"] for row in accepted} == {V2_ARTIFACT_SHA}
    verified = json.loads(verified_raw)
    assert len(verified["profiles"]) == 2


def test_v2_currentness_network_population_is_unique_per_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    calls: list[str] = []

    def completed_download(arguments: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(arguments[-1])
        return SimpleNamespace(stdout=b"contenu officiel")

    monkeypatch.setattr(builder.subprocess, "run", completed_download)
    monkeypatch.setattr(builder, "_sha256_bytes", lambda _content: V2_ARTIFACT_SHA)

    measured = builder._verify_official_downloads(_v2_placement_rows())
    expected = builder._expected_currentness_network_rows(_v2_placement_rows())

    assert calls == [_v2_placement_rows()[0]["current_download_url"]]
    assert [row["content_sha256"] for row in measured] == [V2_ARTIFACT_SHA]
    assert [row["content_sha256"] for row in expected] == [V2_ARTIFACT_SHA]


def test_v2_currentness_evidence_groups_placement_facts_under_one_artifact() -> None:
    builder = cast(Any, _module())
    network_audit = {
        "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
        "network_mode": "UNVERIFIED",
        "currentness_status": "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE",
        "artifacts": [],
    }
    inventory = {
        "corpus_manifest_sha256": "1" * 64,
        "sealed_catalog_sha256": "2" * 64,
        "placement_catalog_sha256": "3" * 64,
        "catalog_delta_sha256": "4" * 64,
        "effective_catalog_authority_sha256": "5" * 64,
    }

    returned_audit, evidence = builder._currentness_documents(
        _v2_population_rows(),
        inventory=inventory,
        inventory_sha256="6" * 64,
        network_audit=network_audit,
    )

    assert returned_audit == network_audit
    assert evidence["evidence_kind"] == "MULTILEVEL_ARTIFACT_CURRENTNESS_V2"
    assert evidence["counts"] == {
        "unique_artifacts": 1,
        "evaluated": 1,
        "current": 0,
        "review_required": 1,
        "unevaluated": 0,
    }
    assert evidence["partition"] == {
        "current": [],
        "review_required": [V2_ARTIFACT_SHA],
        "unevaluated": [],
    }
    assert len(evidence["artifacts"]) == 1
    artifact = evidence["artifacts"][0]
    assert artifact["content_sha256"] == V2_ARTIFACT_SHA
    assert artifact["collections"] == sorted(V2_COLLECTIONS)
    assert artifact["decision"] == "REVIEW_REQUIRED"
    assert artifact["effective_currentness"] is None
    assert artifact["current_download_sha256"] is None
    assert artifact["byte_identity"] is None
    assert len(artifact["placement_facts"]) == 2
    assert [fact["collection"] for fact in artifact["placement_facts"]] == sorted(
        V2_COLLECTIONS
    )


def test_v2_corpus_descriptor_is_derived_from_unique_artifacts() -> None:
    builder = cast(Any, _module())
    expected_digest = hashlib.sha256(f"{V2_ARTIFACT_SHA}\n".encode()).hexdigest()

    descriptor = builder._corpus_descriptor(_v2_placement_rows())

    assert descriptor["final_content_count"] == 1
    assert descriptor["final_content_set_sha256"] == expected_digest


def test_v2_build_release_uses_the_derived_corpus_descriptor() -> None:
    builder = cast(Any, _module())

    assert "_corpus_descriptor(placement_rows)" in inspect.getsource(
        builder.build_release
    )


# --- LOT 1.2 / revue indépendante du producteur V2 --------------------------


def test_v2_writer_refuses_implicit_historical_output_without_writing(
    tmp_path: Path,
) -> None:
    builder = cast(Any, _module())
    historical = tmp_path / "historical" / "production-profile-gate.release.json"
    _write(historical, b"historical-v1")

    with pytest.raises(ValueError, match=r"output|fresh|fra[iî]che|histor"):
        builder._write_documents({historical: b"replacement-v2"}, output_dir=None)

    assert historical.read_bytes() == b"historical-v1"


def test_v2_producer_refuses_a_declared_profile_without_placement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    missing_collection = "rag_nexus_nsi_seconde_specialite"
    profiles = {
        collection: _v2_profile(collection, index)
        for index, collection in enumerate(V2_COLLECTIONS)
    }
    profiles[missing_collection] = _v2_profile(missing_collection, 0)
    monkeypatch.setattr(builder, "profile_fingerprint", lambda _profile: "e" * 64)

    with pytest.raises(ValueError, match=r"profile|collection|placement"):
        builder._release_topology_documents(
            _v2_placement_rows(),
            profiles=profiles,
            profile_manifest_digest=V2_PROFILE_DIGEST,
            collection_config={
                collection: {"statut": "specialite"} for collection in profiles
            },
            preflight_by_sha={V2_ARTIFACT_SHA: _v2_preflight_artifact()},
            type_doc_mapping={"ressource": "ressource_officielle"},
            authorities=_v2_authorities(),
            models=_v2_models(builder),
            release_root=tmp_path / "profile_gate",
            release_id="lot-1-2-option-a",
            school_year="2026-2027",
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "content-identity", "source-path"],
)
def test_v2_producer_refuses_preflight_population_or_identity_drift(
    mutation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(Any, _module())
    profiles = {
        collection: _v2_profile(collection, index)
        for index, collection in enumerate(V2_COLLECTIONS)
    }
    preflight_by_sha = {V2_ARTIFACT_SHA: _v2_preflight_artifact()}
    if mutation == "missing":
        preflight_by_sha.clear()
    elif mutation == "extra":
        extra_sha = "f" * 64
        extra = copy.deepcopy(_v2_preflight_artifact())
        extra["content_sha256"] = extra_sha
        extra["source_path"] = "extra.pdf"
        preflight_by_sha[extra_sha] = extra
    elif mutation == "content-identity":
        preflight_by_sha[V2_ARTIFACT_SHA]["content_sha256"] = "f" * 64
    else:
        preflight_by_sha[V2_ARTIFACT_SHA]["source_path"] = "other/document.pdf"
    monkeypatch.setattr(builder, "profile_fingerprint", lambda _profile: "e" * 64)

    with pytest.raises(ValueError, match=r"preflight"):
        builder._release_topology_documents(
            _v2_placement_rows(),
            profiles=profiles,
            profile_manifest_digest=V2_PROFILE_DIGEST,
            collection_config={
                collection: {"statut": "specialite"} for collection in profiles
            },
            preflight_by_sha=preflight_by_sha,
            type_doc_mapping={"ressource": "ressource_officielle"},
            authorities=_v2_authorities(),
            models=_v2_models(builder),
            release_root=tmp_path / "profile_gate",
            release_id="lot-1-2-option-a",
            school_year="2026-2027",
        )


def test_v2_writer_d31_failure_is_atomic_and_corrected_release_can_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.release_readiness import ReleaseReadinessError

    builder = cast(Any, _module())
    release_root = builder.RELEASE_ROOT
    valid_documents = _v2_topology_documents(builder, release_root, monkeypatch)
    invalid_documents = dict(valid_documents)
    artifact_registry_path = release_root / "artifacts.release.json"
    sabotaged_registry = json.loads(invalid_documents[artifact_registry_path])
    sabotaged_registry["artifacts"][0]["title"] = "Titre non rescelle"
    invalid_documents[artifact_registry_path] = builder.canonical_json_bytes(
        sabotaged_registry
    )

    valid_identity = builder._identite_de_release(valid_documents)
    final_target = tmp_path / f"release-{valid_identity}"
    monkeypatch.setattr(builder, "_identite_de_release", lambda _documents: valid_identity)

    with pytest.raises(ReleaseReadinessError, match="digest"):
        builder._write_documents(invalid_documents, output_dir=tmp_path)

    assert not final_target.exists(), "D-31 a laissé une cible finale invalide"
    assert builder._write_documents(valid_documents, output_dir=tmp_path) == final_target
    assert final_target.is_dir()


def test_v2_writer_validates_parent_registry_before_atomic_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.release_readiness import ReleaseReadinessError

    builder = cast(Any, _module())
    documents = _v2_topology_documents(builder, builder.RELEASE_ROOT, monkeypatch)
    registry_path = builder.RELEASE_ROOT.parent / "release-registry.json"
    sabotaged_registry = json.loads(documents[registry_path])
    sabotaged_registry["releases"][0]["expected_manifest_sha256"] = "0" * 64
    documents[registry_path] = builder.canonical_json_bytes(sabotaged_registry)

    identity = builder._identite_de_release(documents)
    final_target = tmp_path / f"release-{identity}"

    with pytest.raises(ReleaseReadinessError, match="digest"):
        builder._write_documents(documents, output_dir=tmp_path)

    assert not final_target.exists(), "le registre parent invalide a été publié"


def test_v2_placement_id_matches_independent_historical_golden() -> None:
    builder = cast(Any, _module())
    profile = _v2_profile(V2_COLLECTIONS[0], 0)

    placement = builder._placement(
        _v2_placement_rows()[0],
        profile=profile,
        status="specialite",
        include_artifact_id=True,
    )

    assert placement["placement_id"] == (
        "0dbc97c6481c2ebcfeb972b5868aa26bebe9bb8766e6852d4c757e4db68ef572"
    )
