"""Tests de la transition ``authorize_governed_public_corpus`` (ADR-0037).

L'exception à ``REQUIRED_FALSE_SAFETY_FIELDS`` est la modification la plus
dangereuse de cette branche : elle ouvre la seule porte par laquelle un
corpus réel peut entrer. Les tests portent donc autant sur ce qu'elle
*refuse* que sur ce qu'elle permet.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from transition_authorization_audit import (  # noqa: E402
    ALLOWED_AUTHORIZATION_DECISIONS,
    CONDITIONALLY_EXEMPT_SAFETY_FIELDS,
    GOVERNED_PUBLIC_CORPUS_DECISION,
    GOVERNED_PUBLIC_CORPUS_REASON,
    MANDATORY_AUTHORIZATION_DECISIONS,
    REQUIRED_FALSE_SAFETY_FIELDS,
    load_config,
)
from transition_authorization_audit import (
    audit_config as audit,
)

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "transition_authorization.yml"

HEX = "a" * 64


def base_config() -> dict:
    return copy.deepcopy(load_config(CONFIG))


def governed_case(**overrides) -> dict:
    case = {
        "authorization_case_id": "governed_public_corpus_2026_08",
        "readiness_gate": "controlled_readiness_metadata_gate_v1",
        "decision": GOVERNED_PUBLIC_CORPUS_DECISION,
        "decision_reason": GOVERNED_PUBLIC_CORPUS_REASON,
        "final_human_signoff_required": True,
        "rights_confirmation_required": True,
        "provenance_confirmation_required": True,
        "pii_absence_required": True,
        "rollback_plan_required": True,
        "checksum_plan_required": True,
        "separate_real_lot_required": True,
        "real_corpus_authorized": True,
        "real_file_authorized": False,
        "pipeline_authorized": False,
        "adr_reference": "ADR-0037",
        "campaign_id": "2026-08-corpus-public",
        "campaign_sha256": HEX,
        "catalog_sha256": HEX,
        "corpus_manifest_sha256": HEX,
        "corpus_tree_digest": HEX,
        "corpus_oci_digest": "sha256:" + HEX,
        "h2_evidence_sha256": HEX,
        "review_view_sha256": HEX,
        "corpus_classification": "PUBLIC_INSTITUTIONAL",
        "private_corpus_included": False,
    }
    for key, value in overrides.items():
        if value is _ABSENT:
            case.pop(key, None)
        else:
            case[key] = value
    return case


class _Absent:
    pass


_ABSENT = _Absent()


def run(case: dict | None = None) -> dict:
    config = base_config()
    if case is not None:
        config["allowed_authorization_decisions"].append(
            GOVERNED_PUBLIC_CORPUS_DECISION
        )
        config["authorization_cases"].append(case)
    return audit(config)


def safety_errors(result: dict) -> list[str]:
    return [
        issue
        for issue in result.get("issues", [])
        if "governed_public_corpus" in issue or "real_corpus_authorized" in issue
        or "corpus_" in issue or "private_corpus" in issue or "adr_reference" in issue
        or "campaign" in issue or "catalog_sha256" in issue
        or "h2_evidence" in issue or "review_view" in issue
    ]


class TestTheShippedPolicyStaysClosed:
    def test_the_repository_policy_has_no_real_corpus_authorization(self) -> None:
        """L'activation reste une décision humaine : rien dans le dépôt ne
        doit déjà l'avoir prise."""
        config = base_config()
        for case in config["authorization_cases"]:
            assert case.get("real_corpus_authorized") is False, case[
                "authorization_case_id"
            ]

    def test_the_shipped_policy_audits_clean(self) -> None:
        assert run()["issues"] == []

    def test_the_new_decision_is_recognised_but_not_required(self) -> None:
        """Exiger sa déclaration forcerait à écrire aujourd'hui le cas
        qu'un humain doit décider demain."""
        assert GOVERNED_PUBLIC_CORPUS_DECISION in ALLOWED_AUTHORIZATION_DECISIONS
        assert GOVERNED_PUBLIC_CORPUS_DECISION not in MANDATORY_AUTHORIZATION_DECISIONS

    def test_the_historic_refusal_is_preserved(self) -> None:
        config = base_config()
        ids = {case["authorization_case_id"] for case in config["authorization_cases"]}
        assert "real_corpus_blocked_until_separate_lot" in ids


class TestTheExemptionIsNarrow:
    def test_only_real_corpus_authorized_can_ever_be_exempted(self) -> None:
        """``real_file_authorized`` désignerait un fichier arbitraire choisi
        par un opérateur ; ``pipeline_authorized`` un pipeline sans
        campagne. Aucun digest ne peut les rendre sûrs."""
        assert set(CONDITIONALLY_EXEMPT_SAFETY_FIELDS) == {"real_corpus_authorized"}
        assert set(REQUIRED_FALSE_SAFETY_FIELDS) == {
            "real_corpus_authorized",
            "real_file_authorized",
            "pipeline_authorized",
        }

    def test_real_file_authorized_is_refused_even_on_the_new_decision(self) -> None:
        result = run(governed_case(real_file_authorized=True))
        assert any("real_file_authorized must be false" in i for i in result["issues"])

    def test_pipeline_authorized_is_refused_even_on_the_new_decision(self) -> None:
        result = run(governed_case(pipeline_authorized=True))
        assert any("pipeline_authorized must be false" in i for i in result["issues"])

    def test_an_older_decision_cannot_borrow_the_exemption(self) -> None:
        """« Être impossible pour les anciennes décisions. »"""
        result = run(
            governed_case(
                decision="authorize_metadata_only_preparation",
                decision_reason="metadata_only_preparation_allowed",
            )
        )
        assert any(
            "real_corpus_authorized must be false" in i for i in result["issues"]
        )


class TestTheExemptionIsFullyPinned:
    def test_a_complete_authorization_is_accepted(self) -> None:
        assert safety_errors(run(governed_case())) == []

    @pytest.mark.parametrize(
        "field",
        [
            "adr_reference",
            "campaign_id",
            "campaign_sha256",
            "catalog_sha256",
            "corpus_manifest_sha256",
            "corpus_oci_digest",
            "corpus_tree_digest",
            "h2_evidence_sha256",
            "review_view_sha256",
            "corpus_classification",
            "private_corpus_included",
        ],
    )
    def test_every_binding_is_mandatory(self, field: str) -> None:
        """Un champ manquant refuse la transition ; il ne la laisse pas
        passer amoindrie."""
        result = run(governed_case(**{field: _ABSENT}))
        assert any(field in issue for issue in result["issues"]), (
            f"omitting {field} did not block the transition"
        )

    def test_a_mutable_tag_cannot_pin_the_corpus(self) -> None:
        result = run(governed_case(corpus_oci_digest="ghcr.io/x/rag-corpus:latest"))
        assert any("mutable tag" in issue for issue in result["issues"])

    def test_a_bare_hex_oci_digest_is_refused(self) -> None:
        result = run(governed_case(corpus_oci_digest=HEX))
        assert any("corpus_oci_digest" in issue for issue in result["issues"])

    def test_an_uppercase_digest_is_refused(self) -> None:
        result = run(governed_case(corpus_manifest_sha256="A" * 64))
        assert any(
            "corpus_manifest_sha256 must be a lowercase" in issue
            for issue in result["issues"]
        )

    def test_an_abbreviated_digest_is_refused(self) -> None:
        result = run(governed_case(catalog_sha256="a" * 12))
        assert any("catalog_sha256" in issue for issue in result["issues"])

    def test_the_wrong_decision_reason_is_refused(self) -> None:
        result = run(governed_case(decision_reason="looks_fine_to_me"))
        assert any("decision_reason" in issue for issue in result["issues"])


class TestPrivateCorpusCanNeverEnter:
    def test_a_private_classification_is_refused(self) -> None:
        result = run(governed_case(corpus_classification="PRIVATE"))
        assert any("corpus_classification must be" in i for i in result["issues"])

    def test_a_mixed_corpus_is_refused_even_with_a_public_label(self) -> None:
        """Des digests valides et une étiquette publique ne suffisent pas si
        le corpus contient du privé."""
        result = run(governed_case(private_corpus_included=True))
        assert any("private_corpus_included must be false" in i for i in result["issues"])

    def test_a_missing_privacy_declaration_is_refused(self) -> None:
        result = run(governed_case(private_corpus_included=_ABSENT))
        assert any("private_corpus_included" in i for i in result["issues"])


class TestSafetyFieldsStillApply:
    @pytest.mark.parametrize(
        "field",
        [
            "final_human_signoff_required",
            "rights_confirmation_required",
            "provenance_confirmation_required",
            "pii_absence_required",
            "rollback_plan_required",
            "checksum_plan_required",
        ],
    )
    def test_the_existing_guarantees_are_not_waived(self, field: str) -> None:
        """La nouvelle voie s'ajoute aux garanties ; elle ne les remplace
        pas."""
        result = run(governed_case(**{field: False}))
        assert any(f"{field} must be true" in issue for issue in result["issues"])


class TestConfigIsValidYaml:
    def test_the_policy_file_parses(self) -> None:
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["real_documents_allowed"] is False
        assert data["curated_ingestion_allowed"] is False
