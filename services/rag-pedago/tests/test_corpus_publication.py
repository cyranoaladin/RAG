"""Tests de la publication OCI. Le registre est injecté : aucun test ne
contacte GHCR et aucun jeton n'entre dans le dépôt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rag_pedago.governance.corpus_publication import (
    CORPUS_ARTIFACT_TYPE,
    CORPUS_LAYER_MEDIA_TYPE,
    CorpusPublicationError,
    build_corpus_artifact,
    campaign_fields,
    publish_corpus_artifact,
)

MANIFEST_SHA = "d" * 64
TREE_DIGEST = "5" * 64
ARCHIVE_SHA = "7" * 64


class FakeRegistry:
    """Un registre adressé par contenu, en mémoire."""

    def __init__(self, *, lie_about: str | None = None) -> None:
        self.blobs: dict[str, bytes] = {}
        self.manifests: dict[str, bytes] = {}
        self.order: list[str] = []
        self.lie_about = lie_about

    def push_blob(self, digest: str, payload: bytes | Path) -> str:
        data = payload.read_bytes() if isinstance(payload, Path) else payload
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        self.blobs[actual] = data
        self.order.append(f"blob:{actual}")
        if self.lie_about == "blob":
            return "sha256:" + "0" * 64
        return actual

    def push_manifest(self, payload: bytes) -> str:
        actual = "sha256:" + hashlib.sha256(payload).hexdigest()
        self.manifests[actual] = payload
        self.order.append(f"manifest:{actual}")
        if self.lie_about == "manifest":
            return "sha256:" + "1" * 64
        return actual


@pytest.fixture
def layer(tmp_path: Path) -> Path:
    path = tmp_path / "corpus.tar.zst"
    path.write_bytes(b"\x28\xb5\x2f\xfd" + b"compressed-corpus" * 100)
    return path


def make_artifact(layer: Path, **overrides):
    base = dict(
        campaign_id="2026-08-corpus-public",
        manifest_sha256=MANIFEST_SHA,
        tree_digest=TREE_DIGEST,
        archive_sha256=ARCHIVE_SHA,
        object_count=2583,
        uncompressed_bytes=1759467520,
        layer_path=layer,
    )
    base.update(overrides)
    return build_corpus_artifact(**base)


class TestArtifactAssembly:
    def test_the_manifest_digest_is_computed_locally(self, layer: Path) -> None:
        artifact = make_artifact(layer)
        expected = "sha256:" + hashlib.sha256(artifact.manifest_bytes).hexdigest()
        assert artifact.manifest_digest == expected

    def test_the_config_records_what_to_verify_after_extraction(
        self, layer: Path
    ) -> None:
        """Un consommateur qui ne dispose que de l'artefact doit encore
        savoir ce qu'il doit retrouver."""
        config = json.loads(make_artifact(layer).config_bytes)
        assert config["manifestSha256"] == MANIFEST_SHA
        assert config["treeDigest"] == TREE_DIGEST
        assert config["archiveSha256"] == ARCHIVE_SHA
        assert config["objectCount"] == 2583

    def test_exactly_one_layer_is_published(self, layer: Path) -> None:
        """Plusieurs couches rendraient ambigu ce qui a été scellé."""
        manifest = json.loads(make_artifact(layer).manifest_bytes)
        assert len(manifest["layers"]) == 1
        assert manifest["layers"][0]["mediaType"] == CORPUS_LAYER_MEDIA_TYPE

    def test_the_artifact_type_is_not_an_executable_image(self, layer: Path) -> None:
        manifest = json.loads(make_artifact(layer).manifest_bytes)
        assert manifest["artifactType"] == CORPUS_ARTIFACT_TYPE

    def test_the_manifest_bytes_are_canonical(self, layer: Path) -> None:
        """Une indentation différente produirait un autre digest pour le
        même contenu logique."""
        raw = make_artifact(layer).manifest_bytes.decode()
        assert ": " not in raw and ", " not in raw

    def test_assembly_is_deterministic(self, layer: Path) -> None:
        assert make_artifact(layer).manifest_digest == make_artifact(layer).manifest_digest

    def test_a_different_corpus_yields_a_different_digest(self, layer: Path) -> None:
        one = make_artifact(layer)
        two = make_artifact(layer, manifest_sha256="e" * 64)
        assert one.manifest_digest != two.manifest_digest

    def test_an_absent_layer_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusPublicationError, match="absent"):
            make_artifact(tmp_path / "nope.zst")

    def test_an_empty_layer_is_refused(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.zst"
        empty.write_bytes(b"")
        with pytest.raises(CorpusPublicationError, match="valid reference to nothing"):
            make_artifact(empty)


class TestPublication:
    def test_a_nominal_publication_returns_the_local_digest(self, layer: Path) -> None:
        artifact = make_artifact(layer)
        registry = FakeRegistry()
        digest = publish_corpus_artifact(
            artifact,
            push_blob=registry.push_blob,
            push_manifest=registry.push_manifest,
            layer_path=layer,
        )
        assert digest == artifact.manifest_digest

    def test_blobs_are_pushed_before_the_manifest(self, layer: Path) -> None:
        """Un manifeste publié avant ses blobs désignerait, un instant, un
        contenu introuvable."""
        registry = FakeRegistry()
        publish_corpus_artifact(
            make_artifact(layer),
            push_blob=registry.push_blob,
            push_manifest=registry.push_manifest,
            layer_path=layer,
        )
        kinds = [entry.split(":")[0] for entry in registry.order]
        assert kinds == ["blob", "blob", "manifest"]

    def test_a_registry_that_reassigns_the_manifest_digest_is_refused(
        self, layer: Path
    ) -> None:
        """Accepter ce que le serveur annonce reviendrait à lui déléguer
        l'identité de l'objet publié."""
        registry = FakeRegistry(lie_about="manifest")
        with pytest.raises(CorpusPublicationError, match="not the one that was assembled"):
            publish_corpus_artifact(
                make_artifact(layer),
                push_blob=registry.push_blob,
                push_manifest=registry.push_manifest,
                layer_path=layer,
            )

    def test_a_registry_that_reassigns_a_blob_digest_is_refused(
        self, layer: Path
    ) -> None:
        registry = FakeRegistry(lie_about="blob")
        with pytest.raises(CorpusPublicationError, match="server-assigned identity"):
            publish_corpus_artifact(
                make_artifact(layer),
                push_blob=registry.push_blob,
                push_manifest=registry.push_manifest,
                layer_path=layer,
            )

    def test_republishing_the_same_corpus_is_idempotent(self, layer: Path) -> None:
        """Un registre adressé par contenu range deux fois les mêmes octets
        au même endroit : la reprise ne crée pas de doublon logique."""
        registry = FakeRegistry()
        artifact = make_artifact(layer)
        first = publish_corpus_artifact(
            artifact, push_blob=registry.push_blob,
            push_manifest=registry.push_manifest, layer_path=layer,
        )
        second = publish_corpus_artifact(
            make_artifact(layer), push_blob=registry.push_blob,
            push_manifest=registry.push_manifest, layer_path=layer,
        )
        assert first == second
        assert len(registry.manifests) == 1
        assert len(registry.blobs) == 2


class TestCampaignFields:
    def test_the_reference_is_pinned_by_digest_never_by_tag(self, layer: Path) -> None:
        fields = campaign_fields(
            make_artifact(layer),
            registry="ghcr.io",
            repository="cyranoaladin/rag-corpus",
        )
        assert "@sha256:" in fields["oci_reference"]
        assert ":latest" not in fields["oci_reference"]
        assert fields["oci_reference"].startswith(
            "ghcr.io/cyranoaladin/rag-corpus@sha256:"
        )

    def test_the_fields_are_returned_not_written(self, layer: Path) -> None:
        """Le descripteur est relu par un humain ; un outil qui l'écrirait
        retirerait à l'approbation son objet."""
        fields = campaign_fields(
            make_artifact(layer), registry="ghcr.io",
            repository="cyranoaladin/rag-corpus",
        )
        assert isinstance(fields, dict)
        assert fields["source_oci_digest"].startswith("sha256:")

    def test_the_layer_size_is_reported(self, layer: Path) -> None:
        fields = campaign_fields(
            make_artifact(layer), registry="ghcr.io",
            repository="cyranoaladin/rag-corpus",
        )
        assert fields["layer_bytes"] == layer.stat().st_size
