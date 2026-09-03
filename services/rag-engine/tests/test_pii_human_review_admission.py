"""Matrice d'admission et de refus de la revue humaine PII (ADR-0047).

**Ce que ces tests protègent.** Un contenu où le scanner a trouvé une
correspondance ne devient jamais « propre ». Il reste `pii_detected=true` et
n'est admis que sous `DETECTED_REVIEWED_ACCEPTED`, adossé à une décision
`APPROVED` d'un ensemble scellé dont le reçu ADR-0035 vérifie, hors ligne,
qu'un humain autorisé l'a bien approuvé — pour ce SHA exact, sous la même
politique, le même scanner et le même foyer de pages.

**Pourquoi tout est synthétique ici.** Le worker ne doit dépendre d'aucun
fichier de campagne particulier : ni chemin en dur, ni identifiant en dur.
Ces tests unitaires fabriquent leur propre ensemble de décisions, leur propre
reçu signé et leur propre ancre de confiance. La preuve du candidat réel est
faite séparément, dans `TestRealCandidateDecisionSet`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import git_blob_sha1
from nexus_contracts.pii_review_decisions import (
    PII_REVIEW_DECISIONS_PROTOCOL_VERSION,
    PiiReviewDecisionSetV1,
    parse_pii_review_decision_set,
)
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    expected_challenge_digest,
    public_key_hex,
    sign_review_binding,
    verify_review_binding,
)
from pydantic import ValidationError

from ingestor.ingestion_control.sealed_evidence import (
    PII_CLEARED,
    PII_DETECTED_RECORDED,
    PII_DETECTED_REVIEWED_ACCEPTED,
    PII_QUARANTINED,
    SealedEvidenceError,
    VerifiedPIIEvidenceRegistry,
)

# Graine de signature de test. Jamais une clé de production : l'ancre de
# confiance fabriquée ici est déclarée `environment="test"`, et le worker de
# production refuse une clé de test (cf. `TrustAnchor.key`).
TEST_SEED = "33" * 32
KEY_ID = "review-binding-test-key"
REPOSITORY = "cyranoaladin/RAG"
DECISION_SET_ID = "pii-review-test-set-v1"

MANIFEST_SHA = "0" * 64
CONTENT_APPROVED = "a" * 64
CONTENT_REJECTED = "b" * 64
CONTENT_CLEARED = "c" * 64
CONTENT_UNKNOWN = "9" * 64
POLICY_SHA = "d" * 64
SCANNER_SHA = "e" * 64
PAGE_POLICY_SHA = "f" * 64
BUNDLE_APPROVED = "1" * 64
BUNDLE_REJECTED = "2" * 64

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────────────────
# Fabrique d'artefacts synthétiques
# ─────────────────────────────────────────────────────────────────────────


def make_test_anchor() -> TrustAnchor:
    return TrustAnchor.model_validate(
        {
            "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
            "keys": [
                {
                    "algorithm": "ed25519",
                    "key_id": KEY_ID,
                    "public_key": public_key_hex(TEST_SEED),
                    "environment": "test",
                    "comment": "Ephemeral unit-test signing key, never a production anchor.",
                }
            ],
        }
    )


def _finding(finding_id: str, pattern_id: str, page: int, disposition: str) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "pattern_id": pattern_id,
        "page": page,
        "match_sha256": hashlib.sha256(finding_id.encode()).hexdigest(),
        "context_sha256": hashlib.sha256(("ctx" + finding_id).encode()).hexdigest(),
        "disposition": disposition,
    }


def make_decision_set_dict() -> dict[str, Any]:
    """Un ensemble à deux décisions : une APPROVED, une REJECTED.

    Les deux existent pour que « absent de l'ensemble » et « présent mais
    refusé » soient des cas distincts et tous deux testés."""
    return {
        "protocol_version": PII_REVIEW_DECISIONS_PROTOCOL_VERSION,
        "decision_set_id": DECISION_SET_ID,
        "corpus_manifest_sha256": MANIFEST_SHA,
        "policy_id": "pii_gate_policy",
        "policy_sha256": POLICY_SHA,
        "scanner_sha256": SCANNER_SHA,
        "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
        "page_policy_sha256": PAGE_POLICY_SHA,
        "review_index_sha256": "5" * 64,
        "decisions": [
            {
                "content_sha256": CONTENT_APPROVED,
                "policy_id": "pii_gate_policy",
                "policy_sha256": POLICY_SHA,
                "scanner_sha256": SCANNER_SHA,
                "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
                "page_policy_sha256": PAGE_POLICY_SHA,
                "review_bundle_sha256": BUNDLE_APPROVED,
                "signal_classes": ["phone_french"],
                "signal_count": 2,
                "pages": [1, 4],
                "findings": sorted(
                    [
                        _finding("3" * 64, "phone_french", 1, "FALSE_POSITIVE_TECHNICAL"),
                        _finding("7" * 64, "phone_french", 4, "SYNTHETIC_EXAMPLE"),
                    ],
                    key=lambda f: f["finding_id"],
                ),
                "decision": "APPROVED",
                "justification": {
                    "category": "TECHNICAL_FALSE_POSITIVE",
                    "statement": "Segments numeriques d'un tableau de frequences, aucun abonne joignable.",
                    "raw_pii_quoted": False,
                },
                "reviewer_login": "abenrhouma",
                "decided_at": "2026-09-03T10:00:00Z",
            },
            {
                "content_sha256": CONTENT_REJECTED,
                "policy_id": "pii_gate_policy",
                "policy_sha256": POLICY_SHA,
                "scanner_sha256": SCANNER_SHA,
                "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
                "page_policy_sha256": PAGE_POLICY_SHA,
                "review_bundle_sha256": BUNDLE_REJECTED,
                "signal_classes": ["email"],
                "signal_count": 1,
                "pages": [2],
                "findings": [_finding("4" * 64, "email", 2, "PERSONAL_DATA_PRESENT")],
                "decision": "REJECTED",
                "justification": {
                    "category": "PERSONAL_DATA_PRESENT",
                    "statement": "Adresse personnelle d'une personne physique identifiable, non admissible.",
                    "raw_pii_quoted": False,
                },
                "reviewer_login": "abenrhouma",
                "decided_at": "2026-09-03T10:05:00Z",
            },
        ],
    }


def make_signed_receipt_bytes(
    raw_decision_set: bytes,
    *,
    decision_set_id: str = DECISION_SET_ID,
    reviewer_login: str = "abenrhouma",
    seed: str = TEST_SEED,
    key_id: str = KEY_ID,
) -> bytes:
    pull_request = 999
    base_sha, head_sha = "0" * 40, "1" * 40
    author = "cyranoaladin"
    doc = {
        "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
        "repository": REPOSITORY,
        "pull_request": pull_request,
        "base_ref": "main",
        "base_sha": base_sha,
        "head_sha": head_sha,
        "authorization_artifact_path": f"governance/pii-review-decisions/{decision_set_id}.json",
        "authorization_artifact_sha256": hashlib.sha256(raw_decision_set).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(raw_decision_set),
        "authorization_id": decision_set_id,
        "authorization_decision": "APPROVE_PII_REVIEW_DECISIONS",
        "review_id": 12345,
        "reviewer_login": reviewer_login,
        "reviewer_permission": "write",
        "author_login": author,
        "submitted_at": "2026-09-03T11:00:00Z",
        "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
        "challenge_digest": expected_challenge_digest(
            repository=REPOSITORY,
            pull_request=pull_request,
            base_ref="main",
            base_sha=base_sha,
            head_sha=head_sha,
            author=author,
            reviewer=reviewer_login,
        ),
        "verified_at": "2026-09-03T11:30:00Z",
        "expires_at": "2026-10-03T11:30:00Z",
        "verifier_version": "test-verifier/1",
    }
    binding = ScopeAuthorizationReviewBindingV1.model_validate(doc)
    return sign_review_binding(binding, private_key_hex=seed, key_id=key_id).canonical_bytes()


def default_results(decision_set_id: str = DECISION_SET_ID) -> list[dict[str, Any]]:
    return [
        {
            "content_sha256": CONTENT_CLEARED,
            "status": PII_CLEARED,
            "pii_detected": False,
            "pages_scanned": 10,
            "characters_scanned": 1000,
        },
        {
            "content_sha256": CONTENT_APPROVED,
            "status": PII_DETECTED_REVIEWED_ACCEPTED,
            "pii_detected": True,
            "review_status": "APPROVED",
            "review_bundle_sha256": BUNDLE_APPROVED,
            "decision_set_id": decision_set_id,
            "pages_scanned": 5,
            "characters_scanned": 500,
        },
    ]


class Bench:
    """Un banc d'essai : les quatre fichiers sur disque et leurs empreintes."""

    def __init__(self, tmp_path: Path, **kw: Any) -> None:
        decision_set_dict = kw.get("decision_set_dict") or make_decision_set_dict()
        model = PiiReviewDecisionSetV1.model_validate(decision_set_dict)
        raw_ds = model.canonical_bytes()
        if kw.get("tamper_decision_set_bytes"):
            raw_ds = raw_ds.replace(b'"signal_count": 2', b'"signal_count": 3')
        self.ds_path = tmp_path / f"{decision_set_dict['decision_set_id']}.json"
        self.ds_path.write_bytes(raw_ds)
        self.ds_sha = hashlib.sha256(raw_ds).hexdigest()

        receipt_source = kw.get("receipt_over_bytes", raw_ds)
        receipt_bytes = make_signed_receipt_bytes(
            receipt_source,
            decision_set_id=kw.get("receipt_decision_set_id", decision_set_dict["decision_set_id"]),
            reviewer_login=kw.get("reviewer_login", "abenrhouma"),
            seed=kw.get("seed", TEST_SEED),
            key_id=kw.get("key_id", KEY_ID),
        )
        if kw.get("corrupt_receipt"):
            doc = json.loads(receipt_bytes)
            doc["signature"] = "0" * len(doc["signature"])
            receipt_bytes = (json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        self.receipt_path = tmp_path / "receipt.json"
        self.receipt_path.write_bytes(receipt_bytes)

        anchor = kw.get("anchor", make_test_anchor())
        self.anchor_path = tmp_path / "anchor.json"
        anchor_raw = (json.dumps(anchor.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode()
        if kw.get("corrupt_anchor"):
            anchor_raw = b'{"protocol_version": "NEXUS-REVIEW-BINDING-V1", "keys": []}\n'
        self.anchor_path.write_bytes(anchor_raw)

        document = {
            "evidence_kind": "REAL_CORPUS_PII_SCAN",
            "corpus_manifest_sha256": MANIFEST_SHA,
            "remote_access_mode": "READ_ONLY",
            "remote_write_operations": 0,
            "raw_pii_in_output": False,
            "raw_pii_in_logs": False,
            "policy_sha256": kw.get("evidence_policy_sha256", POLICY_SHA),
            "scanner_sha256": kw.get("evidence_scanner_sha256", SCANNER_SHA),
            "page_policy_sha256": kw.get("evidence_page_policy_sha256", PAGE_POLICY_SHA),
            "decision_set_id": decision_set_dict["decision_set_id"],
            "decision_set_sha256": self.ds_sha,
            "results": kw.get("results")
            if kw.get("results") is not None
            else default_results(decision_set_dict["decision_set_id"]),
        }
        raw_pii = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        self.pii_path = tmp_path / "pii_evidence.json"
        self.pii_path.write_bytes(raw_pii)
        self.pii_sha = hashlib.sha256(raw_pii).hexdigest()

    def load(self, **overrides: Any) -> VerifiedPIIEvidenceRegistry:
        kwargs: dict[str, Any] = {
            "expected_evidence_sha256": self.pii_sha,
            "expected_corpus_manifest_sha256": MANIFEST_SHA,
            "decision_set_path": self.ds_path,
            "expected_decision_set_sha256": self.ds_sha,
            "receipt_path": self.receipt_path,
            "trust_anchor_path": self.anchor_path,
            "environment": "test",
            "expected_repository": REPOSITORY,
            "accepted_reviewers": ("abenrhouma",),
            "now": NOW,
        }
        kwargs.update(overrides)
        return VerifiedPIIEvidenceRegistry.load(self.pii_path, **kwargs)


# ─────────────────────────────────────────────────────────────────────────
# Matrice — les deux lignes PASS
# ─────────────────────────────────────────────────────────────────────────


class TestAdmissionMatrixPass:
    def test_cleared_false_passes(self, tmp_path: Path) -> None:
        """CLEARED,false → PASS, sans revue et sans changer de sens."""
        clearance = Bench(tmp_path).load().verify_content_clearance(CONTENT_CLEARED)
        assert clearance.status == PII_CLEARED
        assert clearance.pii_detected is False
        assert clearance.is_reviewed_accepted is False
        assert clearance.review_status is None

    def test_detected_reviewed_accepted_with_valid_approval_passes(self, tmp_path: Path) -> None:
        """DETECTED_REVIEWED_ACCEPTED + APPROVED valide → PASS."""
        clearance = Bench(tmp_path).load().verify_content_clearance(CONTENT_APPROVED)
        assert clearance.status == PII_DETECTED_REVIEWED_ACCEPTED
        assert clearance.is_reviewed_accepted is True

    def test_admission_never_erases_the_detection(self, tmp_path: Path) -> None:
        """Section 4 : un contenu admis reste historiquement détecté.

        Il ne devient jamais `CLEARED / pii_detected=false` : les trois
        dimensions restent lisibles séparément."""
        clearance = Bench(tmp_path).load().verify_content_clearance(CONTENT_APPROVED)
        assert clearance.pii_detected is True, "l'admission n'efface pas la détection"
        assert clearance.status != PII_CLEARED
        assert clearance.review_status == "APPROVED"
        assert clearance.decision_set_id == DECISION_SET_ID


# ─────────────────────────────────────────────────────────────────────────
# Matrice — les dix-sept lignes FAIL (fail-closed)
# ─────────────────────────────────────────────────────────────────────────


class TestAdmissionMatrixFailClosed:
    def test_detected_recorded_fails(self, tmp_path: Path) -> None:
        results = default_results()
        results[1]["status"] = PII_DETECTED_RECORDED
        bench = Bench(tmp_path, results=results)
        with pytest.raises(SealedEvidenceError, match="DETECTED_RECORDED"):
            bench.load().verify_content_clearance(CONTENT_APPROVED)

    def test_quarantined_pii_fails(self, tmp_path: Path) -> None:
        results = default_results()
        results[1]["status"] = PII_QUARANTINED
        bench = Bench(tmp_path, results=results)
        with pytest.raises(SealedEvidenceError, match="QUARANTINED_PII"):
            bench.load().verify_content_clearance(CONTENT_APPROVED)

    def test_decision_set_absent_fails(self, tmp_path: Path) -> None:
        """Une preuve qui revendique une admission sans ensemble de décisions
        chargé ne peut pas être crue : refus au chargement."""
        bench = Bench(tmp_path)
        with pytest.raises(SealedEvidenceError, match="decision set"):
            bench.load(decision_set_path=None, expected_decision_set_sha256=None)

    def test_decision_set_file_missing_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path)
        bench.ds_path.unlink()
        with pytest.raises(SealedEvidenceError, match="decision set"):
            bench.load()

    def test_content_absent_from_decision_set_fails(self, tmp_path: Path) -> None:
        results = default_results()
        results[1]["content_sha256"] = CONTENT_UNKNOWN
        bench = Bench(tmp_path, results=results)
        with pytest.raises(SealedEvidenceError, match="absent from decision set"):
            bench.load()

    def test_rejected_decision_fails(self, tmp_path: Path) -> None:
        results = default_results()
        results[1]["content_sha256"] = CONTENT_REJECTED
        results[1]["review_bundle_sha256"] = BUNDLE_REJECTED
        bench = Bench(tmp_path, results=results)
        with pytest.raises(SealedEvidenceError, match="REJECTED"):
            bench.load()

    def test_undispositioned_finding_fails(self, tmp_path: Path) -> None:
        """Une décision dont un finding porte PERSONAL_DATA_PRESENT n'admet rien.

        Le contrat interdit déjà un `APPROVED` ainsi composé ; ce test prouve
        que le worker le refuse aussi s'il rencontrait un tel ensemble."""
        document = make_decision_set_dict()
        approved = document["decisions"][0]
        approved["findings"][0]["disposition"] = "PERSONAL_DATA_PRESENT"
        with pytest.raises(ValidationError, match="PERSONAL_DATA_PRESENT"):
            PiiReviewDecisionSetV1.model_validate(document)

    def test_finding_count_below_signal_count_fails(self, tmp_path: Path) -> None:
        """Un finding non dispositionné = un signal mesuré sans disposition."""
        document = make_decision_set_dict()
        document["decisions"][0]["findings"] = document["decisions"][0]["findings"][:1]
        with pytest.raises(ValidationError, match="signal_count"):
            PiiReviewDecisionSetV1.model_validate(document)

    def test_content_sha_mismatch_fails(self, tmp_path: Path) -> None:
        """Le reçu et l'ensemble sont valides, mais le contenu servi n'est pas
        celui qui a été décidé : le SHA du scan ne figure dans aucune décision."""
        results = default_results()
        results[1]["content_sha256"] = "8" * 64
        bench = Bench(tmp_path, results=results)
        with pytest.raises(SealedEvidenceError, match="absent from decision set"):
            bench.load()

    def test_review_bundle_sha_mismatch_fails(self, tmp_path: Path) -> None:
        results = default_results()
        results[1]["review_bundle_sha256"] = "6" * 64
        bench = Bench(tmp_path, results=results)
        with pytest.raises(SealedEvidenceError, match="review bundle"):
            bench.load()

    def test_policy_mismatch_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path, evidence_policy_sha256="7" * 64)
        with pytest.raises(SealedEvidenceError, match="policy mismatch"):
            bench.load()

    def test_scanner_mismatch_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path, evidence_scanner_sha256="7" * 64)
        with pytest.raises(SealedEvidenceError, match="scanner mismatch"):
            bench.load()

    def test_page_policy_mismatch_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path, evidence_page_policy_sha256="7" * 64)
        with pytest.raises(SealedEvidenceError, match="page-policy mismatch"):
            bench.load()

    def test_decision_set_digest_tampered_fails(self, tmp_path: Path) -> None:
        """Les octets sur disque ne sont plus ceux dont on attend l'empreinte."""
        bench = Bench(tmp_path)
        bench.ds_path.write_bytes(bench.ds_path.read_bytes().replace(b"abenrhouma", b"abenrhoumb"))
        with pytest.raises(SealedEvidenceError, match="decision set"):
            bench.load()

    def test_receipt_absent_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path)
        with pytest.raises(SealedEvidenceError, match="receipt"):
            bench.load(receipt_path=None)

    def test_receipt_file_missing_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path)
        bench.receipt_path.unlink()
        with pytest.raises(SealedEvidenceError, match="receipt"):
            bench.load()

    def test_receipt_invalid_signature_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path, corrupt_receipt=True)
        with pytest.raises(SealedEvidenceError, match="receipt"):
            bench.load()

    def test_receipt_covers_another_decision_set_fails(self, tmp_path: Path) -> None:
        """Un reçu authentique, signé, mais émis pour un autre ensemble."""
        other = make_decision_set_dict()
        other["decision_set_id"] = "pii-review-other-set-v1"
        other_raw = PiiReviewDecisionSetV1.model_validate(other).canonical_bytes()
        bench = Bench(
            tmp_path,
            receipt_over_bytes=other_raw,
            receipt_decision_set_id="pii-review-other-set-v1",
        )
        with pytest.raises(SealedEvidenceError, match="receipt"):
            bench.load()

    def test_reviewer_not_authorized_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path, reviewer_login="intrus")
        with pytest.raises(SealedEvidenceError, match="receipt"):
            bench.load()

    def test_trust_anchor_invalid_fails(self, tmp_path: Path) -> None:
        """Une ancre sans la clé qui a signé n'autorise rien."""
        bench = Bench(tmp_path, corrupt_anchor=True)
        with pytest.raises(SealedEvidenceError, match="trust anchor|receipt"):
            bench.load()

    def test_trust_anchor_file_missing_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path)
        bench.anchor_path.unlink()
        with pytest.raises(SealedEvidenceError, match="trust anchor"):
            bench.load()

    def test_receipt_signed_by_unknown_key_fails(self, tmp_path: Path) -> None:
        bench = Bench(tmp_path, seed="44" * 32)
        with pytest.raises(SealedEvidenceError, match="receipt"):
            bench.load()


# ─────────────────────────────────────────────────────────────────────────
# Section 2 — aucune identité de campagne en dur dans le code métier
# ─────────────────────────────────────────────────────────────────────────


class TestNoHardcodedCampaignIdentity:
    def test_worker_source_names_no_campaign_identifier(self) -> None:
        """Une rotation de l'ensemble de décisions ne doit toucher aucun .py.

        On lit les sources du plan de données qui décident de l'admission : ni
        l'identifiant de campagne, ni un chemin de gouvernance en dur."""
        src = Path(__file__).resolve().parents[1] / "src" / "ingestor"
        # L'identifiant d'une campagne n'a sa place nulle part dans le moteur.
        campaign_free = [
            src / "ingestion_control",
            src / "ingestion_worker",
            src / "ingestion_agents",
        ]
        # Le chemin de gouvernance ne doit pas apparaître là où l'admission se
        # décide : l'y écrire contournerait l'injection. Ailleurs (aide d'un
        # `--decision-set-id`, par exemple) le nommer est légitime.
        deciding = [
            src / "ingestion_control" / "sealed_evidence.py",
            src / "ingestion_control" / "scope_enforcement.py",
            src / "ingestion_agents" / "quality_agent.py",
            src / "ingestion_worker" / "runner.py",
        ]
        offenders: list[str] = []
        for root in campaign_free:
            for source in root.rglob("*.py"):
                if "pii-review-2026-09-03-final" in source.read_text(encoding="utf-8"):
                    offenders.append(f"{source.name}: campaign identifier")
        for source in deciding:
            if "governance/pii-review-decisions" in source.read_text(encoding="utf-8"):
                offenders.append(f"{source.name}: hardcoded governance path")
        assert offenders == [], f"identité de campagne codée en dur: {offenders}"

    def test_registry_serves_an_injected_decision_set_of_any_identifier(
        self, tmp_path: Path
    ) -> None:
        """Le même code admet un ensemble portant un tout autre identifiant."""
        rotated = make_decision_set_dict()
        rotated["decision_set_id"] = "pii-review-2027-01-15-rotation"
        bench = Bench(tmp_path, decision_set_dict=rotated)
        clearance = bench.load().verify_content_clearance(CONTENT_APPROVED)
        assert clearance.decision_set_id == "pii-review-2027-01-15-rotation"


# ─────────────────────────────────────────────────────────────────────────
# Intégration — le candidat réel
# ─────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DS = REPO_ROOT / "governance/pii-review-decisions/pii-review-2026-09-03-final.json"
REAL_RECEIPT = REPO_ROOT / "governance/pii-review-bindings/pii-review-2026-09-03-final.json"
REAL_ANCHOR = REPO_ROOT / "governance/trust-anchors/review-binding-v1.json"


class TestRealCandidateDecisionSet:
    """Preuve du candidat réel — distincte des tests unitaires déterministes."""

    def test_real_decision_set_is_canonical_and_fully_dispositioned(self) -> None:
        decision_set = parse_pii_review_decision_set(REAL_DS.read_bytes())
        assert decision_set.decision_set_id == "pii-review-2026-09-03-final"
        undecided = [d for d in decision_set.decisions if d.decision not in ("APPROVED", "REJECTED")]
        assert undecided == []
        findings = [f for d in decision_set.decisions for f in d.findings]
        assert all(f.disposition for f in findings)
        assert len(findings) == sum(d.signal_count for d in decision_set.decisions)

    def test_real_receipt_verifies_against_the_production_anchor(self) -> None:
        anchor = TrustAnchor.model_validate(json.loads(REAL_ANCHOR.read_text(encoding="utf-8")))
        binding = verify_review_binding(
            REAL_RECEIPT.read_bytes(),
            trust_anchor=anchor,
            environment="production",
            now=datetime.now(UTC),
        )
        assert binding.authorization_decision == "APPROVE_PII_REVIEW_DECISIONS"
        assert binding.authorization_id == "pii-review-2026-09-03-final"
        assert binding.reviewer_login != binding.author_login

    def test_real_receipt_is_bound_to_the_real_decision_set_bytes(self) -> None:
        from nexus_contracts.review_binding import require_matches_pii_review_decision_set

        raw = REAL_DS.read_bytes()
        anchor = TrustAnchor.model_validate(json.loads(REAL_ANCHOR.read_text(encoding="utf-8")))
        binding = verify_review_binding(
            REAL_RECEIPT.read_bytes(),
            trust_anchor=anchor,
            environment="production",
            now=datetime.now(UTC),
        )
        require_matches_pii_review_decision_set(
            binding,
            decision_set_id="pii-review-2026-09-03-final",
            decision_set_bytes=raw,
            decision_set_git_blob_sha1=git_blob_sha1(raw),
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=("abenrhouma",),
        )

    def test_real_candidate_admits_exactly_its_approved_contents(self, tmp_path: Path) -> None:
        """Le registre, alimenté par les artefacts scellés réels, admet
        exactement l'ensemble APPROVED — mesuré, jamais écrit en dur."""
        raw_ds = REAL_DS.read_bytes()
        decision_set = parse_pii_review_decision_set(raw_ds)
        approved = sorted(decision_set.approved_content_sha256)

        results = [
            {
                "content_sha256": sha,
                "status": PII_DETECTED_REVIEWED_ACCEPTED,
                "pii_detected": True,
                "review_status": "APPROVED",
                "review_bundle_sha256": decision_set.decision_for(sha).review_bundle_sha256,
                "decision_set_id": decision_set.decision_set_id,
                "pages_scanned": 1,
                "characters_scanned": 1,
            }
            for sha in approved
        ]
        document = {
            "evidence_kind": "REAL_CORPUS_PII_SCAN",
            "corpus_manifest_sha256": decision_set.corpus_manifest_sha256,
            "remote_access_mode": "READ_ONLY",
            "remote_write_operations": 0,
            "raw_pii_in_output": False,
            "raw_pii_in_logs": False,
            "policy_sha256": decision_set.policy_sha256,
            "scanner_sha256": decision_set.scanner_sha256,
            "page_policy_sha256": decision_set.page_policy_sha256,
            "results": results,
        }
        raw_pii = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        pii_path = tmp_path / "pii_evidence.json"
        pii_path.write_bytes(raw_pii)

        registry = VerifiedPIIEvidenceRegistry.load(
            pii_path,
            expected_evidence_sha256=hashlib.sha256(raw_pii).hexdigest(),
            expected_corpus_manifest_sha256=decision_set.corpus_manifest_sha256,
            decision_set_path=REAL_DS,
            expected_decision_set_sha256=hashlib.sha256(raw_ds).hexdigest(),
            receipt_path=REAL_RECEIPT,
            trust_anchor_path=REAL_ANCHOR,
            environment="production",
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=("abenrhouma",),
            now=datetime.now(UTC),
        )
        admitted = [
            sha for sha in approved
            if registry.verify_content_clearance(sha).is_reviewed_accepted
        ]
        assert admitted == approved
        # La vérité PII reste lisible jusque dans les compteurs : aucun de ces
        # contenus n'est « cleared », ils sont admis après revue.
        assert registry.cleared_count == 0
        assert registry.reviewed_accepted_count == len(approved)
        for sha in approved:
            assert registry.verify_content_clearance(sha).pii_detected is True
