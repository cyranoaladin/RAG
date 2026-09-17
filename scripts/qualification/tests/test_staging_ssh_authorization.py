"""Épreuves de l'autorisation SSH de staging : périmètre borné, fail-closed, liée au plan."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import check_staging_authorization as autorisation  # noqa: E402


@pytest.fixture()
def document() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION).read_text(encoding="utf-8"))


def _plan_sha(document: dict) -> str:
    return hashlib.sha256((RACINE / document["execution_plan"]["path"]).read_bytes()).hexdigest()


def test_autorisation_versionnee_valide_et_liee_au_plan_courant(document):
    assert autorisation.evaluer(document, plan_sha256=_plan_sha(document)) == []


def test_refuse_si_le_plan_a_change_apres_l_autorisation(document):
    assert any("plan" in e for e in autorisation.evaluer(document, plan_sha256="0" * 64))


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [("host", "autre-hote"), ("compose_project", "rag"), ("bind_address", "0.0.0.0"),
     ("access", "public"), ("pgvector_container_required", "rag_pgvector"), ("ingestor_image", "latest")],
)
def test_refuse_un_perimetre_elargi(document, cle, valeur):
    document["scope"][cle] = valeur
    assert any(cle in e for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document)))


@pytest.mark.parametrize("interdit", sorted(autorisation.INTERDITS_REQUIS))
def test_refuse_une_interdiction_omise(document, interdit):
    document["forbidden"].remove(interdit)
    assert any("interdits" in e for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document)))


def test_refuse_autre_approbateur_usage_multiple_ou_sans_conditions_d_arret(document):
    for muter in (
        lambda d: d.update(granted_by_pull_request_approval_of="quelquun"),
        lambda d: d.update(expires_after_use=False),
        lambda d: d.update(stop_conditions=""),
        lambda d: d["scope"].update(loopback_ports={"ingestor": 80}),
    ):
        copie = copy.deepcopy(document)
        muter(copie)
        assert autorisation.evaluer(copie, plan_sha256=_plan_sha(copie))


def test_sans_fichier_aucune_autorisation(tmp_path):
    assert any("aucune autorisation" in e for e in autorisation.verifier(tmp_path))


def test_une_autorisation_consommee_n_autorise_plus(tmp_path, document):
    document["consumed"] = True
    for relatif, contenu in (
        (autorisation.AUTORISATION, json.dumps(document)),
        (document["execution_plan"]["path"], (RACINE / document["execution_plan"]["path"]).read_text(encoding="utf-8")),
    ):
        (tmp_path / relatif).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relatif).write_text(contenu, encoding="utf-8")
    assert any("consommée" in e or "origin/main" in e for e in autorisation.verifier(tmp_path))


def test_aucun_secret_ni_adresse_dans_l_autorisation(document):
    texte = json.dumps(document).lower()
    for motif in ("password", "token=", "bearer ", "@", "ssh-rsa", "-----begin"):
        assert motif not in texte
