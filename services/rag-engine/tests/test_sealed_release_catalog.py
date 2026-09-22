"""Le catalogue scellé est chargé et vérifié, jamais supposé (lot CU).

« Un dictionnaire passé dans deps avec un commentaire *déjà vérifié* » ne
constitue pas une vérification. Le catalogue est le fichier que le manifeste
de release **nomme** et dont il **déclare l'empreinte** : il est relu et
confronté à cette déclaration, sans quoi un catalogue cohérent avec
lui-même mais étranger à la release passerait.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ingestor.ingestion_control.sealed_release_catalog import (
    SealedReleaseCatalogError,
    load_sealed_release_catalog,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _ecrire(chemin: Path, document: dict) -> str:
    brut = json.dumps(document, ensure_ascii=False).encode("utf-8")
    chemin.write_bytes(brut)
    return hashlib.sha256(brut).hexdigest()


def _release(tmp_path: Path, *, artefacts: list[dict] | None = None,
             release_id: str = "rel-v2",
             registry_release_id: str | None = "rel-v2",
             attendu: int | None = None) -> tuple[Path, str]:
    """Écrit une release minimale et rend (répertoire, digest du manifeste)."""
    entrees = artefacts if artefacts is not None else [
        {"content_sha256": SHA_A, "page_count": 7, "source_path": "z/a.pdf"},
    ]
    registre: dict = {"artifacts": entrees}
    if registry_release_id is not None:
        registre["release_id"] = registry_release_id
    registry_sha = _ecrire(tmp_path / "artifacts.release.json", registre)
    manifeste = {
        "release_id": release_id,
        "artifact_registry": {
            "path": "artifacts.release.json",
            "sha256": registry_sha,
        },
    }
    if attendu is not None:
        manifeste["expected_counts"] = {"unique_artifacts": attendu}
    sha = _ecrire(tmp_path / "production-profile-gate.release.json", manifeste)
    return tmp_path, sha


# --- 1 — le cas nominal ---------------------------------------------------


def test_le_catalogue_nomme_par_le_manifeste_est_charge(tmp_path: Path) -> None:
    repertoire, sha = _release(tmp_path)
    catalogue = load_sealed_release_catalog(
        repertoire, expected_release_manifest_sha256=sha
    )
    assert len(catalogue) == 1
    assert catalogue.release_id == "rel-v2"
    assert catalogue.artifacts[SHA_A]["page_count"] == 7


# --- 2 — l'empreinte fait autorité, pas le chemin -------------------------


def test_un_manifeste_qui_ne_correspond_pas_a_son_empreinte_est_refuse(
    tmp_path: Path,
) -> None:
    repertoire, _ = _release(tmp_path)
    with pytest.raises(SealedReleaseCatalogError, match="not the release that"):
        load_sealed_release_catalog(
            repertoire, expected_release_manifest_sha256="f" * 64
        )


def test_un_catalogue_altere_est_refuse(tmp_path: Path) -> None:
    """Le registre ne correspond plus à l'empreinte que le manifeste déclare."""
    repertoire, sha = _release(tmp_path)
    registre = repertoire / "artifacts.release.json"
    registre.write_bytes(registre.read_bytes().replace(b'"page_count": 7',
                                                       b'"page_count": 8'))
    with pytest.raises(SealedReleaseCatalogError, match="foreign to this release"):
        load_sealed_release_catalog(repertoire, expected_release_manifest_sha256=sha)


def test_un_catalogue_absent_est_refuse(tmp_path: Path) -> None:
    repertoire, sha = _release(tmp_path)
    (repertoire / "artifacts.release.json").unlink()
    with pytest.raises(SealedReleaseCatalogError, match="is absent"):
        load_sealed_release_catalog(repertoire, expected_release_manifest_sha256=sha)


def test_un_manifeste_absent_est_refuse(tmp_path: Path) -> None:
    with pytest.raises(SealedReleaseCatalogError, match="no release manifest"):
        load_sealed_release_catalog(
            tmp_path, expected_release_manifest_sha256="a" * 64
        )


# --- 3 — le catalogue doit décrire CETTE release --------------------------


def test_un_catalogue_d_une_autre_release_est_refuse(tmp_path: Path) -> None:
    """Un même content_sha256 peut exister dans deux releases sans que leurs
    autorités soient interchangeables."""
    repertoire, sha = _release(tmp_path, release_id="rel-v2",
                               registry_release_id="rel-v1")
    with pytest.raises(SealedReleaseCatalogError, match="describes release"):
        load_sealed_release_catalog(repertoire, expected_release_manifest_sha256=sha)


def test_un_compte_declare_different_est_refuse(tmp_path: Path) -> None:
    repertoire, sha = _release(tmp_path, attendu=42)
    with pytest.raises(SealedReleaseCatalogError, match="expects 42 unique"):
        load_sealed_release_catalog(repertoire, expected_release_manifest_sha256=sha)


def test_un_contenu_en_double_dans_le_registre_est_refuse(tmp_path: Path) -> None:
    repertoire, sha = _release(tmp_path, artefacts=[
        {"content_sha256": SHA_A, "page_count": 7, "source_path": "z/a.pdf"},
        {"content_sha256": SHA_A, "page_count": 9, "source_path": "z/b.pdf"},
    ])
    with pytest.raises(SealedReleaseCatalogError, match="appears twice"):
        load_sealed_release_catalog(repertoire, expected_release_manifest_sha256=sha)


def test_un_registre_vide_est_refuse(tmp_path: Path) -> None:
    repertoire, sha = _release(tmp_path, artefacts=[])
    with pytest.raises(SealedReleaseCatalogError, match="carries no artifact"):
        load_sealed_release_catalog(repertoire, expected_release_manifest_sha256=sha)


# --- 4 — le type de média est établi ou laissé vide -----------------------


def _transfert(tmp_path: Path, fichiers: list[str]) -> tuple[Path, str]:
    chemin = tmp_path / "transfer.json"
    sha = _ecrire(chemin, {"files": [{"file": f} for f in fichiers]})
    return chemin, sha


def test_sans_manifeste_de_transfert_l_invariant_reste_vide(tmp_path: Path) -> None:
    """Non établi n'est pas « application/pdf par défaut »."""
    repertoire, sha = _release(tmp_path)
    catalogue = load_sealed_release_catalog(
        repertoire, expected_release_manifest_sha256=sha
    )
    assert catalogue.media_type_invariant == ""
    assert "non etabli" in catalogue.media_type_basis


def test_l_invariant_est_etabli_quand_le_transfert_couvre_le_catalogue(
    tmp_path: Path,
) -> None:
    repertoire, sha = _release(tmp_path)
    chemin, tsha = _transfert(tmp_path, [f"{SHA_A}.pdf"])
    catalogue = load_sealed_release_catalog(
        repertoire,
        expected_release_manifest_sha256=sha,
        transfer_manifest_path=chemin,
        expected_transfer_manifest_sha256=tsha,
    )
    assert catalogue.media_type_invariant == "application/pdf"
    assert "aucune lecture des octets" in catalogue.media_type_basis


def test_un_transfert_qui_ne_couvre_pas_le_catalogue_n_etablit_rien(
    tmp_path: Path,
) -> None:
    repertoire, sha = _release(tmp_path)
    chemin, tsha = _transfert(tmp_path, [f"{SHA_B}.pdf"])
    catalogue = load_sealed_release_catalog(
        repertoire,
        expected_release_manifest_sha256=sha,
        transfer_manifest_path=chemin,
        expected_transfer_manifest_sha256=tsha,
    )
    assert catalogue.media_type_invariant == ""
    assert "ne coincide pas" in catalogue.media_type_basis


def test_des_extensions_heterogenes_n_etablissent_rien(tmp_path: Path) -> None:
    repertoire, sha = _release(tmp_path, artefacts=[
        {"content_sha256": SHA_A, "page_count": 7, "source_path": "z/a.pdf"},
        {"content_sha256": SHA_B, "page_count": 3, "source_path": "z/b.odt"},
    ])
    chemin, tsha = _transfert(tmp_path, [f"{SHA_A}.pdf", f"{SHA_B}.odt"])
    catalogue = load_sealed_release_catalog(
        repertoire,
        expected_release_manifest_sha256=sha,
        transfer_manifest_path=chemin,
        expected_transfer_manifest_sha256=tsha,
    )
    assert catalogue.media_type_invariant == ""
    assert "heterogenes" in catalogue.media_type_basis


def test_un_transfert_qui_ne_correspond_pas_a_son_empreinte_est_refuse(
    tmp_path: Path,
) -> None:
    repertoire, sha = _release(tmp_path)
    chemin, _ = _transfert(tmp_path, [f"{SHA_A}.pdf"])
    with pytest.raises(SealedReleaseCatalogError, match="transfer manifest hashes"):
        load_sealed_release_catalog(
            repertoire,
            expected_release_manifest_sha256=sha,
            transfer_manifest_path=chemin,
            expected_transfer_manifest_sha256="f" * 64,
        )


def test_la_base_du_type_de_media_ne_pretend_pas_a_une_mesure(
    tmp_path: Path,
) -> None:
    """Une extension de nom n'est pas une preuve de lecture des octets, et le
    champ qui l'établit doit le dire."""
    repertoire, sha = _release(tmp_path)
    chemin, tsha = _transfert(tmp_path, [f"{SHA_A}.pdf"])
    catalogue = load_sealed_release_catalog(
        repertoire,
        expected_release_manifest_sha256=sha,
        transfer_manifest_path=chemin,
        expected_transfer_manifest_sha256=tsha,
    )
    assert "convention de nommage" in catalogue.media_type_basis
    assert "aucune lecture des octets" in catalogue.media_type_basis
