"""Les dimensions actualité et PII de la projection batch (ADR-0059).

La projection ne lit plus de déclaration brute : elle reçoit ce que les
chargeurs canoniques ont vérifié — la disposition d'actualité chargée par
``load_multilevel_currentness``, la clairance PII rendue par
``VerifiedPIIEvidenceRegistry``. Ces épreuves fixent ce qu'elle en fait.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ingestor.ingestion_control.sealed_evidence import (
    PIIClearance,
    SealedEvidenceError,
)
from ingestor.ingestion_control.sealed_release_projection import (
    DERIVATION,
    EVALUATION,
    NON_ETABLI,
    DimensionProjetee,
    ProjectionRow,
    derive_currentness,
    derive_pii,
)
from ingestor.multilevel_evidence import MultilevelCurrentnessArtifact

SHA = "a" * 64
EVIDENCE = "b" * 64
PII_EVIDENCE = "c" * 64


def _actualite(disposition: str, decision: str | None = None) -> MultilevelCurrentnessArtifact:
    return MultilevelCurrentnessArtifact(
        content_sha256=SHA,
        exact_path="01_EDUSCOL_OFFICIEL/doc.pdf",
        collections=frozenset({"rag_nexus_svt_terminale_specialite"}),
        decision=decision or disposition,
        effective_currentness="actuel" if disposition == "VERIFIED_CURRENT" else None,
        current_for_school_year="2026-2027",
        current_source_listing_url=None,
        current_download_url=None,
        disposition=disposition,
    )


def _ligne(actualite: DimensionProjetee, pii: DimensionProjetee) -> ProjectionRow:
    etablie = DimensionProjetee(valeur=True, origine=DERIVATION, source="t", digest=SHA)
    return ProjectionRow(
        resource_id=uuid4(),
        artifact_id=uuid4(),
        content_sha256=SHA,
        collection="rag_nexus_svt_terminale_specialite",
        scope_authorization_id="lot41a-staging-v2-svt-terminale-specialite",
        droits=DimensionProjetee(
            valeur="official_public", origine=DERIVATION, source="r", digest=SHA
        ),
        qualite=etablie,
        actualite=actualite,
        pii=pii,
        gate_evaluator="test",
        gate_evaluated_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


# --- actualité ------------------------------------------------------------


def test_un_instantane_officiel_se_projette_comme_tel() -> None:
    dimension = derive_currentness(
        _actualite("OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"), evidence_sha256=EVIDENCE
    )
    assert dimension.valeur == "official_snapshot"
    assert dimension.origine == DERIVATION
    assert "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE" in dimension.source
    # La preuve qui fonde la dimension est nommée par son empreinte.
    assert dimension.digest == EVIDENCE


def test_une_identite_d_octets_prouvee_se_projette_current() -> None:
    dimension = derive_currentness(_actualite("VERIFIED_CURRENT"), evidence_sha256=EVIDENCE)
    assert dimension.valeur == "current"
    assert dimension.origine == DERIVATION


@pytest.mark.parametrize(
    ("disposition", "decision"),
    [
        ("UNKNOWN", "REVIEW_REQUIRED"),
        ("UNKNOWN", "UNKNOWN"),
        ("NOT_CURRENT_DECLARED_BY_SOURCE", None),
    ],
)
def test_une_disposition_non_publiable_est_une_evaluation_negative(
    disposition: str, decision: str | None
) -> None:
    dimension = derive_currentness(
        _actualite(disposition, decision), evidence_sha256=EVIDENCE
    )
    assert dimension.origine == EVALUATION
    assert dimension.valeur not in {"current", "official_snapshot"}


def test_une_actualite_absente_n_est_pas_etablie() -> None:
    dimension = derive_currentness(None, evidence_sha256=EVIDENCE)
    assert dimension.origine == NON_ETABLI


# --- PII ------------------------------------------------------------------


def _clairance(status: str, decision_set_id: str | None = None) -> PIIClearance:
    return PIIClearance(
        content_sha256=SHA,
        pages_scanned=3,
        characters_scanned=1000,
        evidence_sha256=PII_EVIDENCE,
        status=status,
        review_status="APPROVED" if decision_set_id else None,
        decision_set_id=decision_set_id,
    )


def test_un_contenu_sans_signal_se_projette_cleared() -> None:
    dimension = derive_pii(_clairance("CLEARED"), evidence_sha256=PII_EVIDENCE)
    assert (dimension.valeur, dimension.origine) == ("CLEARED", DERIVATION)


def test_une_detection_revue_et_admise_reste_une_detection() -> None:
    """Une admission n'efface jamais la détection (ADR-0047)."""
    dimension = derive_pii(
        _clairance("DETECTED_REVIEWED_ACCEPTED", "pii-review-2026-09-03-final"),
        evidence_sha256=PII_EVIDENCE,
    )
    assert dimension.valeur == "DETECTED_REVIEWED_ACCEPTED"
    assert dimension.origine == DERIVATION
    assert "pii-review-2026-09-03-final" in dimension.source
    assert dimension.digest == PII_EVIDENCE


def test_une_admission_sans_decision_nommee_n_est_pas_une_derivation() -> None:
    dimension = derive_pii(
        _clairance("DETECTED_REVIEWED_ACCEPTED"), evidence_sha256=PII_EVIDENCE
    )
    assert dimension.origine == EVALUATION


def test_un_refus_du_chargeur_pii_est_une_evaluation_negative() -> None:
    dimension = derive_pii(
        SealedEvidenceError("content … is 'DETECTED_RECORDED'"),
        evidence_sha256=PII_EVIDENCE,
    )
    assert dimension.origine == EVALUATION
    assert dimension.valeur == "REFUSED"


def test_une_pii_absente_n_est_pas_etablie() -> None:
    assert derive_pii(None, evidence_sha256=PII_EVIDENCE).origine == NON_ETABLI


# --- la porte ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("disposition", "status", "decision_set_id"),
    [
        ("VERIFIED_CURRENT", "CLEARED", None),
        ("OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE", "CLEARED", None),
        (
            "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE",
            "DETECTED_REVIEWED_ACCEPTED",
            "pii-review-2026-09-03-final",
        ),
    ],
)
def test_la_porte_s_ouvre_sur_les_etats_publiables(
    disposition: str, status: str, decision_set_id: str | None
) -> None:
    ligne = _ligne(
        derive_currentness(_actualite(disposition), evidence_sha256=EVIDENCE),
        derive_pii(_clairance(status, decision_set_id), evidence_sha256=PII_EVIDENCE),
    )
    assert ligne.gate_passed is True


@pytest.mark.parametrize(
    ("actualite", "pii"),
    [
        (
            DimensionProjetee(valeur="UNKNOWN", origine=EVALUATION, source="t"),
            DimensionProjetee(valeur="CLEARED", origine=DERIVATION, source="t"),
        ),
        (
            DimensionProjetee(valeur="official_snapshot", origine=DERIVATION, source="t"),
            DimensionProjetee(valeur="REFUSED", origine=EVALUATION, source="t"),
        ),
        (
            DimensionProjetee(valeur="official_snapshot", origine=DERIVATION, source="t"),
            DimensionProjetee(valeur="DETECTED_RECORDED", origine=EVALUATION, source="t"),
        ),
        (
            DimensionProjetee(valeur="archive", origine=EVALUATION, source="t"),
            DimensionProjetee(valeur="CLEARED", origine=DERIVATION, source="t"),
        ),
    ],
)
def test_la_porte_reste_fermee_sur_tout_autre_etat(
    actualite: DimensionProjetee, pii: DimensionProjetee
) -> None:
    assert _ligne(actualite, pii).gate_passed is False


def test_une_valeur_publiable_d_origine_non_derivee_ne_passe_pas() -> None:
    """Une valeur n'autorise que si elle a été dérivée par le chargeur."""
    ligne = _ligne(
        DimensionProjetee(valeur="official_snapshot", origine=EVALUATION, source="t"),
        DimensionProjetee(valeur="CLEARED", origine=DERIVATION, source="t"),
    )
    assert ligne.gate_passed is False
