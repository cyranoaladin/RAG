"""Les onze autorisations LOT41A-V2 (r4) de publication de V4 — dérivées, jamais ressaisies.

Chaque r4 garde de la r2 de sa collection les droits, domaines et exclusions,
prend du profil V4 sa portée (programme officiel, visibilité servie), sa version
et son empreinte, et porte une liste POSITIVE de contenus : les placements que
V4 prescrit dans CETTE collection. Les r2 restent intactes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))
for _paquet in ("contracts", "release-chain", "pdf-page-policy"):
    sys.path.insert(0, str(RACINE / f"packages/{_paquet}/src"))

import build_lot41a_r4_authorizations as r4  # noqa: E402
from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: E402

V4 = RACINE / r4.V4_DIR


def _placements() -> dict[str, set[str]]:
    couples: dict[str, set[str]] = {}
    for sujet in sorted((V4 / "subjects").glob("*.release.json")):
        document = json.loads(sujet.read_text(encoding="utf-8"))
        couples[document["collection"]] = {p["artifact_id"] for p in document["placements"]}
    return couples


@pytest.fixture(scope="module")
def documents() -> dict[str, dict]:
    return r4.construire(RACINE)


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


def test_chaque_r4_garde_droits_domaines_audience_de_sa_r2(documents):
    for identifiant, document in documents.items():
        r2 = json.loads((RACINE / r4.AUTORISATIONS / f"{r4.id_r2(identifiant)}.json").read_text())
        for cle in ("rights_categories", "allowed_domains", "exclusions", "profile_id", "decision"):
            assert document[cle] == r2[cle], (identifiant, cle)
        ecarts = {k for k in r2["scope"] if document["scope"][k] != r2["scope"][k]}
        assert ecarts == {"programme_version", "visibility"}, (identifiant, ecarts)
        assert document["scope"]["audience"] == r2["scope"]["audience"]
        assert r2["protocol_version"] == "LOT41A-V1"
        assert document["protocol_version"] == "LOT41A-V2"


def test_la_portee_et_l_empreinte_sont_celles_du_profil_v4(documents):
    from nexus_release_chain.ingestion_profiles.registry import load_profile_registry, profile_fingerprint

    profils = {str(p.scope.collection): p for p in load_profile_registry(RACINE / r4.PROFILS_V4).values()}
    for document in documents.values():
        profil = profils[document["scope"]["collection"]]
        assert document["profile_fingerprint"] == profile_fingerprint(profil)
        assert document["profile_version"] == profil.profile_version
        assert document["scope"]["programme_version"] == str(profil.scope.programme_version)
        assert document["scope"]["visibility"] == str(profil.scope.visibility)


def test_le_manifest_digest_est_l_empreinte_canonique_declaree_par_v4(documents):
    manifeste = json.loads((V4 / "production-profile-gate.release.json").read_text())
    for document in documents.values():
        assert document["manifest_digest"] == manifeste["authorities"]["profile_manifest_sha256"]


def test_la_preuve_pii_citee_est_celle_de_v4(documents):
    manifeste = json.loads((V4 / "production-profile-gate.release.json").read_text())
    for document in documents.values():
        chemin, _, empreinte = document["pii_absence_evidence"].partition("@sha256:")
        assert chemin == f"{r4.V4_DIR}/pii_evidence.json"
        assert empreinte == manifeste["authorities"]["pii_evidence_sha256"]


def test_les_octets_verses_quand_ils_existent_sont_ceux_que_la_release_derive(documents):
    """Les r4 sont versées par leur PROPRE PR (enregistrement avant fusion) ;
    là où elles existent, leurs octets doivent être exactement les dérivés."""
    for identifiant, document in documents.items():
        artefact = ScopeAuthorizationArtifactV2.model_validate(document)
        chemin = RACINE / artefact.canonical_path()
        if chemin.is_file():
            assert chemin.read_bytes() == artefact.canonical_bytes(), identifiant


def test_les_r2_ne_sont_pas_modifiees():
    for fichier in sorted((RACINE / r4.AUTORISATIONS).glob("lot41a-staging-v2-*-r2.json")):
        assert json.loads(fichier.read_text())["protocol_version"] == "LOT41A-V1"
