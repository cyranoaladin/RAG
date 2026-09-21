"""Chargement vérifié du catalogue d'artefacts d'une release scellée.

Le catalogue n'est pas « un dictionnaire déjà vérifié » : c'est le fichier
que le manifeste de release **nomme** et dont il **déclare l'empreinte**,
relu et confronté à cette déclaration. Sans cette confrontation, un
catalogue étranger cohérent avec lui-même passerait.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PDF_MEDIA_TYPE = "application/pdf"


class SealedReleaseCatalogError(RuntimeError):
    """Le catalogue ne peut pas être établi — jamais contourné."""


@dataclass(frozen=True)
class VerifiedSealedReleaseCatalog:
    """Ensemble scellé, indexé par ``content_sha256``, et son invariant de
    format.

    ``media_type_invariant`` est vide tant qu'aucun traitement n'a établi le
    format. Il vaut alors refus à la lecture : une extension de nom de
    fichier n'est pas une preuve de lecture des octets, et le lecteur ne
    suppose pas un type de média.
    """

    release_id: str
    release_manifest_sha256: str
    registry_sha256: str
    artifacts: dict[str, dict[str, Any]]
    media_type_invariant: str
    media_type_basis: str

    def __len__(self) -> int:
        return len(self.artifacts)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_sealed_release_catalog(
    release_dir: Path,
    *,
    expected_release_manifest_sha256: str,
    transfer_manifest_path: Path | None = None,
    expected_transfer_manifest_sha256: str | None = None,
) -> VerifiedSealedReleaseCatalog:
    """Charge le catalogue nommé par le manifeste, ou refuse.

    Le chemin ne fait que **localiser** les octets ; l'autorité vient de
    l'empreinte que le manifeste déclare pour eux.
    """
    manifest_path = release_dir / "production-profile-gate.release.json"
    if not manifest_path.is_file():
        raise SealedReleaseCatalogError(
            f"no release manifest at {manifest_path} — the catalogue cannot be "
            "established"
        )
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = _digest(manifest_raw)
    if manifest_sha != expected_release_manifest_sha256:
        raise SealedReleaseCatalogError(
            f"release manifest hashes to {manifest_sha}, not the expected "
            f"{expected_release_manifest_sha256} — this is not the release that "
            "was approved"
        )
    manifest = json.loads(manifest_raw.decode("utf-8"))

    registry = manifest.get("artifact_registry")
    if not isinstance(registry, dict) or not registry.get("path"):
        raise SealedReleaseCatalogError(
            "the release manifest names no artifact registry"
        )
    declared_sha = str(registry.get("sha256", ""))
    registry_path = release_dir / str(registry["path"])
    if not registry_path.is_file():
        raise SealedReleaseCatalogError(
            f"the artifact registry named by the manifest is absent: {registry_path}"
        )
    registry_raw = registry_path.read_bytes()
    registry_sha = _digest(registry_raw)
    if registry_sha != declared_sha:
        raise SealedReleaseCatalogError(
            f"artifact registry hashes to {registry_sha}, but the release manifest "
            f"declares {declared_sha} — a catalogue consistent with itself but "
            "foreign to this release is refused"
        )

    document = json.loads(registry_raw.decode("utf-8"))
    entries = document.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise SealedReleaseCatalogError("the artifact registry carries no artifact")

    # Le catalogue doit décrire LA release du manifeste, pas une autre : un
    # même content_sha256 peut exister dans deux releases sans que leurs
    # autorités soient interchangeables.
    release_id = str(manifest.get("release_id", ""))
    registry_release = str(document.get("release_id", ""))
    if registry_release and registry_release != release_id:
        raise SealedReleaseCatalogError(
            f"the artifact registry describes release {registry_release!r}, not "
            f"{release_id!r}"
        )

    artifacts: dict[str, dict[str, Any]] = {}
    for entry in entries:
        sha = entry.get("content_sha256")
        if not isinstance(sha, str) or not sha:
            raise SealedReleaseCatalogError(
                "an artifact entry carries no content_sha256"
            )
        if sha in artifacts:
            raise SealedReleaseCatalogError(
                f"content {sha} appears twice in the artifact registry — which "
                "entry applies cannot be decided"
            )
        artifacts[sha] = entry

    declared = manifest.get("expected_counts", {})
    attendu = declared.get("unique_artifacts")
    if isinstance(attendu, int) and attendu != len(artifacts):
        raise SealedReleaseCatalogError(
            f"the release manifest expects {attendu} unique artifacts, the "
            f"catalogue carries {len(artifacts)}"
        )

    invariant, basis = _establish_media_type(
        artifacts,
        transfer_manifest_path=transfer_manifest_path,
        expected_transfer_manifest_sha256=expected_transfer_manifest_sha256,
    )
    return VerifiedSealedReleaseCatalog(
        release_id=release_id,
        release_manifest_sha256=manifest_sha,
        registry_sha256=registry_sha,
        artifacts=artifacts,
        media_type_invariant=invariant,
        media_type_basis=basis,
    )


def _establish_media_type(
    artifacts: dict[str, dict[str, Any]],
    *,
    transfer_manifest_path: Path | None,
    expected_transfer_manifest_sha256: str | None,
) -> tuple[str, str]:
    """Établit le type de média, ou rend une chaîne vide.

    Aucune autorité de cette release ne déclare un type par artefact. Ce qui
    peut être établi, c'est une **convention de nommage du manifeste de
    transfert** : tous les objets transférés portent la même extension, et
    l'ensemble transféré couvre exactement le catalogue.

    C'est une convention de nom, pas une lecture des octets — le champ
    ``media_type_basis`` le dit, pour qu'aucun lecteur n'y voie une mesure.
    """
    if transfer_manifest_path is None or expected_transfer_manifest_sha256 is None:
        return "", "non etabli : aucun manifeste de transfert fourni"
    raw = transfer_manifest_path.read_bytes()
    actual = _digest(raw)
    if actual != expected_transfer_manifest_sha256:
        raise SealedReleaseCatalogError(
            f"transfer manifest hashes to {actual}, not the expected "
            f"{expected_transfer_manifest_sha256}"
        )
    document = json.loads(raw.decode("utf-8"))
    files = document.get("files")
    if not isinstance(files, list) or not files:
        return "", "non etabli : le manifeste de transfert ne liste aucun objet"
    extensions = {str(f.get("file", "")).rsplit(".", 1)[-1].lower() for f in files}
    transferes = {
        str(f.get("file", "")).rsplit(".", 1)[0] for f in files
    }
    if transferes != set(artifacts):
        return "", (
            "non etabli : l'ensemble transfere ne coincide pas avec le catalogue"
        )
    if extensions != {"pdf"}:
        return "", f"non etabli : extensions heterogenes {sorted(extensions)}"
    return PDF_MEDIA_TYPE, (
        "convention de nommage du manifeste de transfert : les "
        f"{len(files)} objets portent l'extension .pdf et couvrent exactement "
        "le catalogue (aucune lecture des octets)"
    )


__all__ = [
    "PDF_MEDIA_TYPE",
    "SealedReleaseCatalogError",
    "VerifiedSealedReleaseCatalog",
    "load_sealed_release_catalog",
]
