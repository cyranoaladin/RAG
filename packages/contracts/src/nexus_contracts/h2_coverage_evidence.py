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
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr, model_validator

from nexus_contracts.document import StrictBaseModel

#: Versionné : un futur format ne peut jamais être relu comme celui-ci par
#: accident.
H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION = "NEXUS-H2-COVERAGE-EVIDENCE-V1"
H2_COVERAGE_EVIDENCE_V2_PROTOCOL_VERSION = "NEXUS-H2-COVERAGE-EVIDENCE-V2"

_CANONICAL_INDENT = 2
_HEX40 = r"^[0-9a-f]{40}$"
_HEX64 = r"^[0-9a-f]{64}$"
#: Même motif que ``authority_artifacts._IDENTIFIER_PATTERN`` /
#: ``review_binding.ReviewBindingV1.authorization_id`` — un identifiant
#: d'autorisation n'a jamais de forme différente selon le contrat qui le
#: porte.
_IDENTIFIER = r"^[a-z0-9][a-z0-9._-]{0,127}$"

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

#: Les six preuves d'entrée sans lesquelles un gate H2-B n'a jamais été
#: réellement évalué (`--catalog`/`--routing`/`--rights`/`--pii`/`--golden`
#: sont tous obligatoires côté producteur — `generate_coverage_report`
#: lève `ValueError` si l'un manque, `h2b_coverage_report.py:986-999`,
#: jamais optionnels). Un document qui n'en porterait qu'une partie (ou
#: une clé arbitraire) ne serait lié à aucune des preuves qu'il prétend
#: représenter (Codex P1, PR #104). `golden` ajouté en round 3 : sans
#: lui, un document pouvait revendiquer `golden_validation_pass=true`
#: sans porter l'identité de la spécification supposément validée — le
#: signer, qui ne reçoit que cette preuve H2 et jamais le fichier golden
#: lui-même, ne pouvait alors distinguer une validation contre la
#: spécification gouvernée d'une validation contre une autre. `authority`
#: ajouté en round 4 : `authority_review_binding_verified=true` — donc
#: tout `h2_coverage_gate_pass=true` — exige `authority_path is not
#: None` côté producteur (sinon `authority_binding={}`,
#: `authority_review_binding_verified=bool({})=False`,
#: `h2b_coverage_report.py:1113-1151`), et cette branche renseigne
#: toujours `input_files["authority"]` (`:1221`) : jamais absent d'un
#: document passant réel. **Volontairement absent : `authority_
#: revocations`.** En production, `--authority-revocations` est un refus
#: pur et simple s'il est fourni (`:1584-1591` : « fournir cet argument
#: est un refus ») — le registre est toujours lu au chemin gouverné, et
#: `input_files["authority_revocations"]` n'est renseigné QUE si
#: l'argument CLI est fourni (`:1228-1229`), ce qui n'arrive jamais en
#: production. L'exiger ici casserait donc tout document de production
#: réel. C'est un vrai manque côté producteur (aucun digest du registre
#: de révocation réellement lu n'est jamais capturé pour un rapport de
#: production), signalé dans le rapport de lot, hors du périmètre de ce
#: module de représentation (ADR-0001) — pas contourné en silence ici.
_REQUIRED_INPUT_FILE_KEYS = frozenset({"catalog", "routing", "rights", "pii", "golden", "authority"})
_REQUIRED_V2_INPUT_FILE_KEYS = frozenset(
    {
        "authorization_set",
        "authority_revocations",
        "catalog",
        "currentness_verification",
        "golden",
        "pii",
        "review_binding_trust_anchor",
        "rights",
        "routing",
    }
)

#: Les neuf invariants de sécurité que `generate_coverage_report` compte
#: (toujours initialisés à zéro puis incrémentés, jamais un sous-ensemble
#: partiel — `h2b_coverage_report.py:1044-1054`) et dont
#: `h2_coverage_gate_pass` exige `all(value == 0 ...)`
#: (`h2b_coverage_report.py:1284-1294`). Round 3 (Codex, PR #104) : sans
#: leur représentation ici, un document falsifié pouvait revendiquer
#: `h2_coverage_gate_pass=true` avec tous les autres prérequis projetés
#: satisfaits, malgré un invariant de sécurité réel (droits, PII,
#: currentness, format, provenance, hachage de contenu, autorité,
#: attribution) en échec — jamais représenté, donc jamais détectable par
#: un vérificateur qui ne reçoit que cette preuve.
_SAFETY_INVARIANT_KEYS = frozenset(
    {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE",
        "INGEST_WITHOUT_PII_CLEARANCE",
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE",
        "INGEST_WITH_UNSUPPORTED_FORMAT",
        "INGEST_WITHOUT_PROVENANCE",
        "INGEST_WITHOUT_CONTENT_SHA",
        "INGEST_WITHOUT_AUTHORITY",
        "INGEST_WITH_SELF_DECLARED_AUTHORITY",
        "INGEST_WITHOUT_ATTRIBUTION_METADATA",
    }
)

_NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


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
    #: Round 4 (Codex, PR #104) : sans identité, `authority_review_
    #: binding_verified=true` ne dit QUI a été revu — un document
    #: falsifié pouvait revendiquer ce booléen vrai sans qu'aucun
    #: vérificateur en aval ne puisse corréler le verdict à une
    #: autorisation précise (ni, par extension, la revérifier contre le
    #: registre de révocation courant via `nexus_contracts.
    #: authorization_revocations`, ADR-0042). Toujours présent dans
    #: `authority_binding["authorization_id"]` dès que `authority_path`
    #: est fourni (`h2b_coverage_report.py:760-785`), donc pour tout
    #: rapport de production passant.
    authorization_id: StrictStr = Field(pattern=_IDENTIFIER)

    # --- Invariants de sécurité (round 3, Codex, PR #104) ------------------
    safety_invariants: dict[str, _NonNegativeInt]

    @model_validator(mode="after")
    def _input_file_digests_cover_the_five_required_proofs(self) -> "H2CoverageEvidenceV1":
        """Un document qui ne porterait qu'une clé arbitraire (ex.
        ``{"placeholder": <hex64>}``) passerait la seule contrainte
        « non vide » sans être lié à aucune des cinq preuves qu'il
        prétend représenter. Les cinq entrées `--catalog`/`--routing`/
        `--rights`/`--pii`/`--golden` sont toutes obligatoires côté
        producteur (Codex P1, PR #104 ; `golden` ajouté round 3) : leur
        absence ici est donc toujours un refus, jamais un document
        partiellement lié."""
        missing = _REQUIRED_INPUT_FILE_KEYS - set(self.input_file_digests)
        if missing:
            raise ValueError(
                f"input_file_digests is missing required key(s) {sorted(missing)!r} — "
                "a document not bound to all five core evidence files is never accepted"
            )
        return self

    @model_validator(mode="after")
    def _safety_invariants_key_set_is_exact(self) -> "H2CoverageEvidenceV1":
        """Le producteur réel compte toujours exactement ces neuf
        invariants (jamais un sous-ensemble, jamais une clé inventée) —
        un champ inconnu ou manquant est refusé plutôt que silencieusement
        ignoré, même discipline que le reste de ce contrat (Codex P1,
        PR #104, round 3)."""
        if set(self.safety_invariants) != _SAFETY_INVARIANT_KEYS:
            raise ValueError(
                "safety_invariants has an unexpected key set "
                f"(got={sorted(self.safety_invariants)}, "
                f"expected={sorted(_SAFETY_INVARIANT_KEYS)}) — an unknown or missing "
                "safety invariant is never silently accepted"
            )
        return self

    @model_validator(mode="after")
    def _gate_pass_implies_its_own_prerequisites(self) -> "H2CoverageEvidenceV1":
        """``h2_coverage_gate_pass`` n'est jamais un fait isolé : le
        producteur réel (`h2b_coverage_report._compute`) ne le rend vrai
        que si `coverage_complete`, `golden_validation_pass`, les deux
        statuts de gate, et la liaison d'autorité complète le sont aussi
        (`h2_coverage_gate_pass = decision_coverage_complete and golden_pass
        and rights_gate_status == "PASS" and pii_gate_status == "PASS" and
        authority_review_binding_verified and authority_revocations_checked
        and ...`). Ceci est une cohérence **structurelle** entre des
        verdicts déjà rendus — pas un recalcul du gate depuis les preuves
        brutes, qui resterait exclusivement dans `rag-pedago` (Codex P1,
        PR #104) : sans ce contrôle, un document falsifié ou substitué
        pourrait revendiquer un succès global tout en enregistrant
        explicitement un échec de couverture ou de gouvernance.

        **Round 2 (Codex, même PR).** Côté producteur réel, le champ
        projeté ``coverage_complete`` n'est PAS ``decision_coverage_
        complete`` (la conjonction brute des quatre sous-vérifications) —
        c'est ``report.coverage_complete``, qui vaut ``h2_coverage_gate_
        pass`` lui-même (`h2b_coverage_report.py`, construction de
        `CoverageReport` : ``coverage_complete=h2_coverage_gate_pass``,
        puis `report_to_h2_coverage_evidence` copie ce champ tel quel).
        Vérifié en lisant le producteur, pas supposé. Cela signifie que le
        contrôle ci-dessus sur ``self.coverage_complete`` ne peut jamais
        détecter une incohérence : dans une donnée réelle, ce champ est
        toujours égal à ``h2_coverage_gate_pass``, jamais une source
        indépendante de vérité. Un document falsifié pouvait donc
        déclarer ``h2_coverage_gate_pass=true`` avec ``coverage_complete=
        true`` (cohérents entre eux, donc acceptés) tout en portant
        ``corpus_match=false``/``sum_equals_total=false``/
        ``zero_overlap=false``/``zero_gap=false``, ou des totaux de
        corpus différents — précisément les quatre sous-vérifications
        dont `decision_coverage_complete` est la conjonction côté
        producteur. Ces quatre champs sont donc exigés vrais, et les
        totaux égaux, indépendamment de ``coverage_complete``.

        **Round 3 (Codex, même PR).** `h2_coverage_gate_pass` exige aussi
        côté producteur `all(value == 0 for value in safety_invariants.
        values())` (`h2b_coverage_report.py:1284-1294`) — neuf compteurs
        de violations (droits, PII, currentness, format, provenance,
        hachage de contenu, autorité, attribution) jusque-là absents de
        ce contrat. Un document falsifié pouvait donc revendiquer
        `h2_coverage_gate_pass=true` avec tous les autres prérequis
        projetés satisfaits, malgré un invariant de sécurité réel en
        échec — jamais représenté, donc jamais détectable."""
        if self.h2_coverage_gate_pass and not (
            self.coverage_complete
            and self.golden_validation_pass
            and self.rights_gate_status == "PASS"
            and self.pii_gate_status == "PASS"
            and self.authority_review_binding_verified
            and self.authority_revocations_checked
            and self.corpus_match
            and self.sum_equals_total
            and self.zero_overlap
            and self.zero_gap
            and self.corpus_total_expected == self.corpus_total_actual
            and all(value == 0 for value in self.safety_invariants.values())
        ):
            raise ValueError(
                "h2_coverage_gate_pass=true is inconsistent with its own prerequisites "
                "(coverage_complete, golden_validation_pass, rights_gate_status, "
                "pii_gate_status, authority_review_binding_verified, "
                "authority_revocations_checked, corpus_match, sum_equals_total, "
                "zero_overlap, zero_gap, corpus_total_expected == corpus_total_actual, "
                "all(safety_invariants.values()) == 0) — a contradictory passing verdict "
                "is never accepted"
            )
        return self

    @staticmethod
    def _digest_map_pattern_ok(values: dict[str, str]) -> bool:
        return all(re.fullmatch(_HEX64, v) is not None for v in values.values())

    def canonical_document(self) -> dict[str, Any]:
        return {
            "authority_review_binding_verified": self.authority_review_binding_verified,
            "authority_revocations_checked": self.authority_revocations_checked,
            "authorization_id": self.authorization_id,
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
            "safety_invariants": dict(sorted(self.safety_invariants.items())),
            "sum_equals_total": self.sum_equals_total,
            "zero_gap": self.zero_gap,
            "zero_overlap": self.zero_overlap,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())


class H2CoverageEvidenceV2(StrictBaseModel):
    """Preuve H2 structurée liée à un set d'autorisations exact."""

    protocol_version: Literal["NEXUS-H2-COVERAGE-EVIDENCE-V2"]
    environment: Literal["production"]

    report_id: StrictStr = Field(min_length=1, max_length=128)
    generated_at: AwareDatetime
    git_commit: StrictStr = Field(pattern=_HEX40)
    producer_version: StrictStr = Field(min_length=1, max_length=128)

    corpus_manifest_sha256: StrictStr = Field(pattern=_HEX64)
    profile_manifest_digest: StrictStr = Field(pattern=_HEX64)
    authorization_set_digest: StrictStr = Field(pattern=_HEX64)
    authorization_count: StrictInt = Field(gt=0)
    authorization_set_verified_at: AwareDatetime
    earliest_review_submitted_at: AwareDatetime
    earliest_review_binding_verified_at: AwareDatetime
    earliest_review_binding_expires_at: AwareDatetime
    input_file_digests: dict[str, StrictStr] = Field(min_length=1)

    corpus_total_expected: StrictInt = Field(ge=0)
    corpus_total_actual: StrictInt = Field(ge=0)
    corpus_match: StrictBool
    sum_equals_total: StrictBool
    zero_overlap: StrictBool
    zero_gap: StrictBool
    coverage_complete: StrictBool

    rights_gate_status: _GATE_STATUS
    pii_gate_status: _GATE_STATUS
    golden_validation_pass: StrictBool
    h2_coverage_gate_pass: StrictBool

    authority_review_bindings_verified: StrictBool
    authority_revocations_checked: StrictBool
    authority_required_count: StrictInt = Field(gt=0)
    authority_covered_count: _NonNegativeInt
    authority_required_set_sha256: StrictStr = Field(pattern=_HEX64)
    authorization_overlap_count: _NonNegativeInt
    authorization_gap_count: _NonNegativeInt
    authorization_extra_count: _NonNegativeInt

    safety_invariants: dict[str, _NonNegativeInt]

    @model_validator(mode="after")
    def _input_file_digests_are_exact(self) -> H2CoverageEvidenceV2:
        if set(self.input_file_digests) != _REQUIRED_V2_INPUT_FILE_KEYS:
            raise ValueError(
                "input_file_digests has an unexpected key set "
                f"(got={sorted(self.input_file_digests)}, "
                f"expected={sorted(_REQUIRED_V2_INPUT_FILE_KEYS)})"
            )
        if not all(
            re.fullmatch(_HEX64, digest) is not None
            for digest in self.input_file_digests.values()
        ):
            raise ValueError("input_file_digests contains a malformed sha256 digest")
        if (
            self.input_file_digests["authorization_set"]
            != self.authorization_set_digest
        ):
            raise ValueError(
                "authorization_set_digest does not match "
                "input_file_digests['authorization_set']"
            )
        return self

    @model_validator(mode="after")
    def _safety_invariants_are_exact(self) -> H2CoverageEvidenceV2:
        if set(self.safety_invariants) != _SAFETY_INVARIANT_KEYS:
            raise ValueError(
                "safety_invariants has an unexpected key set "
                f"(got={sorted(self.safety_invariants)}, "
                f"expected={sorted(_SAFETY_INVARIANT_KEYS)})"
            )
        return self

    @model_validator(mode="after")
    def _passing_gate_is_structurally_consistent(self) -> H2CoverageEvidenceV2:
        if self.h2_coverage_gate_pass and not (
            self.coverage_complete
            and self.golden_validation_pass
            and self.rights_gate_status == "PASS"
            and self.pii_gate_status == "PASS"
            and self.authority_review_bindings_verified
            and self.authority_revocations_checked
            and self.corpus_match
            and self.sum_equals_total
            and self.zero_overlap
            and self.zero_gap
            and self.corpus_total_expected == self.corpus_total_actual
            and self.authorization_count <= self.authority_covered_count
            and self.authority_required_count == self.authority_covered_count
            and self.authority_required_count <= self.corpus_total_actual
            and self.authorization_overlap_count == 0
            and self.authorization_gap_count == 0
            and self.authorization_extra_count == 0
            and all(value == 0 for value in self.safety_invariants.values())
            and self.earliest_review_submitted_at
            <= self.earliest_review_binding_verified_at
            <= self.authorization_set_verified_at
            <= self.generated_at
            < self.earliest_review_binding_expires_at
        ):
            raise ValueError(
                "h2_coverage_gate_pass=true is inconsistent with its own prerequisites"
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "authorization_extra_count": self.authorization_extra_count,
            "authorization_gap_count": self.authorization_gap_count,
            "authorization_overlap_count": self.authorization_overlap_count,
            "authorization_count": self.authorization_count,
            "authorization_set_digest": self.authorization_set_digest,
            "authorization_set_verified_at": _canonical_moment(
                self.authorization_set_verified_at
            ),
            "authority_covered_count": self.authority_covered_count,
            "authority_required_count": self.authority_required_count,
            "authority_required_set_sha256": self.authority_required_set_sha256,
            "authority_review_bindings_verified": self.authority_review_bindings_verified,
            "authority_revocations_checked": self.authority_revocations_checked,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "corpus_match": self.corpus_match,
            "corpus_total_actual": self.corpus_total_actual,
            "corpus_total_expected": self.corpus_total_expected,
            "coverage_complete": self.coverage_complete,
            "earliest_review_binding_expires_at": _canonical_moment(
                self.earliest_review_binding_expires_at
            ),
            "earliest_review_binding_verified_at": _canonical_moment(
                self.earliest_review_binding_verified_at
            ),
            "earliest_review_submitted_at": _canonical_moment(
                self.earliest_review_submitted_at
            ),
            "environment": self.environment,
            "generated_at": _canonical_moment(self.generated_at),
            "git_commit": self.git_commit,
            "golden_validation_pass": self.golden_validation_pass,
            "h2_coverage_gate_pass": self.h2_coverage_gate_pass,
            "input_file_digests": dict(sorted(self.input_file_digests.items())),
            "pii_gate_status": self.pii_gate_status,
            "producer_version": self.producer_version,
            "profile_manifest_digest": self.profile_manifest_digest,
            "protocol_version": self.protocol_version,
            "report_id": self.report_id,
            "rights_gate_status": self.rights_gate_status,
            "safety_invariants": dict(sorted(self.safety_invariants.items())),
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


def parse_h2_coverage_evidence_v2(raw: bytes) -> H2CoverageEvidenceV2:
    """Parse strictement le protocole V2, sans fallback vers V1."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise H2CoverageEvidenceError(
            f"evidence bytes are not valid UTF-8: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise H2CoverageEvidenceError(
            f"evidence bytes are not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise H2CoverageEvidenceError("evidence must be a JSON object")
    if document.get("protocol_version") != H2_COVERAGE_EVIDENCE_V2_PROTOCOL_VERSION:
        raise H2CoverageEvidenceError(
            "evidence protocol_version is not "
            f"{H2_COVERAGE_EVIDENCE_V2_PROTOCOL_VERSION!r}"
        )
    try:
        parsed = H2CoverageEvidenceV2.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - strict parsing boundary
        raise H2CoverageEvidenceError(
            f"evidence failed strict validation: {exc}"
        ) from exc
    if parsed.canonical_bytes() != raw:
        raise H2CoverageEvidenceError(
            "evidence bytes are not in canonical form — the reviewed bytes and "
            "their canonical re-serialization differ. Commit the canonical form."
        )
    return parsed
