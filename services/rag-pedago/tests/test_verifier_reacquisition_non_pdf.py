"""Récupérer n'est pas vérifier.

Un fichier rendu par un canal distant peut être le bon fichier, un autre
fichier de même taille, ou une page d'erreur enregistrée sous le bon nom.
Ces épreuves interdisent qu'un de ces trois cas passe pour le premier.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verifier_reacquisition_non_pdf.py"


def _module():
    spec = importlib.util.spec_from_file_location("verifier_reacquisition_non_pdf", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _demande(octets: bytes, **surcharges: object) -> dict[str, object]:
    base: dict[str, object] = {
        "drive_file_id": "drive-1",
        "expected_content_sha256": hashlib.sha256(octets).hexdigest(),
        "expected_size": len(octets),
        "classification": "INTERACTIVE_RESOURCE_SERVABLE",
    }
    base.update(surcharges)
    return base


def _deposer(racine: Path, nom: str, octets: bytes) -> None:
    racine.mkdir(parents=True, exist_ok=True)
    (racine / nom).write_bytes(octets)


def test_un_fichier_conforme_est_verifie(tmp_path: Path) -> None:
    m = _module()
    octets = b"PK\x03\x04 archive geogebra"
    demande = _demande(octets)
    _deposer(tmp_path / "recu", f"{demande['expected_content_sha256']}.ggb", octets)
    rendu = m.verifier([demande], tmp_path / "recu")
    assert rendu["results"][0]["status"] == "VERIFIED"
    assert rendu["ACCEPTANCE_MET"] is True
    assert rendu["NON_PDF_SHA_MATCH"] == 1
    assert rendu["NON_PDF_UNACCOUNTED"] == 0


def test_un_fichier_de_meme_taille_mais_d_autres_octets_est_refuse(
    tmp_path: Path,
) -> None:
    """LE cas que le nom de fichier ne peut pas attraper : l'adresse est bonne,
    le contenu ne l'est pas."""
    m = _module()
    octets = b"les bons octets"
    demande = _demande(octets)
    _deposer(
        tmp_path / "recu",
        f"{demande['expected_content_sha256']}.ggb",
        b"les MAUVAIS!!!"[: len(octets)].ljust(len(octets), b"x"),
    )
    rendu = m.verifier([demande], tmp_path / "recu")
    assert rendu["results"][0]["status"] == "MISMATCH"
    assert rendu["NON_PDF_SHA_MISMATCH"] == 1
    assert rendu["ACCEPTANCE_MET"] is False


def test_une_taille_fausse_et_une_empreinte_juste_sont_deux_compteurs(
    tmp_path: Path,
) -> None:
    """Le manifeste peut mentir sur autre chose que le contenu ; confondre les
    deux priverait l'exploitant de l'information qui dit QUOI réparer."""
    m = _module()
    octets = b"contenu"
    demande = _demande(octets, expected_size=len(octets) + 1)
    _deposer(tmp_path / "recu", demande["expected_content_sha256"], octets)
    rendu = m.verifier([demande], tmp_path / "recu")
    assert rendu["NON_PDF_SIZE_MISMATCH"] == 1
    assert rendu["NON_PDF_SHA_MISMATCH"] == 0
    assert rendu["results"][0]["status"] == "MISMATCH"


def test_un_fichier_absent_est_nomme_manquant_pas_compte_comme_recu(
    tmp_path: Path,
) -> None:
    m = _module()
    (tmp_path / "recu").mkdir()
    rendu = m.verifier([_demande(b"jamais livre")], tmp_path / "recu")
    assert rendu["results"][0]["status"] == "MISSING"
    assert rendu["NON_PDF_MISSING"] == 1
    assert rendu["NON_PDF_REACQUIRED"] == 0
    assert rendu["NON_PDF_UNACCOUNTED"] == 0, "un absent reste COMPTÉ"
    assert rendu["ACCEPTANCE_MET"] is False


def test_l_acceptation_exige_la_population_entiere(tmp_path: Path) -> None:
    m = _module()
    a, b = b"premier", b"second"
    da, db = _demande(a, drive_file_id="d-a"), _demande(b, drive_file_id="d-b")
    _deposer(tmp_path / "recu", str(da["expected_content_sha256"]), a)
    rendu = m.verifier([da, db], tmp_path / "recu")
    assert rendu["NON_PDF_EXPECTED"] == 2
    assert rendu["NON_PDF_REACQUIRED"] == 1
    assert rendu["ACCEPTANCE_MET"] is False


def test_le_verificateur_n_ouvre_jamais_l_archive(tmp_path: Path) -> None:
    """L'identité de source est celle du FICHIER PHYSIQUE.

    Une archive hostile ne doit pas pouvoir agir pendant une simple
    vérification : ce script ne fait que lire des octets et les hacher."""
    source = SCRIPT.read_text(encoding="utf-8")
    for interdit in ("zipfile", "ZipFile", "tarfile", "shutil.unpack", "extractall"):
        assert interdit not in source, f"le vérificateur ouvre une archive : {interdit}"


def test_le_cli_rend_un_code_de_sortie_qui_reflete_l_acceptation(
    tmp_path: Path,
) -> None:
    m = _module()
    octets = b"conforme"
    demande = _demande(octets)
    manifeste = tmp_path / "m.json"
    manifeste.write_text(json.dumps({"requests": [demande]}), encoding="utf-8")
    recu = tmp_path / "recu"
    _deposer(recu, str(demande["expected_content_sha256"]), octets)
    sortie = tmp_path / "out.json"
    assert m.main(["--manifest", str(manifeste), "--received-root", str(recu),
                   "--output", str(sortie)]) == 0
    (recu / str(demande["expected_content_sha256"])).write_bytes(b"altere!")
    assert m.main(["--manifest", str(manifeste), "--received-root", str(recu),
                   "--output", str(sortie)]) == 1
