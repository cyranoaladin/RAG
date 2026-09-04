"""Projection du decision set scellé sur le scan du corpus (ADR-0047, §2-§8).

**Le producteur ne décide rien.** Il lit un scan, un ensemble de décisions
humaines scellé, et l'index des paquets qui ont fondé ces décisions ; puis il
projette honnêtement leur résultat. Toute la difficulté est de refuser lorsque
ces trois sources ne parlent pas du même monde.

Le raisonnement est un raisonnement d'ENSEMBLES, jamais de comptes :

    C = contenus du corpus candidat
    D = contenus où le scan courant trouve au moins une correspondance
    A = contenus APPROVED du decision set
    R = contenus REJECTED du decision set

    A ∩ R = ∅        A ∪ R = D        A ⊆ C    R ⊆ C    D ⊆ C

    CLEARED = C - D          AUTHORIZED = CLEARED ∪ A

Les comptes (297, 23, 320) ne sont que des vérifications a posteriori : aucun
n'est écrit dans le code, et un test le prouve.
"""
from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from rag_pedago.imports.pii_review_projection import (
    PiiProjectionError,
    ScannedContent,
    ScannedFinding,
    project_pii_review,
)

MANIFEST_SHA = "0" * 64
POLICY_SHA = "d" * 64
SCANNER_SHA = "e" * 64
PAGE_POLICY_SHA = "f" * 64
DECISION_SET_ID = "pii-review-test-projection-v1"

CLEAN_A = "1" * 64
CLEAN_B = "2" * 64
DETECTED = "3" * 64
BUNDLE = "4" * 64


def _finding(seed: str, page: int = 1, pattern: str = "phone_french") -> ScannedFinding:
    return ScannedFinding(
        finding_id=sha256(seed.encode()).hexdigest(),
        pattern_id=pattern,
        page=page,
        match_sha256=sha256((seed + ":m").encode()).hexdigest(),
        context_sha256=sha256((seed + ":c").encode()).hexdigest(),
    )


FINDING_1 = _finding("f1", page=1)
FINDING_2 = _finding("f2", page=4)


def _scanned(sha: str, findings: tuple[ScannedFinding, ...] = ()) -> ScannedContent:
    return ScannedContent(
        content_sha256=sha,
        pages_scanned=10,
        characters_scanned=1000,
        ignored_empty_pages=(),
        findings=findings,
    )


def _decision(
    sha: str = DETECTED,
    *,
    decision: str = "APPROVED",
    findings: tuple[ScannedFinding, ...] = (FINDING_1, FINDING_2),
    bundle: str = BUNDLE,
    dispositions: tuple[str, ...] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    if dispositions is None:
        dispositions = ("FALSE_POSITIVE_TECHNICAL",) * len(findings)
    payload: dict[str, Any] = {
        "content_sha256": sha,
        "policy_id": "pii_gate_policy",
        "policy_sha256": POLICY_SHA,
        "scanner_sha256": SCANNER_SHA,
        "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
        "page_policy_sha256": PAGE_POLICY_SHA,
        "review_bundle_sha256": bundle,
        "signal_classes": sorted({f.pattern_id for f in findings}),
        "signal_count": len(findings),
        "pages": sorted({f.page for f in findings}),
        "findings": sorted(
            (
                {
                    "finding_id": f.finding_id,
                    "pattern_id": f.pattern_id,
                    "page": f.page,
                    "match_sha256": f.match_sha256,
                    "context_sha256": f.context_sha256,
                    "disposition": d,
                }
                for f, d in zip(findings, dispositions, strict=True)
            ),
            key=lambda f: f["finding_id"],
        ),
        "decision": decision,
        "justification": {
            "category": "TECHNICAL_FALSE_POSITIVE"
            if decision == "APPROVED"
            else "PERSONAL_DATA_PRESENT",
            "statement": "Motif de revue suffisamment long pour le contrat de justification.",
            "raw_pii_quoted": False,
        },
        "reviewer_login": "abenrhouma",
        "decided_at": "2026-09-03T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def _decision_set(decisions: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol_version": "NEXUS-PII-REVIEW-DECISIONS-V1",
        "decision_set_id": DECISION_SET_ID,
        "corpus_manifest_sha256": "0" * 64,
        "policy_id": "pii_gate_policy",
        "policy_sha256": POLICY_SHA,
        "scanner_sha256": SCANNER_SHA,
        "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
        "page_policy_sha256": PAGE_POLICY_SHA,
        "review_index_sha256": "5" * 64,
        "decisions": sorted(
            decisions if decisions is not None else [_decision()],
            key=lambda d: d["content_sha256"],
        ),
    }
    payload.update(overrides)
    return payload


def _project(**overrides: Any):
    kwargs: dict[str, Any] = {
        "scanned": [
            _scanned(CLEAN_A),
            _scanned(CLEAN_B),
            _scanned(DETECTED, (FINDING_1, FINDING_2)),
        ],
        "decision_set_document": _decision_set(),
        "review_bundles": {DETECTED: BUNDLE},
        "policy_sha256": POLICY_SHA,
        "scanner_sha256": SCANNER_SHA,
        "page_policy_sha256": PAGE_POLICY_SHA,
        "corpus_manifest_sha256": MANIFEST_SHA,
    }
    kwargs.update(overrides)
    return project_pii_review(**kwargs)


# ─────────────────────────────────────────────────────────────────────────
# §2 — l'algèbre d'ensembles est l'autorité
# ─────────────────────────────────────────────────────────────────────────


class TestSetAlgebra:
    def test_sets_are_derived_from_the_evidence(self) -> None:
        p = _project()
        assert p.corpus == {CLEAN_A, CLEAN_B, DETECTED}
        assert p.detected == {DETECTED}
        assert p.approved == {DETECTED}
        assert p.rejected == frozenset()
        assert p.cleared == {CLEAN_A, CLEAN_B}
        assert p.reviewed_accepted == {DETECTED}
        assert p.authorized == {CLEAN_A, CLEAN_B, DETECTED}

    def test_the_invariants_hold_on_a_valid_projection(self) -> None:
        p = _project()
        assert p.approved & p.rejected == frozenset()
        assert p.approved | p.rejected == p.detected
        assert p.approved <= p.corpus
        assert p.rejected <= p.corpus
        assert p.detected <= p.corpus
        assert p.cleared == p.corpus - p.detected
        assert p.authorized == p.cleared | p.reviewed_accepted

    def test_a_corpus_with_no_detection_needs_no_decision_set(self) -> None:
        """Rien à décider : l'absence de decision set n'est alors pas un défaut."""
        p = _project(
            scanned=[_scanned(CLEAN_A), _scanned(CLEAN_B)],
            decision_set_document=None,
            review_bundles={},
        )
        assert p.cleared == {CLEAN_A, CLEAN_B}
        assert p.authorized == {CLEAN_A, CLEAN_B}
        assert p.detected == frozenset()


# ─────────────────────────────────────────────────────────────────────────
# §6 — la comptabilité, dérivée
# ─────────────────────────────────────────────────────────────────────────


class TestCounters:
    def test_every_counter_is_exposed_separately(self) -> None:
        counts = _project().counts
        assert counts == {
            "scanned_count": 3,
            "detected_count": 1,
            "cleared_count": 2,
            "reviewed_accepted_count": 1,
            "rejected_count": 0,
            "authorized_count": 3,
            "quarantined_count": 0,
        }

    def test_counters_follow_the_sets_not_a_constant(self) -> None:
        """Ajouter un contenu propre déplace les comptes sans toucher au code."""
        counts = _project(
            scanned=[
                _scanned(CLEAN_A), _scanned(CLEAN_B), _scanned("7" * 64),
                _scanned(DETECTED, (FINDING_1, FINDING_2)),
            ],
        ).counts
        assert counts["scanned_count"] == 4
        assert counts["cleared_count"] == 3
        assert counts["authorized_count"] == 4

    def test_no_business_constant_lives_in_the_module(self) -> None:
        """Ni 297, ni 23, ni 320 : la population vient des preuves.

        La garde inspecte les LITTÉRAUX de l'arbre syntaxique, pas le texte du
        fichier : la docstring du module cite ces nombres précisément pour
        expliquer pourquoi ils ne font pas autorité, et une garde qui
        interdirait d'en parler interdirait de l'écrire."""
        source = (
            Path(__file__).resolve().parents[1]
            / "rag_pedago" / "imports" / "pii_review_projection.py"
        ).read_text(encoding="utf-8")
        literals = {
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        assert literals & {297, 23, 320, 488, 486, 319} == set()


# ─────────────────────────────────────────────────────────────────────────
# §5 — la projection par contenu, sans effacer la détection
# ─────────────────────────────────────────────────────────────────────────


class TestProjectionPerContent:
    def _by_sha(self) -> dict[str, dict[str, Any]]:
        return {e["content_sha256"]: e for e in _project().entries}

    def test_clean_content_is_cleared(self) -> None:
        entry = self._by_sha()[CLEAN_A]
        assert entry["status"] == "CLEARED"
        assert entry["pii_detected"] is False
        assert "review_status" not in entry

    def test_approved_content_keeps_its_detection(self) -> None:
        entry = self._by_sha()[DETECTED]
        assert entry["pii_detected"] is True
        assert entry["status"] == "DETECTED_REVIEWED_ACCEPTED"
        assert entry["review_status"] == "APPROVED"
        assert entry["review_bundle_sha256"] == BUNDLE
        assert entry["decision_set_id"] == DECISION_SET_ID

    def test_rejected_content_is_quarantined_and_never_authorized(self) -> None:
        p = _project(
            decision_set_document=_decision_set(
                [_decision(decision="REJECTED",
                           dispositions=("PERSONAL_DATA_PRESENT", "FALSE_POSITIVE_TECHNICAL"))]
            ),
        )
        entry = {e["content_sha256"]: e for e in p.entries}[DETECTED]
        assert entry["status"] == "QUARANTINED_PII"
        assert entry["pii_detected"] is True
        assert entry["review_status"] == "REJECTED"
        assert DETECTED not in p.authorized
        assert p.counts["quarantined_count"] == 1
        assert p.counts["authorized_count"] == 2

    def test_entries_never_carry_raw_material(self) -> None:
        for entry in _project().entries:
            assert "match_text" not in entry
            assert "context" not in entry


# ─────────────────────────────────────────────────────────────────────────
# §3 + §8 — la matrice de refus du producteur
# ─────────────────────────────────────────────────────────────────────────


class TestProducerRefusals:
    def test_detected_content_without_any_decision_set_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="no decision set"):
            _project(decision_set_document=None, review_bundles={})

    def test_detected_content_missing_from_the_decision_set_fails(self) -> None:
        other = "8" * 64
        with pytest.raises(PiiProjectionError, match="detected .* no decision"):
            _project(
                scanned=[
                    _scanned(CLEAN_A),
                    _scanned(DETECTED, (FINDING_1, FINDING_2)),
                    _scanned(other, (_finding("x"),)),
                ],
            )

    def test_decision_for_a_content_outside_the_corpus_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="outside the corpus"):
            _project(
                decision_set_document=_decision_set(
                    [
                        _decision(),
                        _decision(sha="9" * 64, findings=(_finding("y"),), bundle="a" * 64),
                    ]
                ),
                review_bundles={DETECTED: BUNDLE, "9" * 64: "a" * 64},
            )

    def test_decision_for_a_content_the_scan_does_not_detect_fails(self) -> None:
        """Une décision sans détection courante : la mesure a changé sous elle."""
        with pytest.raises(PiiProjectionError, match="no current detection"):
            _project(
                scanned=[_scanned(CLEAN_A), _scanned(CLEAN_B), _scanned(DETECTED)],
            )

    def test_duplicate_decision_fails(self) -> None:
        with pytest.raises(PiiProjectionError):
            _project(decision_set_document=_decision_set([_decision(), _decision()]))

    def test_unknown_bundle_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="no review bundle"):
            _project(review_bundles={})

    def test_divergent_bundle_sha_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="bundle"):
            _project(review_bundles={DETECTED: "6" * 64})

    def test_divergent_policy_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="policy"):
            _project(policy_sha256="6" * 64)

    def test_divergent_scanner_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="scanner"):
            _project(scanner_sha256="6" * 64)

    def test_divergent_page_policy_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="page policy"):
            _project(page_policy_sha256="6" * 64)

    def test_scan_finding_absent_from_the_decision_fails(self) -> None:
        """Une correspondance que personne n'a dispositionnée."""
        with pytest.raises(PiiProjectionError, match="no disposition"):
            _project(
                scanned=[
                    _scanned(CLEAN_A), _scanned(CLEAN_B),
                    _scanned(DETECTED, (FINDING_1, FINDING_2, _finding("f3", page=7))),
                ],
            )

    def test_decided_finding_absent_from_the_scan_fails(self) -> None:
        """Une disposition qui ne porte plus sur rien de mesurable."""
        with pytest.raises(PiiProjectionError, match="no longer"):
            _project(scanned=[_scanned(CLEAN_A), _scanned(CLEAN_B),
                              _scanned(DETECTED, (FINDING_1,))])

    def test_same_finding_count_but_different_universe_fails(self) -> None:
        """Le contrôle porte sur les ENSEMBLES, pas sur le nombre.

        Deux findings décidés, deux findings scannés — mais pas les mêmes."""
        with pytest.raises(PiiProjectionError):
            _project(
                scanned=[
                    _scanned(CLEAN_A), _scanned(CLEAN_B),
                    _scanned(DETECTED, (FINDING_1, _finding("impostor", page=4))),
                ],
            )

    def test_finding_whose_material_digest_changed_fails(self) -> None:
        """Même identité, autre empreinte de matière : incohérence."""
        mutated = ScannedFinding(
            finding_id=FINDING_2.finding_id,
            pattern_id=FINDING_2.pattern_id,
            page=FINDING_2.page,
            match_sha256="0" * 64,
            context_sha256=FINDING_2.context_sha256,
        )
        with pytest.raises(PiiProjectionError, match="match_sha256|disagree"):
            _project(
                scanned=[_scanned(CLEAN_A), _scanned(CLEAN_B),
                         _scanned(DETECTED, (FINDING_1, mutated))],
            )

    def test_content_appearing_twice_in_the_scan_fails(self) -> None:
        with pytest.raises(PiiProjectionError, match="twice"):
            _project(scanned=[_scanned(CLEAN_A), _scanned(CLEAN_A)],
                     decision_set_document=None, review_bundles={})


class TestTheDecisionSetMustDescribeThisCorpus:
    """P1 — l'ensemble scellé doit parler DU corpus de cette release."""

    def test_a_matching_corpus_manifest_projects(self) -> None:
        assert _project().counts["reviewed_accepted_count"] == 1

    def test_another_corpus_manifest_is_refused(self) -> None:
        """Même population de contenus, autre corpus : refusé.

        La population de contenus du banc est INCHANGÉE : seule l'empreinte du
        manifeste diffère. C'est précisément le cas qu'une comparaison de
        cardinalités ne verrait pas — autant de contenus, les mêmes contenus,
        et pourtant un autre corpus.

        Un second test identique existait ici, avec une autre constante
        arbitraire (« 8 » au lieu de « 9 ») : il n'exerçait aucun chemin
        supplémentaire et donnait à croire que deux propriétés distinctes
        étaient couvertes."""
        with pytest.raises(PiiProjectionError, match="corpus manifest"):
            _project(corpus_manifest_sha256="9" * 64)


class TestADuplicateFindingIdIsNeverDeduplicated:
    """P2 — un dict servait involontairement de mécanisme de déduplication.

    `{f.finding_id: f for f in findings}` ne garde que la dernière occurrence.
    Deux findings partageant une identité — qu'ils portent la même charge ou
    non — disparaissaient donc silencieusement l'un dans l'autre, et une
    détection supplémentaire pouvait traverser sans disposition.

    Même un doublon strictement identique est refusé : une preuve qui compte
    deux fois le même signal est une preuve fausse, indépendamment de ce que
    le doublon contient."""

    def test_a_duplicate_scan_finding_id_is_refused(self) -> None:
        with pytest.raises(PiiProjectionError, match="twice|duplicate"):
            _project(
                scanned=[
                    _scanned(CLEAN_A), _scanned(CLEAN_B),
                    _scanned(DETECTED, (FINDING_1, FINDING_2, FINDING_1)),
                ],
            )

    def test_a_duplicate_with_a_conflicting_payload_is_refused(self) -> None:
        conflicting = ScannedFinding(
            finding_id=FINDING_1.finding_id,
            pattern_id=FINDING_1.pattern_id,
            page=FINDING_1.page,
            match_sha256="7" * 64,
            context_sha256=FINDING_1.context_sha256,
        )
        with pytest.raises(PiiProjectionError, match="twice|duplicate"):
            _project(
                scanned=[
                    _scanned(CLEAN_A), _scanned(CLEAN_B),
                    _scanned(DETECTED, (FINDING_1, FINDING_2, conflicting)),
                ],
            )

    def test_the_decision_side_is_guarded_by_the_contract_itself(self) -> None:
        """Le côté décision n'a pas de garde ICI — il en a un, ailleurs.

        La projection vérifiait aussi les doublons de `decision.findings`.
        Cette branche ne pouvait jamais s'exécuter : `PiiReviewDecisionV1`
        refuse « a finding_id appears twice » dès la validation du modèle, si
        bien qu'une décision porteuse de doublons n'atteignait pas la
        projection. Un garde inatteignable donne l'illusion d'une protection
        et masque où se trouve la vraie.

        Ce test vise donc le gardien réel : si quelqu'un retire le validateur
        du contrat, c'est ici que cela se voit."""
        from nexus_contracts.pii_review_decisions import PiiReviewDecisionV1

        decision = _decision()
        decision["findings"] = [decision["findings"][0], decision["findings"][0]]
        decision["signal_count"] = 2
        with pytest.raises(ValueError, match="appears twice"):
            PiiReviewDecisionV1.model_validate(decision)

    def test_the_refusal_happens_before_any_mapping_is_built(self) -> None:
        """Le refus doit précéder la construction, pas la suivre.

        Trois findings scannés pour deux dispositionnés : si la déduplication
        avait lieu d'abord, les univers coïncideraient et rien ne serait vu."""
        projection_error = None
        try:
            _project(
                scanned=[
                    _scanned(CLEAN_A), _scanned(CLEAN_B),
                    _scanned(DETECTED, (FINDING_1, FINDING_2, FINDING_2)),
                ],
            )
        except PiiProjectionError as exc:
            projection_error = str(exc)
        assert projection_error is not None
        assert "no disposition" not in projection_error, (
            "le doublon doit être refusé pour ce qu'il est, pas confondu avec "
            "un finding non dispositionné"
        )


class TestTheCorpusBindingComparesComparableThings:
    """Le liage au corpus doit confronter deux mesures de MÊME nature.

    L'ensemble de décisions scellé enregistre, sous `corpus_manifest_sha256`,
    l'empreinte du FICHIER d'autorité de manifeste — `5ce13fac…` pour la
    campagne du 3 septembre. La release, elle, embarque la valeur que ce
    fichier DÉCLARE — `d7e5caa5…`, son `authority_sha256`.

    Ce sont deux mesures de la même autorité, jamais égales. Les comparer
    directement produit un refus systématique : la garde censée empêcher qu'une
    revue soit projetée sur un autre corpus refusait le corpus même sur lequel
    la revue a été rendue.

    Mesuré : le producteur passait `CORPUS_MANIFEST_AUTHORITY` (la valeur
    déclarée) là où l'ensemble scellé attend l'empreinte du fichier. La
    candidate de production était donc impossible à reproduire.
    """

    def test_the_sealed_campaign_projects_on_its_own_authority_file(self) -> None:
        """La campagne réelle doit se projeter sur SON fichier d'autorité."""
        import hashlib
        import json
        import pathlib

        repository = pathlib.Path(__file__).resolve().parents[3]
        decision_set = json.loads(
            (
                repository
                / "governance/pii-review-decisions/pii-review-2026-09-03-final.json"
            ).read_text(encoding="utf-8")
        )
        authority = (
            repository
            / "services/rag-pedago/data/releases/prerentree_2026_2027"
            / "profile_gate/corpus_manifest_authority.json"
        )
        file_digest = hashlib.sha256(authority.read_bytes()).hexdigest()
        assert decision_set["corpus_manifest_sha256"] == file_digest, (
            "l'ensemble scellé n'enregistre pas l'empreinte du fichier "
            "d'autorité : la nature de la liaison a changé"
        )

    def test_the_declared_value_is_not_the_file_digest(self) -> None:
        """Le contrôle qui rend le premier test nécessaire.

        Si ces deux valeurs devenaient égales, comparer l'une pour l'autre
        cesserait d'être une erreur — et ce test dirait pourquoi."""
        import hashlib
        import json
        import pathlib

        repository = pathlib.Path(__file__).resolve().parents[3]
        authority = (
            repository
            / "services/rag-pedago/data/releases/prerentree_2026_2027"
            / "profile_gate/corpus_manifest_authority.json"
        )
        declared = json.loads(authority.read_text(encoding="utf-8"))["authority_sha256"]
        assert declared != hashlib.sha256(authority.read_bytes()).hexdigest()
