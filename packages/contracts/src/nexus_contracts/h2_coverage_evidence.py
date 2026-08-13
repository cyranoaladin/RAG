"""Preuve H2-B machine-lisible — `NEXUS-H2-COVERAGE-EVIDENCE-V1` (ADR-0042).

Projection stricte et canonique du sous-ensemble de
``rag_pedago.imports.h2b_coverage_report.CoverageReport`` nécessaire à un
vérificateur hors ligne (le signer de readiness, ``rag-engine``) — jamais
un second calcul du gate H2-B, seulement sa représentation.

**Pourquoi ce module existe.** Avant lui, la preuve H2-B n'existait qu'en
Markdown (``--output data/reports/h2b_coverage_report.md``). Un signer qui
en dépend n'a alors que deux choix : scraper du texte libre (fragile,
explicitement rejeté), ou hacher le fichier sans jamais vérifier ce qu'il
affirme. Ce contrat donne une troisième voie : une forme structurée,
canonicalisée octet à octet, que le producteur (``rag-pedago``, qui
calcule déjà tous ces champs) sérialise et que le vérificateur
(``rag-engine``, qui ne recalcule rien) parse et confronte.

**Ce qu'il ne fait pas.** Aucun champ de ce module ne recalcule
``h2_coverage_gate_pass`` ni aucun autre verdict — ce calcul, avec toute
la sémantique pédagogique de gouvernance H2-B (droits, PII, currentness,
disposition), reste exclusivement dans ``rag-pedago`` (ADR-0001). Ce
module ne fait que représenter fidèlement un verdict déjà rendu.

Même discipline de canonicalisation que ``production_readiness.py``/
``review_binding.py`` : clés triées, indentation fixe, UTF-8, saut de
ligne final, ``extra="forbid"``.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr

from nexus_contracts.document import StrictBaseModel

#: Versionné : un futur format ne peut jamais être relu comme celui-ci par
#: accident.
H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION = "NEXUS-H2-COVERAGE-EVIDENCE-V1"

_CANONICAL_INDENT = 2
_HEX40 = r"^[0-9a-f]{40}$"
_HEX64 = r"^[0-9a-f]{64}$"

#: Valeurs réellement émises par
#: ``rag_pedago.imports.h2b_coverage_report`` pour ``rights_gate_status``/
#: ``pii_gate_status`` — vérifié dans le producteur, jamais deviné. Ce
#: contrat ne représente que ces deux champs binaires ; les autres champs
#: de gate du producteur (``currentness_gate_status``,
#: ``format_gate_status``, ce dernier paramétré par un compte
#: d'occurrences, ex. ``PASS_WITH_3_UNSUPPORTED``) ne sont pas assez
#: stables dans leur forme pour un ``Literal`` figé et restent hors de ce
#: v1 — un futur ``NEXUS-H2-COVERAGE-EVIDENCE-V2`` les couvrira si le
#: signer en a besoin.
_GATE_STATUS = Literal["PASS", "BLOCKED_INGEST_WITHOUT_CLEARANCE"]


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=_CANONICAL_INDENT, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _canonical_moment(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class H2CoverageEvidenceV1(StrictBaseModel):
    """Les faits H2-B qu'un vérificateur hors ligne peut confronter, sans
    jamais recalculer le gate lui-même."""

    protocol_version: Literal["NEXUS-H2-COVERAGE-EVIDENCE-V1"]
    environment: Literal["production"]

    # --- Identité de la production de cette preuve --------------------
    report_id: StrictStr = Field(min_length=1, max_length=128)
    generated_at: AwareDatetime
    git_commit: StrictStr = Field(pattern=_HEX40)
    producer_version: StrictStr = Field(min_length=1, max_length=128)

    # --- Identité des preuves d'entrée ---------------------------------
    manifest_sha256: StrictStr = Field(pattern=_HEX64)
    input_file_digests: dict[str, StrictStr] = Field(min_length=1)

    # --- Verdicts de couverture -----------------------------------------
    corpus_total_expected: StrictInt = Field(ge=0)
    corpus_total_actual: StrictInt = Field(ge=0)
    corpus_match: StrictBool
    sum_equals_total: StrictBool
    zero_overlap: StrictBool
    zero_gap: StrictBool
    coverage_complete: StrictBool

    # --- Verdicts de gate -------------------------------------------------
    rights_gate_status: _GATE_STATUS
    pii_gate_status: _GATE_STATUS
    golden_validation_pass: StrictBool
    h2_coverage_gate_pass: StrictBool

    # --- Liaison d'autorité (ADR-0025/ADR-0035) --------------------------
    authority_review_binding_verified: StrictBool
    authority_revocations_checked: StrictBool

    @staticmethod
    def _digest_map_pattern_ok(values: dict[str, str]) -> bool:
        return all(re.fullmatch(_HEX64, v) is not None for v in values.values())

    def canonical_document(self) -> dict[str, Any]:
        return {
            "authority_review_binding_verified": self.authority_review_binding_verified,
            "authority_revocations_checked": self.authority_revocations_checked,
            "coverage_complete": self.coverage_complete,
            "corpus_match": self.corpus_match,
            "corpus_total_actual": self.corpus_total_actual,
            "corpus_total_expected": self.corpus_total_expected,
            "environment": self.environment,
            "generated_at": _canonical_moment(self.generated_at),
            "git_commit": self.git_commit,
            "golden_validation_pass": self.golden_validation_pass,
            "h2_coverage_gate_pass": self.h2_coverage_gate_pass,
            "input_file_digests": dict(sorted(self.input_file_digests.items())),
            "manifest_sha256": self.manifest_sha256,
            "pii_gate_status": self.pii_gate_status,
            "producer_version": self.producer_version,
            "protocol_version": self.protocol_version,
            "report_id": self.report_id,
            "rights_gate_status": self.rights_gate_status,
            "sum_equals_total": self.sum_equals_total,
            "zero_gap": self.zero_gap,
            "zero_overlap": self.zero_overlap,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())


class H2CoverageEvidenceError(ValueError):
    """La preuve H2 ne prouve rien — fail-closed.

    Une seule exception pour tout refus : JSON malformé, forme non
    canonique, champ inconnu ou manquant, digest mal formé."""


def parse_h2_coverage_evidence(raw: bytes) -> H2CoverageEvidenceV1:
    """Parse strict **et** exigence de canonicité octet à octet — même
    discipline que ``authority_artifacts.parse_scope_authorization_
    artifact`` : sans elle, deux fichiers différents (espaces, ordre des
    clés) pourraient porter le même verdict logique avec des octets que
    personne n'a formellement relus."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise H2CoverageEvidenceError(f"evidence bytes are not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise H2CoverageEvidenceError(f"evidence bytes are not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise H2CoverageEvidenceError("evidence must be a JSON object")
    try:
        parsed = H2CoverageEvidenceV1.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing, jamais silencieuse
        raise H2CoverageEvidenceError(f"evidence failed strict validation: {exc}") from exc
    if not H2CoverageEvidenceV1._digest_map_pattern_ok(parsed.input_file_digests):
        raise H2CoverageEvidenceError("input_file_digests contains a malformed sha256 digest")
    reserialized = parsed.canonical_bytes()
    if reserialized != raw:
        raise H2CoverageEvidenceError(
            "evidence bytes are not in canonical form — the reviewed bytes and "
            "their canonical re-serialization differ. Commit the canonical form."
        )
    return parsed
