"""Lot DH — sélection du modèle d'embedding du banc de récupération.

Défaut corrigé : la fixture du banc remplaçait TOUJOURS
``RAG_EMBEDDING_MODEL_CACHE_DIR`` par un inventaire fictif, y compris quand
``NEXUS_DH_WORKER_B_CLI=1`` demandait le vrai CLI de Worker B sur E5. Le
chemin fourni par l'opérateur n'atteignait jamais le contexte du banc.

Ces épreuves portent sur la SÉLECTION du modèle. L'« artefact E5 » construit
ici est une FIXTURE qui satisfait le vérificateur d'intégrité canonique
(manifeste, inventaire, empreintes) avec un fichier de poids factice : elle ne
contient aucun poids E5 et ne qualifie rien.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI / "integration"))

import _banc_dh_modele as selection  # noqa: E402
from _banc_multiniveaux import modele_e5_du_banc  # noqa: E402

VARIABLES = (selection.VARIABLE_MODE, selection.VARIABLE_RACINE, selection.VARIABLE_INVENTAIRE)


@pytest.fixture(autouse=True)
def _environnement_isole(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def _artefact_de_forme_e5(racine: Path) -> str:
    """FIXTURE de forme E5 (aucun poids réel) ; rend l'empreinte d'inventaire."""
    racine.mkdir(parents=True)
    (racine / "manifest.json").write_text(json.dumps(
        {"model_id": "intfloat/multilingual-e5-large", "canonical_dim": 1024}
    ))
    (racine / "config.json").write_text("{}")
    (racine / "model.safetensors").write_bytes(b"fixture: aucun poids E5")
    lignes = [
        f"{hashlib.sha256((racine / nom).read_bytes()).hexdigest()}  {nom}"
        for nom in ("config.json", "manifest.json", "model.safetensors")
    ]
    (racine / "SHA256SUMS").write_text("\n".join(lignes) + "\n")
    return hashlib.sha256((racine / "SHA256SUMS").read_bytes()).hexdigest()


def _mode_cli(monkeypatch: pytest.MonkeyPatch, racine: Path, inventaire: str) -> None:
    monkeypatch.setenv(selection.VARIABLE_MODE, "1")
    monkeypatch.setenv(selection.VARIABLE_RACINE, str(racine))
    monkeypatch.setenv(selection.VARIABLE_INVENTAIRE, inventaire)


def test_mode_cli_conserve_le_chemin_de_l_operateur(tmp_path, monkeypatch):
    operateur = tmp_path / "e5-operateur"
    inventaire = _artefact_de_forme_e5(operateur)
    _mode_cli(monkeypatch, operateur, inventaire)
    with selection.modele_du_banc(racine_fictive=tmp_path / "fictif") as modele:
        assert (modele.mode, modele.fictif) == ("cli", False)
        assert modele.racine == operateur.resolve()
        assert modele.inventaire_sha256 == inventaire
        # Ce que le constructeur du contexte lira : le chemin de l'opérateur.
        assert os.environ[selection.VARIABLE_RACINE] == str(operateur)
        vu, empreinte = modele_e5_du_banc()
        assert (vu, empreinte) == (operateur, inventaire)
        selection.exiger_modele_transmis(modele, modele_e5=vu, inventaire_sha256=empreinte)
    assert not (tmp_path / "fictif").exists(), "aucun inventaire fictif n'est créé en mode CLI"
    assert os.environ[selection.VARIABLE_RACINE] == str(operateur)


def test_mode_debug_utilise_un_inventaire_fictif_marque(tmp_path, monkeypatch):
    monkeypatch.setenv(selection.VARIABLE_RACINE, "/chemin/operateur/ignore-en-debug")
    with selection.modele_du_banc(racine_fictive=tmp_path / "fictif") as modele:
        assert (modele.mode, modele.fictif) == ("debug", True)
        assert (modele.racine / selection.MARQUEUR_FICTIF).is_file()
        assert not any(p.suffix == ".safetensors" or p.name == "pytorch_model.bin" for p in modele.racine.iterdir())
        vu, empreinte = modele_e5_du_banc()
        assert (vu, empreinte) == (modele.racine, modele.inventaire_sha256)
    assert os.environ[selection.VARIABLE_RACINE] == "/chemin/operateur/ignore-en-debug"


@pytest.mark.parametrize("cas", ["chemin absent", "inventaire absent", "chemin inexistant", "sans poids",
                                 "inventaire inattendu", "manifeste d'un autre modèle"])
def test_mode_cli_refuse_sans_modele_reel_et_ne_replie_jamais_vers_debug(tmp_path, monkeypatch, cas):
    operateur = tmp_path / "e5-operateur"
    inventaire = _artefact_de_forme_e5(operateur)
    _mode_cli(monkeypatch, operateur, inventaire)
    if cas == "chemin absent":
        monkeypatch.delenv(selection.VARIABLE_RACINE)
    elif cas == "inventaire absent":
        monkeypatch.delenv(selection.VARIABLE_INVENTAIRE)
    elif cas == "chemin inexistant":
        monkeypatch.setenv(selection.VARIABLE_RACINE, str(tmp_path / "absent"))
    elif cas == "sans poids":
        (operateur / "model.safetensors").unlink()
    elif cas == "inventaire inattendu":
        monkeypatch.setenv(selection.VARIABLE_INVENTAIRE, "0" * 64)
    else:
        (operateur / "manifest.json").write_text(json.dumps({"model_id": "autre", "canonical_dim": 1024}))
    avant = {v: os.environ.get(v) for v in VARIABLES}
    with pytest.raises(selection.ModeleDuBancRefuse, match="mode CLI"):
        with selection.modele_du_banc(racine_fictive=tmp_path / "fictif"):
            pytest.fail("le banc ne doit pas démarrer")
    assert not (tmp_path / "fictif").exists(), "aucun repli vers l'inventaire fictif"
    assert {v: os.environ.get(v) for v in VARIABLES} == avant


@pytest.mark.parametrize("precedent", [None, "/valeur/precedente"])
def test_l_environnement_est_restaure_meme_apres_une_exception(tmp_path, monkeypatch, precedent):
    if precedent is not None:
        monkeypatch.setenv(selection.VARIABLE_RACINE, precedent)
    with pytest.raises(RuntimeError, match="interruption"):
        with selection.modele_du_banc(racine_fictive=tmp_path / "fictif") as modele:
            assert os.environ[selection.VARIABLE_RACINE] == str(modele.racine)
            raise RuntimeError("interruption du banc")
    assert os.environ.get(selection.VARIABLE_RACINE) == precedent


@pytest.mark.parametrize("valeur,attendu", [("1", "cli"), ("0", "debug"), ("", "debug")])
def test_le_mode_est_explicite(monkeypatch, valeur, attendu):
    monkeypatch.setenv(selection.VARIABLE_MODE, valeur)
    assert selection.mode_worker_b(os.environ) == attendu


def test_un_mode_ambigu_est_refuse(monkeypatch):
    monkeypatch.setenv(selection.VARIABLE_MODE, "oui")
    with pytest.raises(selection.ModeleDuBancRefuse):
        selection.mode_worker_b(os.environ)


def _arguments_reels_de_worker_b(contexte: SimpleNamespace) -> list[str]:
    """Les arguments que le banc passe RÉELLEMENT au CLI de Worker B."""
    precedent = os.environ.get("NEXUS_BATCH_CLI_ACCEPTANCE")
    os.environ["NEXUS_BATCH_CLI_ACCEPTANCE"] = "1"
    try:
        import test_batch_publication_cli_acceptance as banc_batch  # noqa: PLC0415
    finally:
        if precedent is None:
            os.environ.pop("NEXUS_BATCH_CLI_ACCEPTANCE", None)
        else:
            os.environ["NEXUS_BATCH_CLI_ACCEPTANCE"] = precedent
    return banc_batch._arguments_de_worker_b(contexte, iterations=3)


def test_le_cli_recoit_exactement_le_modele_selectionne(tmp_path, monkeypatch):
    operateur = tmp_path / "e5-operateur"
    inventaire = _artefact_de_forme_e5(operateur)
    _mode_cli(monkeypatch, operateur, inventaire)
    with selection.modele_du_banc(racine_fictive=tmp_path / "fictif") as modele:
        vu, empreinte = modele_e5_du_banc()
        contexte = SimpleNamespace(
            magasin=tmp_path / "magasin", modele_e5=vu, e5_inventaire_sha256=empreinte,
            arguments_d_autorites=lambda: [],
        )
        arguments = _arguments_reels_de_worker_b(contexte)
        selection.exiger_modele_transmis(modele, modele_e5=vu, inventaire_sha256=empreinte, arguments=arguments)
        # Contre-épreuves : un autre chemin, ou une autre empreinte, est refusé.
        autre = SimpleNamespace(**{**contexte.__dict__, "modele_e5": tmp_path / "autre"})
        with pytest.raises(selection.ModeleDuBancRefuse, match="embedding-artifact-root"):
            selection.exiger_modele_transmis(modele, modele_e5=vu, inventaire_sha256=empreinte,
                                             arguments=_arguments_reels_de_worker_b(autre))
        faux = SimpleNamespace(**{**contexte.__dict__, "e5_inventaire_sha256": "1" * 64})
        with pytest.raises(selection.ModeleDuBancRefuse, match="inventory-sha256"):
            selection.exiger_modele_transmis(modele, modele_e5=vu, inventaire_sha256=empreinte,
                                             arguments=_arguments_reels_de_worker_b(faux))


def test_un_inventaire_fictif_n_atteint_jamais_le_cli(tmp_path):
    with selection.modele_du_banc(racine_fictive=tmp_path / "fictif") as modele:
        contexte = SimpleNamespace(
            magasin=tmp_path / "magasin", modele_e5=modele.racine,
            e5_inventaire_sha256=modele.inventaire_sha256, arguments_d_autorites=lambda: [],
        )
        with pytest.raises(selection.ModeleDuBancRefuse, match="FICTIF"):
            selection.exiger_modele_transmis(
                modele, modele_e5=modele.racine, inventaire_sha256=modele.inventaire_sha256,
                arguments=_arguments_reels_de_worker_b(contexte),
            )
