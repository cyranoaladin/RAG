"""Le chargeur canonique, eprouve par l adversaire.

La propriete qui compte n est pas qu il sache lire deux formats : c est qu il
soit le SEUL a choisir entre eux. Neuf consommateurs qui choisissent chacun de
leur cote finissent par ne pas choisir pareil, et le meme document est alors
autorise ici et refuse la.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from nexus_contracts import (
    AUTHORIZATION_SET_PROTOCOL_VERSION,
    AUTHORIZATION_SET_PROTOCOL_VERSION_V2,
    AuthorizationSetError,
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    AuthorizationSetV2,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV2,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.authorization_loader import (
    AUTHORIZATION_PROTOCOLS_ACCEPTED,
    NEW_RELEASE_AUTHORIZATION_PROTOCOL,
    load_authorization_set,
)

MAINTENANT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
CONTENU = "1" * 64
MANIFESTE = "d" * 64


def _scope() -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_premiere",
            "collection": "hlp_premiere",
            "niveau": "premiere",
            "voie": "generale",
            "matiere": "hlp",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "public",
            "school_year": "2026-2027",
            "programme_version": "2026",
        }
    )


def _membre() -> AuthorizationSetMemberV1:
    scope = _scope()
    return AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": "hlp-premiere",
            "authorization_digest": sha256(b"auth").hexdigest(),
            "review_binding_digest": sha256(b"binding").hexdigest(),
            "scope": scope,
            "scope_digest": scope_digest(scope),
            "allowed_content_sha256": [CONTENU],
            "allowed_content_count": 1,
            "allowed_content_set_sha256": content_set_digest((CONTENU,)),
            "valid_from": MAINTENANT - timedelta(days=1),
            "valid_until": MAINTENANT + timedelta(days=30),
        }
    )


@pytest.fixture
def octets_v2() -> bytes:
    scope = _scope()
    placement = ReleaseScopePlacementV2.build(
        placements=[
            ReleaseScopePlacementEntryV1.model_validate(
                {
                    "content_sha256": CONTENU,
                    "profile_id": scope.collection,
                    "profile_version": "v1",
                    "profile_fingerprint": "c" * 64,
                    "scope": scope,
                }
            )
        ],
        profile_manifest_digest=MANIFESTE,
    )
    return AuthorizationSetV2.build(
        members=[_membre()],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFESTE,
        release_scope_placement_digest=placement.digest(),
    ).canonical_bytes()


@pytest.fixture
def octets_v1() -> bytes:
    return AuthorizationSetV1.build(
        members=[_membre()],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFESTE,
        release_scope_placement_digest="e" * 64,
        authority_required_content_sha256=(CONTENU,),
    ).canonical_bytes()


# --- accepter les deux, sans deviner -----------------------------------


def test_un_document_v2_est_lu_en_v2(octets_v2) -> None:
    charge = load_authorization_set(octets_v2)
    assert charge.protocol_version == AUTHORIZATION_SET_PROTOCOL_VERSION_V2
    assert charge.is_v2 is True
    assert charge.is_historical_v1 is False


def test_un_document_v1_reste_lisible(octets_v1) -> None:
    """Refuser la V1 rejetterait tout artefact operateur existant."""
    charge = load_authorization_set(octets_v1)
    assert charge.protocol_version == AUTHORIZATION_SET_PROTOCOL_VERSION
    assert charge.is_historical_v1 is True
    assert charge.is_v2 is False


def test_le_protocole_est_lu_jamais_infere(octets_v2) -> None:
    """Un document qui MENT sur son protocole doit etre refuse, pas rattrape.

    Un essai V2 puis repli V1 accepterait un V2 malforme comme un V1 invalide,
    et le message parlerait du mauvais protocole.
    """
    document = json.loads(octets_v2.decode("utf-8"))
    document["protocol_version"] = AUTHORIZATION_SET_PROTOCOL_VERSION
    menteur = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(AuthorizationSetError):
        load_authorization_set(menteur)


def test_un_protocole_inconnu_est_refuse_PAR_LE_CHARGEUR(octets_v2) -> None:
    """Le refus doit venir du chargeur, pas du parseur sous-jacent.

    Les deux refusent, donc un simple `pytest.raises` passerait meme sans la
    garde du chargeur — c est ce qu une mutation a montre. Ce qui distingue le
    refus du chargeur est qu il NOMME les protocoles lisibles : un appelant
    apprend quoi produire, au lieu d apprendre seulement qu il a tort.
    """
    document = json.loads(octets_v2.decode("utf-8"))
    document["protocol_version"] = "NEXUS-AUTHORIZATION-SET-V3"
    octets = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(AuthorizationSetError) as refus:
        load_authorization_set(octets)
    message = str(refus.value)
    assert "unsupported protocol_version" in message
    assert "Protocoles lisibles" in message, (
        "le refus ne vient pas du chargeur : la garde du chargeur a disparu et "
        "seul le parseur sous-jacent refuse encore"
    )
    assert AUTHORIZATION_SET_PROTOCOL_VERSION_V2 in message


def test_un_document_qui_n_est_pas_du_json_est_refuse() -> None:
    with pytest.raises(AuthorizationSetError, match="UTF-8 JSON"):
        load_authorization_set(b"pas du json")


def test_un_json_qui_n_est_pas_un_objet_est_refuse() -> None:
    with pytest.raises(AuthorizationSetError, match="JSON object"):
        load_authorization_set(b"[]")


# --- une release neuve ne retombe jamais en V1 -------------------------


def test_le_protocole_des_releases_neuves_est_v2() -> None:
    assert NEW_RELEASE_AUTHORIZATION_PROTOCOL == AUTHORIZATION_SET_PROTOCOL_VERSION_V2


def test_require_v2_refuse_un_document_historique(octets_v1) -> None:
    charge = load_authorization_set(octets_v1)
    with pytest.raises(AuthorizationSetError, match="release neuve"):
        charge.require_v2(because="la release 2026-2027")


def test_require_v2_nomme_l_exigence_dans_son_refus(octets_v1) -> None:
    """Un refus qui ne dit pas au nom de quoi il refuse est un refus qu on
    contourne."""
    charge = load_authorization_set(octets_v1)
    with pytest.raises(AuthorizationSetError, match="la release 2026-2027"):
        charge.require_v2(because="la release 2026-2027")


def test_require_v2_rend_le_document_quand_il_est_v2(octets_v2) -> None:
    charge = load_authorization_set(octets_v2)
    ensemble = charge.require_v2(because="la release 2026-2027")
    assert isinstance(ensemble, AuthorizationSetV2)
    assert ensemble.protocol_version == AUTHORIZATION_SET_PROTOCOL_VERSION_V2


# --- ce que le chargeur ne fait pas ------------------------------------


def test_le_chargeur_ne_verifie_rien(octets_v2) -> None:
    """Charger n est pas autoriser. La verification appartient au gate, qui
    differe entre les deux protocoles."""
    import nexus_contracts.authorization_loader as module

    source = module.__doc__ or ""
    assert "ne verifie rien" in source
    noms = set(dir(module))
    assert not {n for n in noms if n.startswith("verify")}, (
        "le chargeur expose une verification : elle appartient au gate"
    )


def test_les_deux_protocoles_sont_acceptes_et_seulement_eux() -> None:
    assert set(AUTHORIZATION_PROTOCOLS_ACCEPTED) == {
        AUTHORIZATION_SET_PROTOCOL_VERSION,
        AUTHORIZATION_SET_PROTOCOL_VERSION_V2,
    }
