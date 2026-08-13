"""Publication OCI du corpus scellé — adressée par contenu, sans tag d'autorité.

**Ce que la publication ajoute, et ce qu'elle n'ajoute pas.** Elle ne crée
aucune identité : les trois digests qui comptent — manifeste, arbre,
archive — sont calculés en amont, sur des octets locaux. La publication
les rend *récupérables*. C'est pourquoi elle est idempotente sans effort
particulier : un registre adressé par contenu range deux fois les mêmes
octets au même endroit.

**Aucun tag ne fait autorité.** Un tag peut être posé pour qu'un humain
retrouve l'artefact, mais rien dans la chaîne ne le lit : ``latest`` ou
``v1`` peuvent être repointés sans trace, et une campagne approuvée
cesserait de désigner ce qui a été relu. ``corpus_source_resolver`` ne
connaît qu'un digest, et ce module ne lui en fabrique jamais un autre.

**Le digest est vérifié, pas reçu.** Le registre renvoie le digest sous
lequel il a rangé le manifeste. On le recalcule localement et on refuse
s'il diverge : accepter ce que le serveur annonce reviendrait à lui
déléguer l'identité de l'objet qu'on publie.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: Type de média de l'artefact. Distinct d'une image : rien ici n'est
#: exécutable, et un consommateur qui tenterait de le lancer doit échouer
#: sur le type plutôt que sur le contenu.
CORPUS_ARTIFACT_TYPE = "application/vnd.nexus.corpus.v1+json"
CORPUS_CONFIG_MEDIA_TYPE = "application/vnd.nexus.corpus.config.v1+json"
CORPUS_LAYER_MEDIA_TYPE = "application/vnd.nexus.corpus.tar+zstd"
OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"

#: Annotation portant le nom canonique de l'archive à l'intérieur de la
#: couche. Une seule couche est publiée : plusieurs rendraient ambigu
#: *ce* qui a été scellé.
TITLE_ANNOTATION = "org.opencontainers.image.title"


class CorpusPublicationError(RuntimeError):
    """La publication ne peut pas prouver ce qu'elle a poussé — refus."""


@dataclass(frozen=True)
class BlobRef:
    """Un blob, identifié par son digest et sa taille."""

    media_type: str
    digest: str
    size: int

    def to_descriptor(self, *, annotations: dict[str, str] | None = None) -> dict:
        descriptor: dict = {
            "mediaType": self.media_type,
            "digest": self.digest,
            "size": self.size,
        }
        if annotations:
            descriptor["annotations"] = dict(sorted(annotations.items()))
        return descriptor


@dataclass(frozen=True)
class CorpusArtifact:
    """L'artefact prêt à pousser, et l'identité qu'il aura."""

    manifest_bytes: bytes
    manifest_digest: str
    config_bytes: bytes
    config: BlobRef
    layer: BlobRef
    campaign_id: str

    @property
    def reference_suffix(self) -> str:
        """Le suffixe ``@sha256:…`` par lequel la campagne le désignera."""
        return f"@{self.manifest_digest}"


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_json(payload: dict) -> bytes:
    """JSON canonique, sans espace superflu.

    Le digest du manifeste OCI porte sur *ces* octets : une indentation
    différente produirait un autre digest pour le même contenu logique, et
    la campagne cesserait de se vérifier."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_corpus_artifact(
    *,
    campaign_id: str,
    manifest_sha256: str,
    tree_digest: str,
    archive_sha256: str,
    object_count: int,
    uncompressed_bytes: int,
    layer_path: Path,
) -> CorpusArtifact:
    """Assemble l'artefact OCI autour de la couche déjà produite.

    Les digests ne sont pas recalculés ici : ils viennent de l'acquisition
    et sont *inscrits* dans la configuration, de sorte qu'un consommateur
    qui ne dispose que de l'artefact puisse encore savoir ce qu'il doit
    retrouver après extraction."""
    if not layer_path.is_file():
        raise CorpusPublicationError(f"layer {layer_path} is absent")
    layer_bytes = layer_path.stat().st_size
    if layer_bytes == 0:
        raise CorpusPublicationError(
            "the transport layer is empty — publishing it would create a valid "
            "reference to nothing"
        )

    digest = hashlib.sha256()
    with layer_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    layer = BlobRef(
        media_type=CORPUS_LAYER_MEDIA_TYPE,
        digest="sha256:" + digest.hexdigest(),
        size=layer_bytes,
    )

    # La configuration porte l'identité *du contenu décompressé*. C'est
    # elle qui permet de vérifier après extraction, indépendamment du
    # compresseur ayant produit la couche.
    config_bytes = _canonical_json(
        {
            "artifactType": CORPUS_ARTIFACT_TYPE,
            "campaignId": campaign_id,
            "manifestSha256": manifest_sha256,
            "treeDigest": tree_digest,
            "archiveSha256": archive_sha256,
            "objectCount": object_count,
            "uncompressedBytes": uncompressed_bytes,
        }
    )
    config = BlobRef(
        media_type=CORPUS_CONFIG_MEDIA_TYPE,
        digest=_digest(config_bytes),
        size=len(config_bytes),
    )

    manifest_bytes = _canonical_json(
        {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST_MEDIA_TYPE,
            "artifactType": CORPUS_ARTIFACT_TYPE,
            "config": config.to_descriptor(),
            "layers": [
                layer.to_descriptor(annotations={TITLE_ANNOTATION: "corpus.tar.zst"})
            ],
            "annotations": {
                "fr.nexus.campaign.id": campaign_id,
                "fr.nexus.corpus.manifest-sha256": manifest_sha256,
                "fr.nexus.corpus.tree-digest": tree_digest,
            },
        }
    )

    return CorpusArtifact(
        manifest_bytes=manifest_bytes,
        manifest_digest=_digest(manifest_bytes),
        config_bytes=config_bytes,
        config=config,
        layer=layer,
        campaign_id=campaign_id,
    )


#: Pousse un blob ; rend le digest sous lequel le registre l'a rangé.
BlobPush = Callable[[str, bytes | Path], str]
#: Pousse le manifeste ; rend le digest annoncé par le registre.
ManifestPush = Callable[[bytes], str]


def publish_corpus_artifact(
    artifact: CorpusArtifact,
    *,
    push_blob: BlobPush,
    push_manifest: ManifestPush,
    layer_path: Path,
) -> str:
    """Pousse l'artefact et **vérifie** le digest que le registre renvoie.

    L'ordre importe : les blobs d'abord, le manifeste ensuite. Un manifeste
    publié avant ses blobs désignerait, le temps d'un intervalle, un
    contenu introuvable — et un consommateur malchanceux lirait une
    référence valide vers rien."""
    returned_config = push_blob(artifact.config.digest, artifact.config_bytes)
    if returned_config != artifact.config.digest:
        raise CorpusPublicationError(
            f"registry stored the config under {returned_config!r} instead of "
            f"{artifact.config.digest!r} — refusing to accept a server-assigned "
            "identity for content we hashed ourselves"
        )

    returned_layer = push_blob(artifact.layer.digest, layer_path)
    if returned_layer != artifact.layer.digest:
        raise CorpusPublicationError(
            f"registry stored the layer under {returned_layer!r} instead of "
            f"{artifact.layer.digest!r}"
        )

    returned_manifest = push_manifest(artifact.manifest_bytes)
    if returned_manifest != artifact.manifest_digest:
        raise CorpusPublicationError(
            f"registry returned manifest digest {returned_manifest!r} but the "
            f"locally computed digest is {artifact.manifest_digest!r} — the "
            "published object is not the one that was assembled"
        )
    return artifact.manifest_digest


def campaign_fields(artifact: CorpusArtifact, *, registry: str, repository: str) -> dict:
    """Les champs à reporter dans le descripteur de campagne.

    Rendus séparément plutôt qu'écrits : le descripteur est versionné et
    relu par un humain, et un outil qui l'écrirait lui-même retirerait à
    l'approbation son objet."""
    return {
        "campaign_id": artifact.campaign_id,
        "source_oci_digest": artifact.manifest_digest,
        "oci_reference": f"{registry}/{repository}@{artifact.manifest_digest}",
        "layer_digest": artifact.layer.digest,
        "layer_bytes": artifact.layer.size,
    }


__all__ = [
    "CORPUS_ARTIFACT_TYPE",
    "CORPUS_CONFIG_MEDIA_TYPE",
    "CORPUS_LAYER_MEDIA_TYPE",
    "OCI_MANIFEST_MEDIA_TYPE",
    "TITLE_ANNOTATION",
    "BlobPush",
    "BlobRef",
    "CorpusArtifact",
    "CorpusPublicationError",
    "ManifestPush",
    "build_corpus_artifact",
    "campaign_fields",
    "publish_corpus_artifact",
]
