"""``NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1`` — ce qu'une revue a établi.

**Le problème que ce contrat résout.** La chaîne d'autorisation LOT41A
revérifiait, à chaque usage, que la pull request d'autorité était encore
**ouverte** et approuvée. Or l'artefact d'autorisation doit être sur ``main``
pour être relu — donc la PR doit être fusionnée. Les deux ne peuvent pas être
vraies au même moment : mesuré sur la PR #233, l'usage répondait
``pull_request_not_open`` alors que la revue humaine avait bel et bien eu
lieu, au bon head, par le bon relecteur.

Le modèle change de temps, pas de sévérité (ADR-0058) :

* **à l'enregistrement**, tout reste exigé en direct — PR ouverte, APPROVED,
  head exact, challenge correct, contexte ``trusted-human-review/head-pinned``
  au vert, artefact relu octet à octet ;
* **à l'usage**, c'est cette preuve-là qui est vérifiée, pas l'état courant
  d'une PR que le temps a nécessairement fermée.

**Ce que la preuve ne prétend pas.** Elle n'affirme rien sur l'état de la PR
après l'enregistrement, et ne remplace pas une révocation : si une revue doit
être invalidée après coup, elle doit être révoquée **explicitement**. Une
preuve scellée sans registre de révocation serait une autorisation éternelle.

**Ce qui la rend vérifiable hors ligne.** Elle porte les sept dimensions du
challenge — dont l'auteur et la ``base_ref``, que l'ancien modèle ne
conservait pas. Le challenge peut donc être **recalculé** et comparé, au lieu
d'être simplement recopié : une preuve dont le challenge ne se redérive pas
de ses propres champs est refusée.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, field_validator

from nexus_contracts.document import StrictBaseModel

SEALED_TRUSTED_REVIEW_EVIDENCE_PROTOCOL = "NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1"

#: Le protocole de challenge d'ADR-0025. La preuve le nomme au lieu de le
#: supposer : un futur V2 ne doit pas pouvoir être relu comme un V1.
TRUSTED_REVIEW_CHALLENGE_PROTOCOL = "NEXUS-TRUSTED-REVIEW-V1"

_HEX64 = r"^[0-9a-f]{64}$"
_GIT_SHA1 = r"^[0-9a-f]{40}$"
_GIT_BLOB_SHA = r"^[0-9a-f]{40}$"
_REPOSITORY = r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"
_LOGIN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"
_AUTHORIZATION_ID = r"^[a-z0-9][a-z0-9._-]{0,127}$"
_CHALLENGE = r"^NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}$"
_REF = r"^[A-Za-z0-9._/-]{1,255}$"
_PATH = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$"

_CANONICAL_INDENT = 2


class SealedTrustedReviewEvidenceError(ValueError):
    """La preuve scellée ne tient pas — refus, jamais un avertissement."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=_CANONICAL_INDENT, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _canonical_moment(value: datetime) -> str:
    return value.astimezone(tz=value.tzinfo).isoformat().replace("+00:00", "Z")


def _challenge_payload_bytes(document: dict[str, Any]) -> bytes:
    """Les sept dimensions du challenge, sérialisées comme ADR-0025 le fait.

    Reproduit exactement ``scripts/github/trusted_human_review.canonical_json``
    — clés triées, séparateurs compacts, sans espace — parce qu'un challenge
    recalculé autrement ne prouverait rien."""
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class SealedTrustedReviewEvidenceV1(StrictBaseModel):
    """La revue humaine, scellée au moment où elle était vivante."""

    protocol_version: Literal["NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1"]

    # — Ce que la revue portait —
    repository: StrictStr = Field(pattern=_REPOSITORY)
    pull_request: StrictInt = Field(gt=0)
    pull_request_base_ref: StrictStr = Field(pattern=_REF)
    pull_request_base_sha: StrictStr = Field(pattern=_GIT_SHA1)
    pull_request_head_sha: StrictStr = Field(pattern=_GIT_SHA1)
    #: L'auteur fait partie des sept dimensions du challenge. L'ancien modèle
    #: ne le conservait pas, ce qui rendait le challenge irrecalculable.
    pull_request_author: StrictStr = Field(pattern=_LOGIN)

    # — Ce qu'elle autorisait —
    authorization_id: StrictStr = Field(pattern=_AUTHORIZATION_ID)
    artifact_path: StrictStr = Field(pattern=_PATH)
    #: Deux empreintes des mêmes octets : le sha256 du contenu, et le SHA de
    #: blob Git que GitHub expose. Les deux, parce qu'elles se vérifient
    #: contre des choses différentes.
    artifact_sha256: StrictStr = Field(pattern=_HEX64)
    artifact_blob_sha: StrictStr = Field(pattern=_GIT_BLOB_SHA)

    # — Qui a approuvé, et quand —
    reviewer: StrictStr = Field(pattern=_LOGIN)
    review_id: StrictInt = Field(gt=0)
    review_node_id: StrictStr = Field(min_length=1, max_length=255)
    review_submitted_at: AwareDatetime

    # — Le challenge, et le contexte qui l'a validé —
    challenge_protocol: Literal["NEXUS-TRUSTED-REVIEW-V1"]
    challenge: StrictStr = Field(pattern=_CHALLENGE)
    #: Le contexte requis de la protection de branche. Seul ``success`` est
    #: représentable : une preuve ne peut pas sceller un contexte en échec.
    head_pinned_status: Literal["success"]
    head_pinned_context: StrictStr = Field(min_length=1, max_length=255)

    # — Qui a scellé, et avec quoi —
    recorded_at: AwareDatetime
    recorder_version: StrictStr = Field(min_length=1, max_length=64)
    workflow_run_id: StrictInt | None = Field(default=None, gt=0)

    @field_validator("reviewer", "pull_request_author")
    @classmethod
    def _login_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("login must not be blank")
        return value

    def expected_challenge(self) -> str:
        """Recalcule le challenge depuis les sept dimensions scellées.

        C'est ce qui distingue une preuve d'une copie : le challenge n'est
        pas cru sur parole, il doit se redériver des champs qui l'entourent."""
        payload = {
            "author": self.pull_request_author,
            "base_ref": self.pull_request_base_ref,
            "base_sha": self.pull_request_base_sha,
            "head_sha": self.pull_request_head_sha,
            "protocol": self.challenge_protocol,
            "pull_request": self.pull_request,
            "repository": self.repository,
            "reviewer": self.reviewer,
        }
        digest = sha256(_challenge_payload_bytes(payload)).hexdigest()
        return f"{self.challenge_protocol}:{digest}"

    def canonical_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "artifact_blob_sha": self.artifact_blob_sha,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "authorization_id": self.authorization_id,
            "challenge": self.challenge,
            "challenge_protocol": self.challenge_protocol,
            "head_pinned_context": self.head_pinned_context,
            "head_pinned_status": self.head_pinned_status,
            "protocol_version": self.protocol_version,
            "pull_request": self.pull_request,
            "pull_request_author": self.pull_request_author,
            "pull_request_base_ref": self.pull_request_base_ref,
            "pull_request_base_sha": self.pull_request_base_sha,
            "pull_request_head_sha": self.pull_request_head_sha,
            "recorded_at": _canonical_moment(self.recorded_at),
            "recorder_version": self.recorder_version,
            "repository": self.repository,
            "review_id": self.review_id,
            "review_node_id": self.review_node_id,
            "review_submitted_at": _canonical_moment(self.review_submitted_at),
            "reviewer": self.reviewer,
        }
        if self.workflow_run_id is not None:
            document["workflow_run_id"] = self.workflow_run_id
        return document

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def parse_sealed_trusted_review_evidence(
    document: dict[str, Any] | bytes,
) -> SealedTrustedReviewEvidenceV1:
    """Parse strict. Un champ manquant est un refus, pas un défaut."""
    if isinstance(document, bytes | bytearray):
        try:
            document = json.loads(bytes(document).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SealedTrustedReviewEvidenceError(
                f"sealed trusted review evidence is not valid UTF-8 JSON: {exc}"
            ) from exc
    if not isinstance(document, dict):
        raise SealedTrustedReviewEvidenceError(
            "sealed trusted review evidence must be a JSON object"
        )
    if not document:
        raise SealedTrustedReviewEvidenceError(
            "sealed trusted review evidence is empty — an authorization "
            "registered before this model carries no proof, and no proof is a "
            "refusal, never a grandfathered acceptance"
        )
    try:
        return SealedTrustedReviewEvidenceV1.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise SealedTrustedReviewEvidenceError(
            f"sealed trusted review evidence failed strict validation: {exc}"
        ) from exc


def require_trusted_reviewer(
    evidence: SealedTrustedReviewEvidenceV1, *, allowed_reviewers: tuple[str, ...]
) -> None:
    """Le relecteur scellé doit être encore dans l'allowlist gouvernée.

    C'est la partie de la vérification qui reste **vivante** : une identité
    retirée de l'allowlist cesse d'autoriser, sans qu'on ait besoin de
    révoquer chaque autorisation une par une."""
    if evidence.reviewer not in allowed_reviewers:
        raise SealedTrustedReviewEvidenceError(
            f"reviewer {evidence.reviewer!r} is not in the governed allowlist "
            f"{sorted(allowed_reviewers)} — a sealed proof never outlives the "
            "authority of its signer"
        )


def require_challenge_is_self_consistent(
    evidence: SealedTrustedReviewEvidenceV1,
) -> None:
    """Le challenge scellé doit se redériver de ses propres dimensions."""
    expected = evidence.expected_challenge()
    if evidence.challenge != expected:
        raise SealedTrustedReviewEvidenceError(
            "the sealed challenge does not derive from the sealed dimensions "
            f"(expected {expected}, sealed {evidence.challenge}) — a challenge "
            "copied rather than computed proves nothing"
        )


def require_evidence_matches_authorization(
    evidence: SealedTrustedReviewEvidenceV1,
    *,
    authorization_id: str,
    artifact_path: str,
    artifact_blob_sha: str,
    repository: str,
    pull_request: int,
    base_sha: str,
    head_sha: str,
    reviewer: str,
    review_id: int,
    challenge: str,
) -> None:
    """La preuve et la ligne enregistrée doivent décrire la même revue.

    Deux représentations du même fait qui divergeraient rendraient le
    scellement décoratif : on vérifie donc chaque champ, au lieu de faire
    confiance à celui qui est le plus commode à lire."""
    ecarts: list[str] = []
    for champ, scelle, enregistre in (
        ("authorization_id", evidence.authorization_id, authorization_id),
        ("artifact_path", evidence.artifact_path, artifact_path),
        ("artifact_blob_sha", evidence.artifact_blob_sha, artifact_blob_sha),
        ("repository", evidence.repository, repository),
        ("pull_request", evidence.pull_request, pull_request),
        ("base_sha", evidence.pull_request_base_sha, base_sha),
        ("head_sha", evidence.pull_request_head_sha, head_sha),
        ("reviewer", evidence.reviewer, reviewer),
        ("review_id", evidence.review_id, review_id),
        ("challenge", evidence.challenge, challenge),
    ):
        if scelle != enregistre:
            ecarts.append(f"{champ}: sealed={scelle!r}, recorded={enregistre!r}")
    if ecarts:
        raise SealedTrustedReviewEvidenceError(
            "sealed trusted review evidence disagrees with the recorded "
            f"authorization: {ecarts}"
        )


__all__ = [
    "SEALED_TRUSTED_REVIEW_EVIDENCE_PROTOCOL",
    "TRUSTED_REVIEW_CHALLENGE_PROTOCOL",
    "SealedTrustedReviewEvidenceError",
    "SealedTrustedReviewEvidenceV1",
    "parse_sealed_trusted_review_evidence",
    "require_challenge_is_self_consistent",
    "require_evidence_matches_authorization",
    "require_trusted_reviewer",
]
