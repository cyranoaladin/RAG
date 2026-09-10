"""Le mapping d autorisation accepte la V2 — et refuse de la verifier a l aveugle.

La V2 compare un ensemble de LIAISONS `(content_sha256, scope)`. La comparaison
par contenu seul ne distingue pas deux placements legitimes d un meme contenu
partage. Un document V2 sans son placement est donc REFUSE, jamais accepte sur
une comparaison qui passerait sans rien prouver.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from nexus_contracts import (
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    AuthorizationSetV2,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV2,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.ingestion import ResourceScope

from ingestor.ingestion_worker.authorization_mapping import (
    AuthorizationMappingError,
    build_authorization_mapping,
)

MAINTENANT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
CONTENU = "1" * 64
MANIFESTE = "d" * 64


def _scope(collection: str = "hlp_premiere", niveau: str = "premiere") -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_" + niveau,
            "collection": collection,
            "niveau": niveau,
            "voie": "generale",
            "matiere": "hlp",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "public",
            "school_year": "2026-2027",
            "programme_version": "2026",
        }
    )


def _membre(scope: ResourceScope, identifiant: str = "hlp") -> AuthorizationSetMemberV1:
    return AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": identifiant,
            "authorization_digest": sha256(identifiant.encode()).hexdigest(),
            "review_binding_digest": sha256(b"binding" + identifiant.encode()).hexdigest(),
            "scope": scope,
            "scope_digest": scope_digest(scope),
            "allowed_content_sha256": [CONTENU],
            "allowed_content_count": 1,
            "allowed_content_set_sha256": content_set_digest((CONTENU,)),
            "valid_from": MAINTENANT - timedelta(days=1),
            "valid_until": MAINTENANT + timedelta(days=30),
        }
    )


def _placement(scope: ResourceScope) -> ReleaseScopePlacementV2:
    return ReleaseScopePlacementV2.build(
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


@pytest.fixture
def materiel_v2():
    scope = _scope()
    placement = _placement(scope)
    ensemble = AuthorizationSetV2.build(
        members=[_membre(scope)],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFESTE,
        release_scope_placement_digest=placement.digest(),
    )
    octets = ensemble.canonical_bytes()
    return octets, sha256(octets).hexdigest(), placement


def test_un_document_v2_est_accepte_avec_son_placement(materiel_v2) -> None:
    octets, empreinte, placement = materiel_v2
    mapping = build_authorization_mapping(
        authorization_set_bytes=octets,
        expected_authorization_set_digest=empreinte,
        authority_required_content_sha256=(CONTENU,),
        release_scope_placement_raw=placement.canonical_bytes(),
    )
    assert mapping.authorization_set_digest == empreinte


def test_un_document_v2_sans_placement_est_refuse(materiel_v2) -> None:
    """LE garde-fou. Sans placement, la V2 ne peut pas etre verifiee ; l accepter
    sur une comparaison par contenu donnerait un accord qui ne prouve rien."""
    octets, empreinte, _place = materiel_v2
    with pytest.raises(AuthorizationMappingError, match="exige le placement"):
        build_authorization_mapping(
            authorization_set_bytes=octets,
            expected_authorization_set_digest=empreinte,
            authority_required_content_sha256=(CONTENU,),
        )


def test_un_document_v2_avec_le_MAUVAIS_placement_est_refuse(materiel_v2) -> None:
    octets, empreinte, _place = materiel_v2
    autre_scope = _scope("maths_seconde", "seconde")
    with pytest.raises(AuthorizationMappingError):
        build_authorization_mapping(
            authorization_set_bytes=octets,
            expected_authorization_set_digest=empreinte,
            authority_required_content_sha256=(CONTENU,),
            release_scope_placement_raw=_placement(autre_scope).canonical_bytes(),
        )


def test_un_document_v1_reste_verifie_comme_avant() -> None:
    """La migration elargit ce qui est accepte ; elle ne change rien a la V1."""
    scope = _scope()
    ensemble = AuthorizationSetV1.build(
        members=[_membre(scope)],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFESTE,
        release_scope_placement_digest="e" * 64,
        authority_required_content_sha256=(CONTENU,),
    )
    octets = ensemble.canonical_bytes()
    mapping = build_authorization_mapping(
        authorization_set_bytes=octets,
        expected_authorization_set_digest=sha256(octets).hexdigest(),
        authority_required_content_sha256=(CONTENU,),
    )
    assert mapping.authority_required_count == 1


def test_un_document_v1_avec_une_liste_requise_fausse_est_toujours_refuse() -> None:
    scope = _scope()
    ensemble = AuthorizationSetV1.build(
        members=[_membre(scope)],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFESTE,
        release_scope_placement_digest="e" * 64,
        authority_required_content_sha256=(CONTENU,),
    )
    octets = ensemble.canonical_bytes()
    with pytest.raises(AuthorizationMappingError):
        build_authorization_mapping(
            authorization_set_bytes=octets,
            expected_authorization_set_digest=sha256(octets).hexdigest(),
            authority_required_content_sha256=("2" * 64,),
        )
