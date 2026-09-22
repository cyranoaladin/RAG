"""Adoption des placements acquis par une release successeur (ADR-0059 § 5).

Épreuves de la planification, sans base : elle décide seule ce qui est
adoptable, et la persistance n'écrit que ce qu'elle a décidé.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from ingestor.ingestion_control.sealed_release_adoption import (
    FAITS_INVARIANTS,
    AcquiredRow,
    SealedReleaseAdoptionError,
    SuccessorIdentity,
    plan_adoption,
)

PREDECESSEUR = "production-profile-gate-2026-2027-v2"
MANIFESTE_PREDECESSEUR = "1" * 64
SUCCESSEUR = SuccessorIdentity(
    release_id="production-profile-gate-2026-2027-v3",
    release_manifest_sha256="2" * 64,
    artifacts_release_sha256="3" * 64,
    candidate_inventory_sha256="4" * 64,
    artifact_transfer_manifest_sha256="5" * 64,
    currentness_evidence_sha256="6" * 64,
    pii_evidence_sha256="7" * 64,
)
CONTENUS = ("a" * 64, "b" * 64)


def _evidence(sha: str, collection: str, *, release_id: str, manifeste: str,
              currentness: str) -> dict[str, Any]:
    return {
        "protocol_version": "SEALED-RELEASE-INGESTION-V1",
        "pipeline_kind": "sealed_release_pipeline",
        "release_id": release_id,
        "release_manifest_sha256": manifeste,
        "artifacts_release_sha256": "8" * 64,
        "candidate_inventory_sha256": "9" * 64,
        "artifact_transfer_manifest_sha256": "0" * 64,
        "collection": collection,
        "content_sha256": sha,
        "placement_id": f"placement-{sha[:4]}-{collection}",
        "source_placement_id": f"source-{sha[:4]}",
        "external_document_type": "diaporama",
        "type_doc": "ressource_officielle",
        "provenance_discovery_url": "https://eduscol.education.gouv.fr/page",
        "provenance_artifact_url": "https://eduscol.education.gouv.fr/page",
        "chunk_count": 12,
        "review_status": "reviewed",
        "placement_status": "active",
        "currentness": currentness,
    }


PLACEMENTS = [
    (CONTENUS[0], "rag_nexus_svt_terminale_specialite"),
    (CONTENUS[0], "rag_nexus_svt_premiere_specialite"),
    (CONTENUS[1], "rag_nexus_ses_terminale_specialite"),
]


def _acquis() -> list[AcquiredRow]:
    lignes = []
    for sha, collection in PLACEMENTS:
        payload = _evidence(
            sha, collection, release_id=PREDECESSEUR, manifeste=MANIFESTE_PREDECESSEUR,
            currentness="current",
        )
        payload["scope_authorization_id"] = "lot41a-staging-v2-" + collection
        payload["scope_authorization_digest"] = "f" * 64
        lignes.append(
            AcquiredRow(
                resource_id=uuid4(), artifact_id=uuid4(), content_sha256=sha,
                collection=collection, payload=payload,
            )
        )
    return lignes


def _prescrits(currentness: str = "official_snapshot") -> list[dict[str, Any]]:
    return [
        _evidence(
            sha, collection, release_id=SUCCESSEUR.release_id,
            manifeste=SUCCESSEUR.release_manifest_sha256, currentness=currentness,
        )
        for sha, collection in PLACEMENTS
    ]


def _plan(acquis: list[AcquiredRow] | None = None,
          prescrits: list[dict[str, Any]] | None = None, **kw: Any) -> list[Any]:
    return plan_adoption(
        acquired=acquis if acquis is not None else _acquis(),
        successor_placements=prescrits if prescrits is not None else _prescrits(),
        successor=kw.pop("successor", SUCCESSEUR),
        predecessor_release_id=kw.pop("predecessor_release_id", PREDECESSEUR),
        predecessor_release_manifest_sha256=kw.pop(
            "predecessor_release_manifest_sha256", MANIFESTE_PREDECESSEUR
        ),
    )


def test_un_successeur_adopte_chaque_placement_acquis_une_fois() -> None:
    acquis = _acquis()
    lignes = _plan(acquis)

    assert len(lignes) == len(PLACEMENTS)
    assert {ligne.resource_id for ligne in lignes} == {row.resource_id for row in acquis}
    assert {ligne.currentness for ligne in lignes} == {"official_snapshot"}
    assert {ligne.successor for ligne in lignes} == {SUCCESSEUR}
    assert {ligne.predecessor_release_id for ligne in lignes} == {PREDECESSEUR}


def test_l_adoption_ne_touche_pas_la_ligne_acquise() -> None:
    acquis = _acquis()
    avant = [dict(row.payload) for row in acquis]
    _plan(acquis)
    assert [dict(row.payload) for row in acquis] == avant


def test_un_rejeu_identique_a_la_meme_empreinte() -> None:
    acquis = _acquis()
    assert [ligne.digest() for ligne in _plan(acquis)] == [
        ligne.digest() for ligne in _plan(acquis)
    ]


def test_l_empreinte_nomme_les_preuves_du_successeur() -> None:
    acquis = _acquis()
    autre = SuccessorIdentity(
        **{**SUCCESSEUR.__dict__, "currentness_evidence_sha256": "e" * 64}
    )
    assert _plan(acquis)[0].digest() != _plan(acquis, successor=autre)[0].digest()


@pytest.mark.parametrize("champ", FAITS_INVARIANTS)
def test_un_fait_invariant_divergent_refuse_toute_l_adoption(champ: str) -> None:
    prescrits = _prescrits()
    valeur = prescrits[1][champ]
    prescrits[1][champ] = (valeur + 1) if isinstance(valeur, int) else f"{valeur}-autre"
    with pytest.raises(SealedReleaseAdoptionError):
        _plan(prescrits=prescrits)


def test_un_placement_prescrit_jamais_acquis_refuse() -> None:
    acquis = _acquis()[:-1]
    with pytest.raises(SealedReleaseAdoptionError, match="bijection"):
        _plan(acquis)


def test_un_placement_acquis_non_prescrit_refuse() -> None:
    with pytest.raises(SealedReleaseAdoptionError, match="bijection"):
        _plan(prescrits=_prescrits()[:-1])


@pytest.mark.parametrize("actualite", ["archive", "review_required", "actuel", ""])
def test_une_actualite_non_publiable_n_est_pas_adoptee(actualite: str) -> None:
    with pytest.raises(SealedReleaseAdoptionError, match="currentness"):
        _plan(prescrits=_prescrits(currentness=actualite))


def test_une_identite_d_octets_prouvee_reste_current() -> None:
    assert {ligne.currentness for ligne in _plan(prescrits=_prescrits("current"))} == {
        "current"
    }


def test_une_release_ne_s_adopte_pas_elle_meme() -> None:
    with pytest.raises(SealedReleaseAdoptionError, match="successor"):
        _plan(predecessor_release_id=SUCCESSEUR.release_id)


def test_un_successeur_qui_nomme_le_manifeste_du_predecesseur_refuse() -> None:
    meme = SuccessorIdentity(
        **{**SUCCESSEUR.__dict__, "release_manifest_sha256": MANIFESTE_PREDECESSEUR}
    )
    prescrits = _prescrits()
    for prescrit in prescrits:
        prescrit["release_manifest_sha256"] = MANIFESTE_PREDECESSEUR
    with pytest.raises(SealedReleaseAdoptionError, match="same release"):
        _plan(prescrits=prescrits, successor=meme)


def test_des_lignes_acquises_sous_un_autre_manifeste_refusent() -> None:
    with pytest.raises(SealedReleaseAdoptionError, match="manifest"):
        _plan(predecessor_release_manifest_sha256="d" * 64)


def test_rien_d_acquis_rien_a_adopter() -> None:
    with pytest.raises(SealedReleaseAdoptionError, match="nothing to adopt"):
        _plan(acquis=[])


def test_une_ligne_acquise_qui_contredit_son_payload_refuse() -> None:
    acquis = _acquis()
    faussee = AcquiredRow(
        resource_id=acquis[0].resource_id, artifact_id=acquis[0].artifact_id,
        content_sha256=CONTENUS[1], collection=acquis[0].collection,
        payload=acquis[0].payload,
    )
    with pytest.raises(SealedReleaseAdoptionError, match="contradicts"):
        _plan([faussee, *acquis[1:]])


def test_un_placement_prescrit_pour_une_autre_release_refuse() -> None:
    prescrits = _prescrits()
    prescrits[0]["release_id"] = PREDECESSEUR
    with pytest.raises(SealedReleaseAdoptionError, match="successor"):
        _plan(prescrits=prescrits)


def test_les_identites_adoptees_sont_celles_de_la_base() -> None:
    acquis = _acquis()
    par_ressource = {row.resource_id: row for row in acquis}
    for ligne in _plan(acquis):
        row = par_ressource[ligne.resource_id]
        assert isinstance(ligne.artifact_id, UUID)
        assert ligne.artifact_id == row.artifact_id
        assert (ligne.content_sha256, ligne.collection) == (
            row.content_sha256, row.collection
        )
