"""Les onze autorisations LOT41A-V2 (r3) de publication de V3 — dérivées, jamais ressaisies.

Chaque r3 est la r2 de sa collection, portée au protocole V2 : même scope, mêmes
droits, même audience, même profil — et une liste POSITIVE de contenus, celle
des placements que V3 prescrit dans CETTE collection. Les r2 restent intactes :
elles ont fondé l'acquisition passée.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))
sys.path.insert(0, str(RACINE / "packages/contracts/src"))

import build_lot41a_r3_authorizations as r3  # noqa: E402
from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: E402

V3 = RACINE / r3.V3_DIR


def _placements() -> dict[str, set[str]]:
    couples: dict[str, set[str]] = {}
    for sujet in sorted((V3 / "subjects").glob("*.release.json")):
        document = json.loads(sujet.read_text(encoding="utf-8"))
        couples[document["collection"]] = {p["artifact_id"] for p in document["placements"]}
    return couples


@pytest.fixture(scope="module")
def documents() -> dict[str, dict]:
    return r3.construire(RACINE)


def test_onze_autorisations_une_par_collection(documents):
    assert len(documents) == 11
    assert {d["scope"]["collection"] for d in documents.values()} == set(_placements())


def test_la_couverture_est_exactement_les_479_couples(documents):
    placements = _placements()
    couples = 0
    for document in documents.values():
        collection = document["scope"]["collection"]
        assert set(document["allowed_content_sha256"]) == placements[collection], collection
        couples += len(document["allowed_content_sha256"])
    assert couples == 479


def test_chaque_r3_est_sa_r2_sans_extension_de_droits_ni_d_audience(documents):
    for identifiant, document in documents.items():
        r2 = json.loads((RACINE / r3.AUTORISATIONS / f"{r3.id_r2(identifiant)}.json").read_text())
        for cle in ("scope", "rights_categories", "allowed_domains", "exclusions",
                    "profile_id", "profile_version", "profile_fingerprint", "decision"):
            assert document[cle] == r2[cle], (identifiant, cle)
        assert r2["protocol_version"] == "LOT41A-V1"
        assert document["protocol_version"] == "LOT41A-V2"


def test_le_manifest_digest_est_l_empreinte_canonique_declaree_par_v3(documents):
    manifeste = json.loads((V3 / "production-profile-gate.release.json").read_text())
    for document in documents.values():
        assert document["manifest_digest"] == manifeste["authorities"]["profile_manifest_sha256"]


def test_la_preuve_pii_citee_est_celle_de_v3(documents):
    manifeste = json.loads((V3 / "production-profile-gate.release.json").read_text())
    for document in documents.values():
        chemin, _, empreinte = document["pii_absence_evidence"].partition("@sha256:")
        assert chemin == f"{r3.V3_DIR}/pii_evidence.json"
        assert empreinte == manifeste["authorities"]["pii_evidence_sha256"]


def test_les_octets_verses_quand_ils_existent_sont_ceux_que_la_release_derive(documents):
    """Les r3 sont versées par leur PROPRE PR (enregistrement avant fusion) ;
    là où elles existent, leurs octets doivent être exactement les dérivés."""
    for identifiant, document in documents.items():
        artefact = ScopeAuthorizationArtifactV2.model_validate(document)
        chemin = RACINE / artefact.canonical_path()
        if chemin.is_file():
            assert chemin.read_bytes() == artefact.canonical_bytes(), identifiant


def test_les_r2_ne_sont_pas_modifiees():
    for fichier in sorted((RACINE / r3.AUTORISATIONS).glob("lot41a-staging-v2-*-r2.json")):
        assert json.loads(fichier.read_text())["protocol_version"] == "LOT41A-V1"
