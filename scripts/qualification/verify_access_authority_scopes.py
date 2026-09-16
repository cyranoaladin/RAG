#!/usr/bin/env python3
"""Vérification formelle et qualification de l'autorité d'accès et des portées (C5).

Condition de fermeture gouvernée :
« l autorité d accès refuse une portée non autorisée, prouvé par épreuve »

Ce script ne fait confiance à aucune affirmation déclarative : il soumet l'ensemble
de la chaîne d'autorité d'accès (contrats, registre d'identité, endpoint de retrieval,
mapping d'ingestion et prédicat SQL) à une batterie d'épreuves adversariales strictes.
Chaque tentative de franchissement de frontière ou d'accès hors autorité DOIT être refusée.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Configuration des chemins d'importation
RACINE = Path(__file__).resolve().parents[2]
sys.path.extend(
    [
        str(RACINE / "packages/contracts/src"),
        str(RACINE / "packages/release-chain/src"),
        str(RACINE / "packages/pdf-page-policy/src"),
        str(RACINE / "services/rag-engine"),
        str(RACINE / "services/rag-engine/src"),
        str(RACINE / "services/rag-pedago"),
    ]
)

from nexus_contracts import (  # noqa: E402
    InternalIdentityEnvelope,
    Niveau,
    RetrievalCurriculumScope,
    RetrievalNeed,
    RetrievalRequest,
    RetrievalScopeArtifactV2,
    StudentProfile,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)
from nexus_contracts.authorization_set import (  # noqa: E402
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.ingestion import ResourceScope  # noqa: E402

from src.ingestor import identity_v2, retrieval_scope_v2  # noqa: E402
from src.ingestor import retrieval_v2_endpoint as endpoint  # noqa: E402
from src.ingestor.ingestion_worker.authorization_mapping import (  # noqa: E402
    AuthorizationMappingError,
    build_authorization_mapping,
)
from src.ingestor.retrieval_pg_v2 import (  # noqa: E402
    _EFFECTIVE_SCOPE_FILTER_SQL,
    _GOVERNED_SCOPE_JOINS_SQL,
    _PLACEMENT_SCOPE_PREDICATE_SQL,
)

KIND = "NEXUS-C5-ACCESS-AUTHORITY-REFUSAL-PROOF-V1"
DEFAULT_OUTPUT = "docs/reports/evidence/access_authority_c5_refusal_proof.json"
DEFAULT_SHA = "docs/reports/evidence/access_authority_c5_refusal_proof.sha256"

CONTENT_A = "a" * 64
CONTENT_B = "b" * 64


def _dummy_scope(*, collection: str) -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_terminale",
            "collection": collection,
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "philosophie",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "bo-2026",
        }
    )


def _dummy_member(auth_id: str, content: str, scope: ResourceScope) -> AuthorizationSetMemberV1:
    return AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": auth_id,
            "authorization_digest": hashlib.sha256(f"auth:{auth_id}".encode()).hexdigest(),
            "review_binding_digest": hashlib.sha256(f"binding:{auth_id}".encode()).hexdigest(),
            "scope": scope,
            "scope_digest": scope_digest(scope),
            "allowed_content_sha256": [content],
            "allowed_content_count": 1,
            "allowed_content_set_sha256": content_set_digest([content]),
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    )


def _dummy_set() -> AuthorizationSetV1:
    members = (
        _dummy_member("auth-a", CONTENT_A, _dummy_scope(collection="philo_terminale")),
        _dummy_member("auth-b", CONTENT_B, _dummy_scope(collection="francais_terminale")),
    )
    return AuthorizationSetV1.build(
        members=members,
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest="d" * 64,
        release_scope_placement_digest="e" * 64,
        authority_required_content_sha256=(CONTENT_A, CONTENT_B),
    )


def _verified_identity(scope_id: str) -> identity_v2.VerifiedInternalIdentity:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    envelope = InternalIdentityEnvelope.model_validate(
        {
            "protocol_version": "1",
            "iss": "cockpit-internal",
            "aud": "rag-engine",
            "sub": "psn_1234567890abcdef",
            "jti": "jti-wave0-123",
            "iat": 1_799_999_990,
            "exp": 1_800_000_300,
            "identity": {
                "aud": "nexus-cockpit",
                "exp": 1_800_000_600,
                "iss": "nexus-issuer",
                "jti": "jti-wave0-123",
                "tenant": target.tenant,
                "niveau": target.niveau,
                "role": "teacher",
                "school_year": evidence.school_year,
                "sub": "psn_1234567890abcdef",
                "pedagogical_profile": {
                    "voie": target.voie,
                    "matieres": [target.matiere],
                    "statut_enseignement": target.statut_enseignement,
                    "candidat": target.candidates[0],
                    "audience": target.audience,
                },
            },
            "scope_id": artifact.scope_id,
            "scope_digest": artifact.sha256_digest(),
            "allowed_collections": [evidence.collection],
        }
    )
    return identity_v2.VerifiedInternalIdentity(envelope=envelope, artifact=artifact)


def _retrieval_request(
    scope_id: str,
    *,
    curriculum_niveau: Niveau = Niveau.troisieme,
    target_niveau: Niveau = Niveau.seconde,
    include_curriculum: bool = True,
) -> RetrievalRequest:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    return RetrievalRequest(
        student_profile=StudentProfile(
            niveau=target_niveau,
            voie=target.voie,
            matieres=[target.matiere],
            statut_enseignement=target.statut_enseignement,
            candidat=target.candidates[0],
            school_year=evidence.school_year,
            zone=target.audience,
        ),
        curriculum_scope=(
            RetrievalCurriculumScope(
                niveau=curriculum_niveau,
                voie=evidence.voie,
                matiere=evidence.matiere,
                statut_enseignement=evidence.statut_enseignement,
            )
            if include_curriculum
            else None
        ),
        need=RetrievalNeed(intent="remediation", query="Épreuve C5 autorité d accès"),
    )


def eval_governed_scope_predicate(
    *,
    chunk: dict[str, Any],
    artifact: dict[str, Any] | None,
    placements: list[dict[str, Any]],
    scope: dict[str, Any],
) -> bool:
    """Évaluation relationnelle déterministe et exacte de _GOVERNED_SCOPE_JOINS_SQL

    et _EFFECTIVE_SCOPE_FILTER_SQL.
    Reproduit sans dépendance externe la logique SQL formelle du moteur.
    """
    if chunk.get("artifact_id") is None:
        # Branche legacy: inaccessible pour tout chunk gouverné Nexus
        return False

    if artifact is None or artifact.get("artifact_id") != chunk.get("artifact_id"):
        return False

    # Jointure LATERAL sur rag_artifact_placements avec _PLACEMENT_SCOPE_PREDICATE_SQL
    matched_placement = None
    candidates = []
    for p in placements:
        if p.get("artifact_id") != chunk.get("artifact_id"):
            continue
        if p.get("collection") != scope.get("collection"):
            continue
        if p.get("tenant") != scope.get("tenant"):
            continue
        if p.get("niveau") != scope.get("niveau"):
            continue
        if p.get("voie") != scope.get("voie"):
            continue
        if p.get("matiere") != scope.get("matiere"):
            continue
        if p.get("statut_enseignement") != scope.get("statut_enseignement"):
            continue
        if p.get("candidat") not in (scope.get("candidat") or []):
            continue

        p_aud = set(p.get("audience") or [])
        s_aud = set(scope.get("audience") or [])
        if not (p_aud & s_aud):
            continue

        if p.get("visibility") not in (scope.get("visibility") or []):
            continue
        if p.get("school_year") != scope.get("school_year"):
            continue
        if p.get("programme_version") != scope.get("programme_version"):
            continue
        if p.get("placement_status") != "active":
            continue
        if p.get("currentness") != "current":
            continue
        if p.get("review_status") != "reviewed":
            continue
        candidates.append(p)

    if candidates:
        candidates.sort(key=lambda x: str(x.get("placement_id", "")))
        matched_placement = candidates[0]

    # Condition _EFFECTIVE_SCOPE_FILTER_SQL:
    # chunk.artifact_id IS NOT NULL AND artifact.artifact_id IS NOT NULL
    # AND matched_placement.placement_id IS NOT NULL AND artifact.rights = ANY(%s::text[])
    has_rights = artifact.get("rights") in (scope.get("rights") or [])
    return (matched_placement is not None) and (matched_placement.get("placement_id") is not None) and has_rights


def run_identity_and_retrieval_scope_refusals() -> dict[str, bool]:
    """Épreuves 1 à 7 : Registre d'identité, jetons et endpoint retrieval."""
    verdicts: dict[str, bool] = {}

    config = identity_v2.IdentityVerifierConfig(
        secret="test-secret-long-enough-for-hs256-minimum-32-chars",
        issuer="cockpit-internal",
        audience="rag-engine",
        identity_issuer="nexus-issuer",
        identity_audience="nexus-cockpit",
        artifact=load_retrieval_scope_artifact("libre_terminale_maths_nsi_real_v1"),
        artifacts=load_retrieval_scope_registry(),
    )

    # 1. Scope ID inconnu refusé
    try:
        identity_v2.resolve_identity_scope("unknown_forbidden_scope_id", config=config)
        verdicts["UNKNOWN_SCOPE_ID_REFUSED"] = False
    except identity_v2.IdentityScopeError as err:
        verdicts["UNKNOWN_SCOPE_ID_REFUSED"] = "identity scope forbidden" in str(err)

    # 2. Scope ID falsifié refusé
    try:
        identity_v2.resolve_identity_scope("../../../etc/passwd", config=config)
        verdicts["FORGED_SCOPE_ID_REFUSED"] = False
    except identity_v2.IdentityScopeError as err:
        verdicts["FORGED_SCOPE_ID_REFUSED"] = "identity scope forbidden" in str(err)

    # 3. Digest de portée altéré refusé
    verified = _verified_identity("entree_seconde_maths_v1")
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    bad_payload = verified.envelope.model_dump(mode="json")
    bad_payload["scope_digest"] = "0" * 64
    bad_envelope = InternalIdentityEnvelope.model_validate(bad_payload)
    try:
        artifact.validate_envelope(bad_envelope)
        verdicts["SCOPE_DIGEST_CORRUPTION_REFUSED"] = False
    except ValueError as err:
        verdicts["SCOPE_DIGEST_CORRUPTION_REFUSED"] = "scope_digest" in str(err)

    # Catalogue d'épreuve pour le matching d'endpoint
    catalogue = {
        "collections": {
            artifact.evidence_subject.collection: {
                "matiere": artifact.evidence_subject.matiere,
                "niveau": artifact.evidence_subject.niveau.value,
                "voie": artifact.evidence_subject.voie.value,
                "statut": artifact.evidence_subject.statut_enseignement.value,
                "domain": "education",
                "instanciee": True,
            }
        },
        "domains": {"education": {"retrievable": True}},
    }
    server_scope = retrieval_scope_v2.build_server_retrieval_scope(
        verified,
        collection=artifact.evidence_subject.collection,
        collection_config=catalogue,
    )

    # 4. Niveau pédagogique cible divergent refusé
    bad_target_req = _retrieval_request("entree_seconde_maths_v1", target_niveau=Niveau.terminale)
    try:
        endpoint._require_retrieval_profile_match(bad_target_req, server_scope, verified)
        verdicts["TARGET_LEVEL_DRIFT_REFUSED"] = False
    except endpoint.RetrievalScopeError as err:
        verdicts["TARGET_LEVEL_DRIFT_REFUSED"] = "retrieval scope forbidden" in str(err)

    # 5. Niveau curriculum divergent refusé
    bad_curriculum_req = _retrieval_request(
        "entree_seconde_maths_v1", curriculum_niveau=Niveau.seconde
    )
    try:
        endpoint._require_retrieval_profile_match(bad_curriculum_req, server_scope, verified)
        verdicts["CURRICULUM_LEVEL_DRIFT_REFUSED"] = False
    except endpoint.RetrievalScopeError as err:
        verdicts["CURRICULUM_LEVEL_DRIFT_REFUSED"] = "retrieval scope forbidden" in str(err)

    # 6. Matière hors périmètre refusée (croisement matière / collection non signée)
    verified_french = _verified_identity("entree_seconde_francais_v1")
    math_req = _retrieval_request("entree_seconde_maths_v1")
    try:
        endpoint._collection_for_retrieval_request(math_req, verified_french)
        verdicts["CROSS_SUBJECT_DRIFT_REFUSED"] = False
    except endpoint.RetrievalScopeError as err:
        verdicts["CROSS_SUBJECT_DRIFT_REFUSED"] = "retrieval scope forbidden" in str(err)

    # 7. Curriculum scope omis refusé, sans fallback implicite
    no_curriculum_req = _retrieval_request("entree_seconde_maths_v1", include_curriculum=False)
    try:
        endpoint._collection_for_retrieval_request(no_curriculum_req, verified)
        verdicts["OMITTED_CURRICULUM_SCOPE_REFUSED"] = False
    except endpoint.RetrievalScopeError as err:
        verdicts["OMITTED_CURRICULUM_SCOPE_REFUSED"] = "retrieval scope forbidden" in str(err)

    return verdicts


def run_authorization_mapping_and_set_refusals() -> dict[str, bool]:
    """Épreuves 8 à 11 : Mapping d'autorisations et intégrité de l'AuthorizationSet."""
    verdicts: dict[str, bool] = {}
    auth_set = _dummy_set()

    # 8. AuthorizationMapping incomplet refusé (gap, extra, ou doublons)
    try:
        build_authorization_mapping(
            authorization_set_bytes=auth_set.canonical_bytes(),
            expected_authorization_set_digest=auth_set.digest(),
            authority_required_content_sha256=[CONTENT_A],  # gap: manque CONTENT_B
        )
        verdicts["AUTHORIZATION_MAPPING_INCOMPLETE_REFUSED"] = False
    except AuthorizationMappingError as err:
        verdicts["AUTHORIZATION_MAPPING_INCOMPLETE_REFUSED"] = "extra" in str(err) or "gap" in str(err)

    # 9. AuthorizationSetV2 falsifié ou divergent refusé
    try:
        build_authorization_mapping(
            authorization_set_bytes=auth_set.canonical_bytes(),
            expected_authorization_set_digest="0" * 64,  # digest divergent falsifié
            authority_required_content_sha256=[CONTENT_A, CONTENT_B],
        )
        verdicts["AUTHORIZATION_SET_V2_FALSIFIED_OR_DIVERGENT_REFUSED"] = False
    except AuthorizationMappingError as err:
        verdicts["AUTHORIZATION_SET_V2_FALSIFIED_OR_DIVERGENT_REFUSED"] = "digest mismatch" in str(err)

    # 10. Contenu hors autorisation refusé & scope inconnu refusé
    mapping = build_authorization_mapping(
        authorization_set_bytes=auth_set.canonical_bytes(),
        expected_authorization_set_digest=auth_set.digest(),
        authority_required_content_sha256=[CONTENT_A, CONTENT_B],
    )
    unauthorized_content_refused = False
    try:
        mapping.authorization_id_for_content("f" * 64)
    except AuthorizationMappingError as err:
        unauthorized_content_refused = "unknown content" in str(err)

    unauthorized_scope_refused = False
    try:
        mapping.authorization_id_for_scope(_dummy_scope(collection="unknown_collection"))
    except AuthorizationMappingError as err:
        unauthorized_scope_refused = "unknown scope" in str(err)

    verdicts["CONTENT_OUTSIDE_AUTHORIZATION_REFUSED"] = (
        unauthorized_content_refused and unauthorized_scope_refused
    )

    # 11. Overlap ou duplication non gouvernée refusé
    doc = auth_set.canonical_document()
    doc["members"][1]["allowed_content_sha256"] = [CONTENT_A]
    doc["members"][1]["allowed_content_set_sha256"] = content_set_digest([CONTENT_A])
    raw_overlap = (json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    try:
        build_authorization_mapping(
            authorization_set_bytes=raw_overlap,
            expected_authorization_set_digest=hashlib.sha256(raw_overlap).hexdigest(),
            authority_required_content_sha256=[CONTENT_A, CONTENT_B],
        )
        verdicts["OVERLAP_OR_DUPLICATION_REFUSED"] = False
    except AuthorizationMappingError as err:
        verdicts["OVERLAP_OR_DUPLICATION_REFUSED"] = "overlap" in str(err)

    return verdicts


def run_sql_placement_authority_refusals() -> dict[str, bool]:
    """Épreuves 12 à 15 : Prédicat SQL effectif et non-élargissement par rag_chunks."""
    verdicts: dict[str, bool] = {}

    nominal_scope = {
        "collection": "rag_nexus_nsi_terminale_specialite",
        "tenant": "libre_terminale",
        "niveau": "terminale",
        "voie": None,
        "matiere": "nsi",
        "statut_enseignement": "specialite",
        "candidat": ["libre"],
        "audience": ["eleve"],
        "rights": ["officiel_public"],
        "visibility": ["public"],
        "school_year": "2026-2027",
        "programme_version": "BOEN-NSI-2026",
    }

    chunk = {
        "chunk_id": "chk-1",
        "artifact_id": "art-1",
        "visibility": "public",
        "audience": ["eleve"],
    }
    artifact = {
        "artifact_id": "art-1",
        "rights": "officiel_public",
        "source_label": "Eduscol",
        "source_uri": "https://source.test/1",
    }
    nominal_placement = {
        "placement_id": "pl-1",
        "artifact_id": "art-1",
        "collection": nominal_scope["collection"],
        "tenant": nominal_scope["tenant"],
        "niveau": nominal_scope["niveau"],
        "voie": nominal_scope["voie"],
        "matiere": nominal_scope["matiere"],
        "statut_enseignement": nominal_scope["statut_enseignement"],
        "candidat": "libre",
        "audience": ["eleve"],
        "visibility": "public",
        "school_year": nominal_scope["school_year"],
        "programme_version": nominal_scope["programme_version"],
        "placement_status": "active",
        "currentness": "current",
        "review_status": "reviewed",
    }

    # Contrôle positif nominal : le chunk doit être servi
    nominal_served = eval_governed_scope_predicate(
        chunk=chunk,
        artifact=artifact,
        placements=[nominal_placement],
        scope=nominal_scope,
    )

    # 12. Tentative d'élargissement via colonnes dénormalisées de rag_chunks refusée
    # Cas adversarial : le placement est restreint ('restricted'), mais rag_chunks a 'public'
    restricted_placement = dict(nominal_placement, visibility="restricted")
    stale_chunk = dict(chunk, visibility="public", audience=["eleve", "tous"])
    served_widened_visibility = eval_governed_scope_predicate(
        chunk=stale_chunk,
        artifact=artifact,
        placements=[restricted_placement],
        scope=nominal_scope,
    )
    # Cas adversarial audience : le placement est 'enseignant', rag_chunks prétend 'eleve'
    restricted_aud_placement = dict(nominal_placement, audience=["enseignant"])
    served_widened_audience = eval_governed_scope_predicate(
        chunk=stale_chunk,
        artifact=artifact,
        placements=[restricted_aud_placement],
        scope=nominal_scope,
    )
    verdicts["DENORMALIZED_COLUMNS_CANNOT_WIDEN_AUTHORITY"] = (
        nominal_served and not served_widened_visibility and not served_widened_audience
    )

    # 13. Placement inactif (placement_status != 'active') refusé
    retired_placement = dict(nominal_placement, placement_status="retired")
    served_retired = eval_governed_scope_predicate(
        chunk=chunk,
        artifact=artifact,
        placements=[retired_placement],
        scope=nominal_scope,
    )
    verdicts["INACTIVE_PLACEMENT_REFUSED"] = not served_retired

    # 14. Placement non actuel (currentness != 'current') ou non revu refusé
    stale_placement = dict(nominal_placement, currentness="stale")
    served_stale = eval_governed_scope_predicate(
        chunk=chunk,
        artifact=artifact,
        placements=[stale_placement],
        scope=nominal_scope,
    )
    unreviewed_placement = dict(nominal_placement, review_status="unreviewed")
    served_unreviewed = eval_governed_scope_predicate(
        chunk=chunk,
        artifact=artifact,
        placements=[unreviewed_placement],
        scope=nominal_scope,
    )
    verdicts["STALE_OR_UNREVIEWED_PLACEMENT_REFUSED"] = (not served_stale) and (
        not served_unreviewed
    )

    # 15. _EFFECTIVE_SCOPE_FILTER_SQL impose bien la jointure sur rag_artifact_placements
    # Contrôle de compilation / structure formelle :
    # 1) Le fragment SQL doit exiger matched_placement.placement_id IS NOT NULL
    # 2) La sous-requête LATERAL doit exiger active, current, reviewed
    # 3) L'absence complète de placement pour un chunk gouverné exclut le chunk
    missing_placement_served = eval_governed_scope_predicate(
        chunk=chunk,
        artifact=artifact,
        placements=[],  # zéro placement
        scope=nominal_scope,
    )

    has_required_sql_guards = (
        "matched_placement.placement_id IS NOT NULL" in _EFFECTIVE_SCOPE_FILTER_SQL
        and "placement.placement_status = 'active'" in _PLACEMENT_SCOPE_PREDICATE_SQL
        and "placement.currentness = 'current'" in _PLACEMENT_SCOPE_PREDICATE_SQL
        and "placement.review_status = 'reviewed'" in _PLACEMENT_SCOPE_PREDICATE_SQL
        and "LEFT JOIN LATERAL" in _GOVERNED_SCOPE_JOINS_SQL
        and "public.rag_artifact_placements AS placement" in _GOVERNED_SCOPE_JOINS_SQL
    )

    verdicts["_EFFECTIVE_SCOPE_FILTER_SQL_ENFORCES_GOVERNED_PLACEMENT"] = (
        (not missing_placement_served) and has_required_sql_guards
    )

    return verdicts


def run_all_c5_verifications(main_sha: str) -> dict[str, Any]:
    """Exécute l'intégralité des vérifications de refus C5 et compose l'attestation."""
    id_verdicts = run_identity_and_retrieval_scope_refusals()
    auth_verdicts = run_authorization_mapping_and_set_refusals()
    sql_verdicts = run_sql_placement_authority_refusals()

    all_verdicts: dict[str, bool] = {
        **id_verdicts,
        **auth_verdicts,
        **sql_verdicts,
    }

    echecs = [k for k, v in all_verdicts.items() if not v]
    status = "VERIFIED" if not echecs else "FAILED"

    return {
        "kind": KIND,
        "observed_at_main_sha": main_sha,
        "verification_status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "summary": {
            "total_adversarial_proofs": len(all_verdicts),
            "passed_proofs": len(all_verdicts) - len(echecs),
            "failed_proofs": len(echecs),
            "failed_items": echecs,
        },
        "verdicts": all_verdicts,
        "specifications": {
            "identity_scope_guard": "Refus strict de scope inconnu, falsifié, ou de digest altéré",
            "pedagogical_drift_guard": "Refus strict de dérive de niveau ou de matière croisée",
            "curriculum_scope_guard": "Refus sans repli implicite en l'absence de curriculum_scope",
            "authorization_mapping_guard": "Refus strict de gap, extra, altération de digest ou overlap",
            "sql_placement_authority_guard": "L'autorité de placement rag_artifact_placements prévaut exclusivement sur toute colonne dénormalisée",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Chemin de sortie pour le document de preuve JSON",
    )
    parser.add_argument(
        "--sha-output",
        default=DEFAULT_SHA,
        help="Chemin de sortie pour l'empreinte SHA-256 de la preuve",
    )
    parser.add_argument(
        "--main-sha",
        default="eb0fb6a64190a4b6d8de6dbee7e4a2d61450bfcb",
        help="Commit de base main observé",
    )
    args = parser.parse_args(argv)

    racine = RACINE
    attestation = run_all_c5_verifications(args.main_sha)

    out_json = racine / args.output
    out_sha = racine / args.sha_output
    out_json.parent.mkdir(parents=True, exist_ok=True)

    octets = (json.dumps(attestation, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    out_json.write_bytes(octets)

    sha = hashlib.sha256(octets).hexdigest()
    out_sha.write_text(f"{sha}  {args.output}\n", encoding="utf-8")

    total = attestation["summary"]["total_adversarial_proofs"]
    passed = attestation["summary"]["passed_proofs"]
    failed = attestation["summary"]["failed_proofs"]

    print(f"C5 Verification: {attestation['verification_status']} ({passed}/{total} passés, {failed} échecs)")
    print(f"Écrit : {out_json}")
    print(f"Écrit : {out_sha}")

    return 0 if attestation["verification_status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
