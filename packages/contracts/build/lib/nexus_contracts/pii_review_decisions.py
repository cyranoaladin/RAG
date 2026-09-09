"""Décisions humaines de revue PII, par contenu (ADR-0047).

**Ce que ce contrat protège.** La politique PII scellée exige une revue humaine
pour tout contenu où le scanner trouve une correspondance. Ce module donne à
cette revue une forme opposable : une décision INDIVIDUELLE par contenu, liée
au SHA exact, à la politique, au scanner, au foyer de pages et au paquet de
revue figé qui l'a fondée, rédigée par un reviewer nommé, sans matière brute.

Aucune décision n'est dérivable d'un compte de faux positifs ni d'une catégorie
de triage : chaque enregistrement est écrit par le reviewer. Un ensemble de
décisions est un artefact canonique, relu octet à octet, dont le chemin dérive
de son identifiant seul — comme les artefacts d'autorité (ADR-0032/0035).

Ce module ne fait aucune E/S : il reçoit des octets et rend des verdicts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from nexus_contracts.authority_artifacts import CanonicalArtifactError, _IDENTIFIER_PATTERN
from nexus_contracts.document import StrictBaseModel

#: Protocole de l'ensemble de décisions. Versionné : un futur format ne peut
#: jamais être relu comme celui-ci par accident.
PII_REVIEW_DECISIONS_PROTOCOL_VERSION = "NEXUS-PII-REVIEW-DECISIONS-V1"

#: Répertoire canonique versionné dans Git. Un ensemble de décisions n'est
#: jamais relu ailleurs — le chemin est dérivé de l'identifiant, jamais fourni.
PII_REVIEW_DECISIONS_DIR = "governance/pii-review-decisions"

_HEX64 = r"^[0-9a-f]{64}$"
_LOGIN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"

#: Dispositions fermées d'UN finding (ADR-0047 § 8). Définitions :
#: - FALSE_POSITIVE_TECHNICAL : la chaîne détectée n'est pas une donnée de la
#:   classe annoncée (fréquence lue comme adresse, années lues comme téléphone,
#:   NIR à clé invalide, identifiant technique) ;
#: - PUBLIC_INSTITUTIONAL_DATA : coordonnées d'une institution ou d'un
#:   professionnel publiées par l'État dans une ressource officielle ;
#: - SYNTHETIC_EXAMPLE : identité ou coordonnée fabriquée par le document pour
#:   enseigner un format (exercice, personnage fictif, gabarit) ;
#: - PERSONAL_DATA_PRESENT : donnée personnelle réelle d'une personne physique
#:   identifiable — jamais admissible.
FINDING_DISPOSITIONS: tuple[str, ...] = (
    "FALSE_POSITIVE_TECHNICAL",
    "PUBLIC_INSTITUTIONAL_DATA",
    "SYNTHETIC_EXAMPLE",
    "PERSONAL_DATA_PRESENT",
)
ADMISSIBLE_DISPOSITIONS: frozenset[str] = frozenset(FINDING_DISPOSITIONS) - {
    "PERSONAL_DATA_PRESENT"
}
FindingDisposition = Literal[
    "FALSE_POSITIVE_TECHNICAL",
    "PUBLIC_INSTITUTIONAL_DATA",
    "SYNTHETIC_EXAMPLE",
    "PERSONAL_DATA_PRESENT",
]

#: Catégories fermées de justification. Une catégorie ne DÉCIDE rien : elle
#: qualifie ce que le reviewer a constaté, et borne ce qu'une approbation peut
#: admettre (`PERSONAL_DATA_PRESENT` n'est jamais approuvable).
JustificationCategory = Literal[
    "INSTITUTIONAL_CONTACT",
    "PEDAGOGICAL_EXAMPLE",
    "FICTIONAL_IDENTITY",
    "TECHNICAL_FALSE_POSITIVE",
    "PUBLIC_OFFICIAL_PUBLICATION",
    "PERSONAL_DATA_PRESENT",
]


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _canonical_moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class PiiReviewJustificationV1(StrictBaseModel):
    """Pourquoi le reviewer a décidé — sans jamais citer la matière brute."""

    category: JustificationCategory
    statement: StrictStr = Field(min_length=20, max_length=1000)
    raw_pii_quoted: StrictBool

    @field_validator("raw_pii_quoted")
    @classmethod
    def _never_quotes(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError(
                "raw_pii_quoted must be false — a justification never carries the "
                "personal data it judges"
            )
        return value


class PiiFindingDispositionV1(StrictBaseModel):
    """La disposition d'UN finding, identifié sans sa matière brute.

    `finding_id`, `match_sha256` et `context_sha256` sont ceux de l'index des
    paquets : le reviewer voit la matière dans le paquet local, le dépôt ne
    garde que les empreintes."""

    finding_id: StrictStr = Field(pattern=_HEX64)
    pattern_id: StrictStr = Field(min_length=1, max_length=64)
    page: StrictInt = Field(ge=1)
    match_sha256: StrictStr = Field(pattern=_HEX64)
    context_sha256: StrictStr = Field(pattern=_HEX64)
    disposition: FindingDisposition

    @field_validator("page")
    @classmethod
    def _page_is_int(cls, value: int) -> int:
        if isinstance(value, bool):
            raise ValueError("page must be an integer")
        return value

    def canonical_document(self) -> dict[str, Any]:
        return {
            "context_sha256": self.context_sha256,
            "disposition": self.disposition,
            "finding_id": self.finding_id,
            "match_sha256": self.match_sha256,
            "page": self.page,
            "pattern_id": self.pattern_id,
        }


class PiiReviewDecisionV1(StrictBaseModel):
    """Une décision, un contenu, un reviewer, un paquet de revue figé.

    La décision documentaire découle des dispositions de ses findings : un
    `APPROVED` exige que TOUS soient admissibles ; un `REJECTED` en nomme au
    moins un `PERSONAL_DATA_PRESENT`. « J'ai vu le premier match, ça semble
    bon » n'est pas représentable."""

    content_sha256: StrictStr = Field(pattern=_HEX64)
    policy_id: StrictStr = Field(min_length=1, max_length=128)
    policy_sha256: StrictStr = Field(pattern=_HEX64)
    scanner_sha256: StrictStr = Field(pattern=_HEX64)
    page_policy_id: StrictStr = Field(min_length=1, max_length=128)
    page_policy_sha256: StrictStr = Field(pattern=_HEX64)
    review_bundle_sha256: StrictStr = Field(pattern=_HEX64)
    signal_classes: tuple[StrictStr, ...] = Field(min_length=1)
    signal_count: StrictInt = Field(gt=0)
    pages: tuple[StrictInt, ...] = Field(min_length=1)
    findings: tuple[PiiFindingDispositionV1, ...] = Field(min_length=1)
    decision: Literal["APPROVED", "REJECTED"]
    justification: PiiReviewJustificationV1
    reviewer_login: StrictStr = Field(pattern=_LOGIN)
    decided_at: AwareDatetime

    @field_validator("signal_classes")
    @classmethod
    def _classes_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or item != item.strip() for item in value):
            raise ValueError("signal_classes must be non-empty trimmed identifiers")
        if list(value) != sorted(set(value)):
            raise ValueError("signal_classes must be sorted and unique")
        return value

    @field_validator("pages")
    @classmethod
    def _pages_strictly_increasing(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(isinstance(item, bool) or item < 1 for item in value):
            raise ValueError("pages must be physical page numbers >= 1")
        if list(value) != sorted(set(value)):
            raise ValueError("pages must be strictly increasing")
        return value

    @model_validator(mode="after")
    def _findings_match_the_measure(self) -> PiiReviewDecisionV1:
        ids = [finding.finding_id for finding in self.findings]
        if len(set(ids)) != len(ids):
            raise ValueError("a finding_id appears twice")
        if ids != sorted(ids):
            raise ValueError("findings must be sorted by finding_id")
        if len(self.findings) != self.signal_count:
            raise ValueError(
                f"{len(self.findings)} findings dispositioned for signal_count={self.signal_count}"
            )
        if {finding.page for finding in self.findings} != set(self.pages):
            raise ValueError("findings pages differ from the measured pages")
        if {finding.pattern_id for finding in self.findings} != set(self.signal_classes):
            raise ValueError("findings pattern ids differ from the measured signal_classes")
        return self

    @model_validator(mode="after")
    def _approval_never_admits_personal_data(self) -> PiiReviewDecisionV1:
        personal = [
            finding.finding_id
            for finding in self.findings
            if finding.disposition == "PERSONAL_DATA_PRESENT"
        ]
        if self.decision == "APPROVED":
            if self.justification.category == "PERSONAL_DATA_PRESENT":
                raise ValueError(
                    "an APPROVED decision cannot carry the PERSONAL_DATA_PRESENT category — "
                    "attested personal data is never admissible"
                )
            if personal:
                raise ValueError(
                    "an APPROVED decision cannot carry a finding dispositioned "
                    f"PERSONAL_DATA_PRESENT ({personal[0][:12]}…) — every finding must be admissible"
                )
        elif not personal:
            raise ValueError(
                "a REJECTED decision must name at least one finding dispositioned "
                "PERSONAL_DATA_PRESENT — a rejection is a finding, not a mood"
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "decided_at": _canonical_moment(self.decided_at),
            "decision": self.decision,
            "findings": [finding.canonical_document() for finding in self.findings],
            "justification": {
                "category": self.justification.category,
                "raw_pii_quoted": False,
                "statement": self.justification.statement,
            },
            "page_policy_id": self.page_policy_id,
            "page_policy_sha256": self.page_policy_sha256,
            "pages": list(self.pages),
            "policy_id": self.policy_id,
            "policy_sha256": self.policy_sha256,
            "review_bundle_sha256": self.review_bundle_sha256,
            "reviewer_login": self.reviewer_login,
            "scanner_sha256": self.scanner_sha256,
            "signal_classes": list(self.signal_classes),
            "signal_count": self.signal_count,
        }


class PiiReviewDecisionSetV1(StrictBaseModel):
    """L'ensemble scellé des décisions d'une campagne de revue."""

    protocol_version: Literal["NEXUS-PII-REVIEW-DECISIONS-V1"]
    decision_set_id: StrictStr = Field(min_length=1, max_length=128)
    corpus_manifest_sha256: StrictStr = Field(pattern=_HEX64)
    policy_id: StrictStr = Field(min_length=1, max_length=128)
    policy_sha256: StrictStr = Field(pattern=_HEX64)
    scanner_sha256: StrictStr = Field(pattern=_HEX64)
    page_policy_id: StrictStr = Field(min_length=1, max_length=128)
    page_policy_sha256: StrictStr = Field(pattern=_HEX64)
    review_index_sha256: StrictStr = Field(pattern=_HEX64)
    decisions: tuple[PiiReviewDecisionV1, ...] = Field(min_length=1)

    @field_validator("decision_set_id")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(
                f"decision_set_id {value!r} must match {_IDENTIFIER_PATTERN.pattern}"
            )
        return value

    @model_validator(mode="after")
    def _decisions_are_coherent(self) -> PiiReviewDecisionSetV1:
        shas = [decision.content_sha256 for decision in self.decisions]
        if len(set(shas)) != len(shas):
            raise ValueError("a content appears twice in the decision set")
        if shas != sorted(shas):
            raise ValueError("decisions must be sorted by content_sha256")
        bundles: dict[str, str] = {}
        for decision in self.decisions:
            if decision.policy_sha256 != self.policy_sha256 or decision.policy_id != self.policy_id:
                raise ValueError(
                    f"decision {decision.content_sha256[:12]} names another policy than the set"
                )
            if decision.scanner_sha256 != self.scanner_sha256:
                raise ValueError(
                    f"decision {decision.content_sha256[:12]} names another scanner than the set"
                )
            if (
                decision.page_policy_sha256 != self.page_policy_sha256
                or decision.page_policy_id != self.page_policy_id
            ):
                raise ValueError(
                    f"decision {decision.content_sha256[:12]} names another page policy than the set"
                )
            owner = bundles.setdefault(decision.review_bundle_sha256, decision.content_sha256)
            if owner != decision.content_sha256:
                raise ValueError("a review bundle cannot found decisions on two contents")
        return self

    @property
    def approved_content_sha256(self) -> frozenset[str]:
        return frozenset(
            decision.content_sha256
            for decision in self.decisions
            if decision.decision == "APPROVED"
        )

    def decision_for(self, content_sha256: str) -> PiiReviewDecisionV1 | None:
        for decision in self.decisions:
            if decision.content_sha256 == content_sha256:
                return decision
        return None

    def canonical_document(self) -> dict[str, Any]:
        return {
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "decision_set_id": self.decision_set_id,
            "decisions": [decision.canonical_document() for decision in self.decisions],
            "page_policy_id": self.page_policy_id,
            "page_policy_sha256": self.page_policy_sha256,
            "policy_id": self.policy_id,
            "policy_sha256": self.policy_sha256,
            "protocol_version": self.protocol_version,
            "review_index_sha256": self.review_index_sha256,
            "scanner_sha256": self.scanner_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def canonical_pii_review_decisions_path(decision_set_id: str) -> str:
    """Chemin Git canonique d'un ensemble de décisions, dérivé de l'identifiant seul."""
    if not _IDENTIFIER_PATTERN.fullmatch(decision_set_id):
        raise ValueError(
            f"decision_set_id {decision_set_id!r} must match {_IDENTIFIER_PATTERN.pattern} "
            "before a canonical path can be derived"
        )
    return f"{PII_REVIEW_DECISIONS_DIR}/{decision_set_id}.json"


def parse_pii_review_decision_set(raw: bytes) -> PiiReviewDecisionSetV1:
    """Parse strict : les octets relus doivent être leur propre forme canonique."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CanonicalArtifactError(f"decision set bytes are not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CanonicalArtifactError(f"decision set bytes are not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CanonicalArtifactError("decision set must be a JSON object")
    try:
        parsed = PiiReviewDecisionSetV1.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing, jamais silencieuse
        raise CanonicalArtifactError(f"decision set failed strict validation: {exc}") from exc
    if parsed.canonical_bytes() != raw:
        raise CanonicalArtifactError(
            "decision set bytes are not in canonical form — the reviewed bytes and "
            "their canonical re-serialization differ, so the human review cannot be "
            "bound to this content. Commit the canonical form."
        )
    return parsed


__all__ = [
    "ADMISSIBLE_DISPOSITIONS",
    "FINDING_DISPOSITIONS",
    "PII_REVIEW_DECISIONS_DIR",
    "PII_REVIEW_DECISIONS_PROTOCOL_VERSION",
    "FindingDisposition",
    "JustificationCategory",
    "PiiFindingDispositionV1",
    "PiiReviewDecisionSetV1",
    "PiiReviewDecisionV1",
    "PiiReviewJustificationV1",
    "canonical_pii_review_decisions_path",
    "parse_pii_review_decision_set",
]
