"""Tests unitaires du harnais de qualification C5 (autorité d'accès et portées)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[4]

sys.path.extend(
    [
        str(RACINE / "packages/contracts/src"),
        str(RACINE / "packages/release-chain/src"),
        str(RACINE / "packages/pdf-page-policy/src"),
        str(RACINE / "services/rag-engine"),
        str(RACINE / "services/rag-engine/src"),
        str(RACINE / "services/rag-pedago"),
        str(RACINE / "scripts/qualification"),
    ]
)

import verify_access_authority_scopes as c5_verifier  # noqa: E402


def test_nominal_evaluation_passes() -> None:
    chunk = {"chunk_id": "c-1", "artifact_id": "a-1", "visibility": "public", "audience": ["eleve"]}
    artifact = {"artifact_id": "a-1", "rights": "officiel_public"}
    scope = {
        "collection": "col-1",
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
        "programme_version": "BOEN-2026",
    }
    placement = {
        "placement_id": "p-1",
        "artifact_id": "a-1",
        "collection": "col-1",
        "tenant": "libre_terminale",
        "niveau": "terminale",
        "voie": None,
        "matiere": "nsi",
        "statut_enseignement": "specialite",
        "candidat": "libre",
        "audience": ["eleve"],
        "visibility": "public",
        "school_year": "2026-2027",
        "programme_version": "BOEN-2026",
        "placement_status": "active",
        "currentness": "current",
        "review_status": "reviewed",
    }

    assert c5_verifier.eval_governed_scope_predicate(
        chunk=chunk,
        artifact=artifact,
        placements=[placement],
        scope=scope,
    ) is True


def test_denormalized_chunk_column_cannot_widen_restricted_placement() -> None:
    chunk = {"chunk_id": "c-1", "artifact_id": "a-1", "visibility": "public", "audience": ["eleve", "tous"]}
    artifact = {"artifact_id": "a-1", "rights": "officiel_public"}
    scope = {
        "collection": "col-1",
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
        "programme_version": "BOEN-2026",
    }
    # Placement est restricted
    placement = {
        "placement_id": "p-1",
        "artifact_id": "a-1",
        "collection": "col-1",
        "tenant": "libre_terminale",
        "niveau": "terminale",
        "voie": None,
        "matiere": "nsi",
        "statut_enseignement": "specialite",
        "candidat": "libre",
        "audience": ["eleve"],
        "visibility": "restricted",  # Ne correspond pas à scope['visibility'] = ['public']
        "school_year": "2026-2027",
        "programme_version": "BOEN-2026",
        "placement_status": "active",
        "currentness": "current",
        "review_status": "reviewed",
    }

    assert c5_verifier.eval_governed_scope_predicate(
        chunk=chunk,
        artifact=artifact,
        placements=[placement],
        scope=scope,
    ) is False


def test_inactive_or_stale_placement_cannot_serve() -> None:
    chunk = {"chunk_id": "c-1", "artifact_id": "a-1", "visibility": "public", "audience": ["eleve"]}
    artifact = {"artifact_id": "a-1", "rights": "officiel_public"}
    scope = {
        "collection": "col-1",
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
        "programme_version": "BOEN-2026",
    }
    placement_base = {
        "placement_id": "p-1",
        "artifact_id": "a-1",
        "collection": "col-1",
        "tenant": "libre_terminale",
        "niveau": "terminale",
        "voie": None,
        "matiere": "nsi",
        "statut_enseignement": "specialite",
        "candidat": "libre",
        "audience": ["eleve"],
        "visibility": "public",
        "school_year": "2026-2027",
        "programme_version": "BOEN-2026",
        "placement_status": "active",
        "currentness": "current",
        "review_status": "reviewed",
    }

    # Inactive
    p_inactive = dict(placement_base, placement_status="retired")
    assert c5_verifier.eval_governed_scope_predicate(
        chunk=chunk, artifact=artifact, placements=[p_inactive], scope=scope
    ) is False

    # Stale
    p_stale = dict(placement_base, currentness="stale")
    assert c5_verifier.eval_governed_scope_predicate(
        chunk=chunk, artifact=artifact, placements=[p_stale], scope=scope
    ) is False

    # Unreviewed
    p_unreviewed = dict(placement_base, review_status="unreviewed")
    assert c5_verifier.eval_governed_scope_predicate(
        chunk=chunk, artifact=artifact, placements=[p_unreviewed], scope=scope
    ) is False


def test_evidence_file_integrity_and_all_verdicts_true() -> None:
    evidence_path = RACINE / c5_verifier.DEFAULT_OUTPUT
    sha_path = RACINE / c5_verifier.DEFAULT_SHA

    assert evidence_path.is_file(), f"Fichier de preuve absent: {evidence_path}"
    assert sha_path.is_file(), f"Fichier sha absent: {sha_path}"

    octets = evidence_path.read_bytes()
    sha_reel = hashlib.sha256(octets).hexdigest()

    sha_line = sha_path.read_text(encoding="utf-8").strip()
    sha_attendu = sha_line.split()[0]
    assert sha_reel == sha_attendu, f"Empreinte altérée: {sha_reel} != {sha_attendu}"

    data = json.loads(octets.decode("utf-8"))
    assert data["kind"] == c5_verifier.KIND
    assert data["verification_status"] == "VERIFIED"
    assert data["summary"]["failed_proofs"] == 0
    assert data["summary"]["passed_proofs"] >= 15

    for k, v in data["verdicts"].items():
        assert v is True, f"Verdict C5 non vérifié: {k} = {v}"
