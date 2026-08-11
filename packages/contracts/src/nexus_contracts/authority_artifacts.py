"""Artefacts d'autorité canoniques — LOT41A (ADR-0032) et LOT42 (ADR-0033).

Remédiation GATE H1, items **B** et **E**.

**Le problème résolu ici.** Une review GitHub ``APPROVED`` prouve qu'un
humain a lu *un diff précis, à un commit précis*. Elle ne prouve
strictement rien sur un fichier local que l'opérateur passerait ensuite en
argument à un outil. Tant que la décision enregistrée en base est
construite depuis un fichier opérateur indépendant, la review et
l'enregistrement ne sont liés par rien : l'opérateur peut faire approuver
un scope étroit puis enregistrer un scope large.

Ce module supprime cet écart en définissant l'**artefact canonique** qui
*est* la décision. La chaîne devient :

    PR approuvée -> head SHA exact -> blob Git exact (chemin canonique)
    -> octets exacts -> parse canonique -> digest d'autorisation
    -> ligne PostgreSQL

Trois propriétés rendent ce lien inviolable :

1. **Chemin canonique déterministe** — ``canonical_authorization_path``
   dérive le chemin de l'identifiant seul. L'opérateur ne choisit jamais
   quel fichier est relu.
2. **Sérialisation canonique déterministe** — ``canonical_bytes`` produit
   une forme unique par valeur (clés triées, indentation fixe, domaines et
   listes normalisés, dates en UTC). Les vérificateurs exigent l'égalité
   **octet à octet** entre le blob relu et la re-sérialisation de son
   parse : un fichier commité non canonique est refusé, donc les octets
   revus par l'humain sont exactement ceux dont le digest est calculé.
3. **Validation stricte** — ``extra="forbid"`` hérité de
   ``StrictBaseModel`` : un champ inconnu glissé dans le JSON ne peut pas
   voyager silencieusement à côté de la décision revue.

Aucun champ de confiance figé n'existe ici (``approved``, ``valid``) — ce
module ne décrit qu'une *proposition* de décision. Sa validité n'est
jamais un booléen stocké : elle est recalculée en direct contre GitHub par
``ingestor.ingestion_control.scope_authority`` /
``ingestor.ingestion_control.publication_attestation``.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, TypeAlias

from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from nexus_contracts.document import Rights, StrictBaseModel
from nexus_contracts.ingestion import ResourceScope

#: Version de protocole des artefacts LOT41A — jamais implicite, jamais
#: absente : un artefact sans version ne peut pas être parsé.
LOT41A_PROTOCOL_VERSION = "LOT41A-V1"

#: Version content-bound introduite par ADR-0034. La constante historique
#: ci-dessus reste volontairement V1 : changer sa valeur modifierait
#: silencieusement le sens des intégrations V1 existantes.
LOT41A_V2_PROTOCOL_VERSION = "LOT41A-V2"

#: Version de protocole des artefacts de revue de publication LOT42.
#: Reste volontairement ``LOT42-V1`` : cette constante nomme la structure
#: historique, qui garde exactement le sens qu'elle avait quand des humains
#: l'ont relue. La faire pointer vers V2 réétiquetterait ces relectures.
LOT42_PROTOCOL_VERSION = "LOT42-V1"

#: Version attribution-bound introduite par ADR-0035. Un artefact V2 nomme
#: le digest d'attribution du control plane : l'humain qui approuve les
#: octets approuve donc *aussi* les quatre faits d'attribution publiés.
#: Seule cette version peut encore être proposée à la revue, produire une
#: attestation et autoriser une publication (ADR-0035 § 6).
LOT42_V2_PROTOCOL_VERSION = "LOT42-V2"

#: Seule valeur de décision acceptée — jamais un texte libre (ADR-0032 § 2).
AUTHORIZE_INGESTION_SCOPE_DECISION = "AUTHORIZE_INGESTION_SCOPE"

#: Seule valeur de décision acceptée côté publication (ADR-0033 § 2).
AUTHORIZE_PUBLICATION_DECISION = "AUTHORIZE_PUBLICATION"

#: Répertoires canoniques versionnés dans Git. Un artefact d'autorité n'est
#: jamais relu ailleurs — le chemin est dérivé de l'identifiant, jamais
#: fourni par l'opérateur.
AUTHORIZATIONS_DIR = "governance/authorizations"
PUBLICATION_REVIEWS_DIR = "governance/publication-reviews"

#: Identifiants : ASCII minuscule strict. Interdit tout séparateur de
#: chemin, tout ``..``, toute majuscule — le chemin canonique dérivé ne peut
#: donc jamais sortir du répertoire d'artefacts ni dépendre de la casse du
#: système de fichiers.
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

#: Nom d'hôte ASCII déjà normalisé (punycode pour tout domaine non-ASCII).
#: Refuser l'unicode ici est délibéré : deux écritures unicode distinctes
#: peuvent se normaliser vers le même hôte, ce qui rendrait la comparaison
#: « hostname ∈ allowed_domains » ambiguë au moment de l'enforcement.
_HOSTNAME_PATTERN = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)

_HEX64 = r"^[0-9a-f]{64}$"

#: Indentation de la forme canonique. Volontairement lisible : ces octets
#: sont ceux qu'un humain relit dans le diff de la PR d'autorité. Une forme
#: compacte sur une seule ligne serait tout aussi déterministe mais
#: rendrait la review humaine — la seule chose qui donne sa valeur à toute
#: cette chaîne — pratiquement impossible.
_CANONICAL_INDENT = 2


class CanonicalArtifactError(ValueError):
    """Les octets fournis ne sont pas la forme canonique de leur contenu —
    refus explicite, jamais une normalisation silencieuse (qui casserait le
    lien entre les octets revus par l'humain et le digest enregistré)."""


def normalize_hostname(value: str) -> str:
    """Forme canonique d'un nom d'hôte : minuscule, sans point final, sans
    espace. Lève ``ValueError`` sur toute forme non normalisable (schéma,
    port, chemin, wildcard, unicode, adresse IP littérale)."""
    candidate = value.strip().lower().rstrip(".")
    if not candidate:
        raise ValueError("hostname must not be blank")
    if candidate == "*" or candidate.startswith("*."):
        raise ValueError(f"wildcard hostname is never allowed, got {value!r}")
    for forbidden in ("/", ":", "?", "#", "@", " ", "\t"):
        if forbidden in candidate:
            raise ValueError(
                f"hostname must be a bare host, got {value!r} "
                f"(contains {forbidden!r} — scheme/port/path are never accepted)"
            )
    if not _HOSTNAME_PATTERN.fullmatch(candidate):
        raise ValueError(
            f"hostname {value!r} is not a normalized ASCII dotted host name "
            "(non-ASCII hosts must be committed in punycode form)"
        )
    if re.fullmatch(r"[0-9.]+", candidate):
        raise ValueError(
            f"hostname {value!r} looks like a literal IP address — an "
            "authorization always names a host, never an address"
        )
    return candidate


def _normalized_sorted(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    cleaned = []
    for raw in values:
        item = raw.strip()
        if not item:
            raise ValueError(f"{label} must never contain a blank entry")
        cleaned.append(item)
    unique = sorted(set(cleaned))
    if len(unique) != len(cleaned):
        raise ValueError(f"{label} must not contain duplicates, got {list(values)!r}")
    return tuple(unique)


def _canonical_datetime(value: datetime) -> str:
    """UTC, précision microseconde fixe, suffixe ``Z``. Une même instant
    exprimé dans deux fuseaux produit donc exactement la même chaîne."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _canonical_scope(scope: ResourceScope) -> dict[str, Any]:
    """Les dix dimensions, clés triées et ``audience`` trié.

    ``visibility`` est un ``Literal[str]`` (jamais une Enum) dans
    ``ResourceScope`` — repris tel quel ici, sans ``.value``, pour rester
    exactement la même valeur que celle stockée en base."""
    return {
        "audience": sorted(a.value for a in scope.audience),
        "candidat": scope.candidat.value,
        "collection": scope.collection,
        "matiere": scope.matiere,
        "niveau": scope.niveau.value,
        "programme_version": scope.programme_version,
        "school_year": scope.school_year,
        "tenant": scope.tenant,
        "visibility": scope.visibility,
        "voie": scope.voie.value,
    }


def _dump_canonical(document: dict[str, Any]) -> bytes:
    """Encodage canonique commun : clés triées, indentation fixe, UTF-8,
    saut de ligne final (un fichier texte versionné en a toujours un)."""
    return (
        json.dumps(
            document,
            sort_keys=True,
            indent=_CANONICAL_INDENT,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


class ScopeAuthorizationArtifact(StrictBaseModel):
    """Décision d'autorisation de scope LOT41A **dans son intégralité**.

    C'est ce document, et lui seul, qu'un humain approuve : aucune donnée
    de la ligne PostgreSQL enregistrée n'existe en dehors de lui (hormis
    l'évidence GitHub, qui est relue en direct et jamais fournie par
    l'opérateur).

    L'évidence GitHub n'est délibérément **pas** un champ de cet artefact :
    un artefact ne peut pas contenir la preuve de sa propre approbation
    (elle n'existe qu'après le commit qui le porte).
    """

    protocol_version: Literal["LOT41A-V1"]
    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    decision: Literal["AUTHORIZE_INGESTION_SCOPE"]
    scope: ResourceScope
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    profile_id: StrictStr = Field(min_length=1)
    profile_version: StrictStr = Field(min_length=1)
    profile_fingerprint: StrictStr = Field(pattern=_HEX64)
    allowed_domains: tuple[StrictStr, ...] = Field(min_length=1)
    rights_categories: tuple[Rights, ...] = Field(min_length=1)
    exclusions: tuple[StrictStr, ...] = Field(default=())
    pii_absence_attested: StrictBool
    pii_absence_evidence: StrictStr = Field(min_length=1)
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @field_validator("authorization_id")
    @classmethod
    def _identifier_is_canonical(cls, value: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(
                f"authorization_id {value!r} must match {_IDENTIFIER_PATTERN.pattern} "
                "— it is used to derive the canonical artifact path and must "
                "never be able to escape its directory"
            )
        return value

    @field_validator("allowed_domains")
    @classmethod
    def _domains_are_normalized(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_hostname(v) for v in values)
        unique = sorted(set(normalized))
        if len(unique) != len(normalized):
            raise ValueError(
                f"allowed_domains must not contain duplicates after "
                f"normalization, got {list(values)!r}"
            )
        # L'entrée elle-même doit déjà être normalisée et triée — pas
        # seulement normalisable. Accepter ``["Eduscol.Education.FR"]`` en le
        # corrigeant en silence romprait la canonicité octet à octet : deux
        # fichiers différents produiraient la même décision, et le digest ne
        # désignerait plus des octets uniques.
        if list(values) != unique:
            raise ValueError(
                "allowed_domains must be committed already normalized and "
                f"sorted; expected {unique!r}, got {list(values)!r}"
            )
        return tuple(unique)

    @field_validator("rights_categories")
    @classmethod
    def _rights_are_sorted_and_unique(cls, values: tuple[Rights, ...]) -> tuple[Rights, ...]:
        raw = [v.value for v in values]
        unique = sorted(set(raw))
        if len(unique) != len(raw):
            raise ValueError(f"rights_categories must not contain duplicates, got {raw!r}")
        if raw != unique:
            raise ValueError(
                f"rights_categories must be committed sorted; expected {unique!r}, got {raw!r}"
            )
        if Rights.unknown.value in raw:
            raise ValueError(
                "rights_categories must never contain 'unknown' — an "
                "authorization can never pre-authorize undetermined rights"
            )
        return values

    @field_validator("exclusions")
    @classmethod
    def _exclusions_are_normalized(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = _normalized_sorted(values, label="exclusions")
        if list(values) != list(normalized):
            raise ValueError(
                f"exclusions must be committed normalized and sorted; "
                f"expected {list(normalized)!r}, got {list(values)!r}"
            )
        return normalized

    @model_validator(mode="after")
    def _validity_window_is_coherent(self) -> ScopeAuthorizationArtifact:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        return self

    @model_validator(mode="after")
    def _pii_attestation_is_asserted(self) -> ScopeAuthorizationArtifact:
        if not self.pii_absence_attested:
            raise ValueError(
                "pii_absence_attested must be true — this release ingests no "
                "PII, so an authorization can never be constructed for a scope "
                "where PII absence is not attested"
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "allowed_domains": list(self.allowed_domains),
            "authorization_id": self.authorization_id,
            "decision": self.decision,
            "exclusions": list(self.exclusions),
            "manifest_digest": self.manifest_digest,
            "pii_absence_attested": self.pii_absence_attested,
            "pii_absence_evidence": self.pii_absence_evidence,
            "profile_fingerprint": self.profile_fingerprint,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "protocol_version": self.protocol_version,
            "rights_categories": [r.value for r in self.rights_categories],
            "scope": _canonical_scope(self.scope),
            "valid_from": _canonical_datetime(self.valid_from),
            "valid_until": _canonical_datetime(self.valid_until),
        }

    def canonical_bytes(self) -> bytes:
        return _dump_canonical(self.canonical_document())

    def digest(self) -> str:
        """SHA-256 de la forme canonique — l'identité cryptographique de la
        décision, recalculée intégralement à chaque usage, jamais lue."""
        return sha256(self.canonical_bytes()).hexdigest()

    def canonical_path(self) -> str:
        return canonical_authorization_path(self.authorization_id)


# Alias public explicite : le nom historique reste l'exact modèle V1 et ses
# octets canoniques ne changent pas avec l'introduction de V2.
ScopeAuthorizationArtifactV1 = ScopeAuthorizationArtifact


class ScopeAuthorizationArtifactV2(StrictBaseModel):
    """Autorisation LOT41A liée positivement aux contenus exacts revus.

    La liste est exigée sous sa forme déjà canonique. Aucune casse, aucun
    ordre et aucun doublon n'est corrigé en silence : les octets visibles
    dans la PR sont donc ceux qui déterminent la décision et son digest.
    """

    protocol_version: Literal["LOT41A-V2"]
    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    decision: Literal["AUTHORIZE_INGESTION_SCOPE"]
    scope: ResourceScope
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    profile_id: StrictStr = Field(min_length=1)
    profile_version: StrictStr = Field(min_length=1)
    profile_fingerprint: StrictStr = Field(pattern=_HEX64)
    allowed_domains: tuple[StrictStr, ...] = Field(min_length=1)
    rights_categories: tuple[Rights, ...] = Field(min_length=1)
    exclusions: tuple[StrictStr, ...] = Field(default=())
    pii_absence_attested: StrictBool
    pii_absence_evidence: StrictStr = Field(min_length=1)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    allowed_content_sha256: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("authorization_id")
    @classmethod
    def _identifier_is_canonical(cls, value: str) -> str:
        return ScopeAuthorizationArtifactV1._identifier_is_canonical(value)

    @field_validator("allowed_domains")
    @classmethod
    def _domains_are_normalized(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return ScopeAuthorizationArtifactV1._domains_are_normalized(values)

    @field_validator("rights_categories")
    @classmethod
    def _rights_are_sorted_and_unique(
        cls, values: tuple[Rights, ...]
    ) -> tuple[Rights, ...]:
        return ScopeAuthorizationArtifactV1._rights_are_sorted_and_unique(values)

    @field_validator("exclusions")
    @classmethod
    def _exclusions_are_normalized(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return ScopeAuthorizationArtifactV1._exclusions_are_normalized(values)

    @field_validator("allowed_content_sha256")
    @classmethod
    def _content_allowlist_is_canonical(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        for value in values:
            if not re.fullmatch(_HEX64[1:-1], value):
                raise ValueError(
                    "allowed_content_sha256 entries must be exactly 64 "
                    "lowercase hexadecimal characters"
                )
        if len(set(values)) != len(values):
            raise ValueError("allowed_content_sha256 must not contain duplicates")
        expected = sorted(values)
        if list(values) != expected:
            raise ValueError(
                "allowed_content_sha256 must be committed sorted; "
                f"expected {expected!r}, got {list(values)!r}"
            )
        return values

    @model_validator(mode="after")
    def _validity_window_is_coherent(self) -> ScopeAuthorizationArtifactV2:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        return self

    @model_validator(mode="after")
    def _pii_attestation_is_asserted(self) -> ScopeAuthorizationArtifactV2:
        if not self.pii_absence_attested:
            raise ValueError(
                "pii_absence_attested must be true — this release ingests no "
                "PII, so an authorization can never be constructed for a scope "
                "where PII absence is not attested"
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "allowed_content_sha256": list(self.allowed_content_sha256),
            "allowed_domains": list(self.allowed_domains),
            "authorization_id": self.authorization_id,
            "decision": self.decision,
            "exclusions": list(self.exclusions),
            "manifest_digest": self.manifest_digest,
            "pii_absence_attested": self.pii_absence_attested,
            "pii_absence_evidence": self.pii_absence_evidence,
            "profile_fingerprint": self.profile_fingerprint,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "protocol_version": self.protocol_version,
            "rights_categories": [r.value for r in self.rights_categories],
            "scope": _canonical_scope(self.scope),
            "valid_from": _canonical_datetime(self.valid_from),
            "valid_until": _canonical_datetime(self.valid_until),
        }

    def canonical_bytes(self) -> bytes:
        return _dump_canonical(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()

    def canonical_path(self) -> str:
        return canonical_authorization_path(self.authorization_id)


ScopeAuthorizationArtifactAny: TypeAlias = (
    ScopeAuthorizationArtifactV1 | ScopeAuthorizationArtifactV2
)


class PublicationReviewArtifact(StrictBaseModel):
    """Décision de publication LOT42 **dans son intégralité** (item E).

    Tous les champs techniques proviennent des faits durables du pipeline
    (tables ``resources``/``artifacts``/``resource_candidates`` et
    ``workflow_events`` append-only) — jamais d'une affirmation libre de
    l'opérateur. L'artefact est *produit* depuis la base, revu par un
    humain, puis relu depuis le blob Git approuvé et **recomparé à la
    base** avant tout enregistrement : une divergence DB ↔ artefact est un
    refus.
    """

    protocol_version: Literal["LOT42-V1"]
    review_id: StrictStr = Field(min_length=1, max_length=128)
    decision: Literal["AUTHORIZE_PUBLICATION"]
    resource_id: StrictStr = Field(pattern=r"^[0-9a-f-]{36}$")
    artifact_id: StrictStr = Field(pattern=r"^[0-9a-f-]{36}$")
    collection: StrictStr = Field(min_length=1)
    canonical_url: StrictStr = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HEX64)
    scope_authorization_id: StrictStr = Field(min_length=1, max_length=128)
    profile_id: StrictStr = Field(min_length=1)
    profile_version: StrictStr = Field(min_length=1)
    profile_fingerprint: StrictStr = Field(pattern=_HEX64)
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    rights_status: Rights
    rights_assessed_at: AwareDatetime
    quality_passed: StrictBool
    #: Digest du QualityReport complet — jamais un score scalaire. Les
    #: heuristiques de qualité de ce lot sont des placeholders explicites ;
    #: les résumer en un « score » leur donnerait une autorité qu'elles
    #: n'ont pas. Le digest rend le rapport comparable sans rien affirmer.
    quality_report_digest: StrictStr = Field(pattern=_HEX64)
    quality_assessed_at: AwareDatetime
    gate_passed: StrictBool
    gate_name: StrictStr = Field(min_length=1)
    gate_evaluated_at: AwareDatetime
    #: Identifiants des ``workflow_events`` append-only qui portent chacun
    #: de ces faits — l'artefact ne peut pas affirmer un résultat sans
    #: nommer l'événement durable qui l'a produit.
    evidence_event_ids: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("review_id", "scope_authorization_id")
    @classmethod
    def _identifier_is_canonical(cls, value: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(
                f"identifier {value!r} must match {_IDENTIFIER_PATTERN.pattern}"
            )
        return value

    @field_validator("evidence_event_ids")
    @classmethod
    def _events_are_sorted_uuids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not re.fullmatch(r"[0-9a-f-]{36}", value):
                raise ValueError(f"evidence_event_ids entry {value!r} is not a UUID")
        unique = sorted(set(values))
        if list(values) != unique:
            raise ValueError(
                f"evidence_event_ids must be committed sorted and unique; "
                f"expected {unique!r}, got {list(values)!r}"
            )
        return tuple(unique)

    @model_validator(mode="after")
    def _negative_results_are_never_authorized(self) -> PublicationReviewArtifact:
        """Item F, première barrière : un artefact de revue *ne peut pas
        exister* pour une chaîne négative. Le refus n'attend donc pas la
        vérification live — la décision négative est irreprésentable."""
        if not self.quality_passed:
            raise ValueError(
                "quality_passed must be true — a publication review artifact "
                "can never be constructed for a resource that failed quality"
            )
        if not self.gate_passed:
            raise ValueError(
                "gate_passed must be true — a publication review artifact can "
                "never be constructed for a resource that failed the gate"
            )
        if self.rights_status == Rights.unknown:
            raise ValueError(
                "rights_status must never be 'unknown' in a publication review "
                "artifact — undetermined rights are never publishable"
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "canonical_url": self.canonical_url,
            "collection": self.collection,
            "content_sha256": self.content_sha256,
            "decision": self.decision,
            "evidence_event_ids": list(self.evidence_event_ids),
            "gate_evaluated_at": _canonical_datetime(self.gate_evaluated_at),
            "gate_name": self.gate_name,
            "gate_passed": self.gate_passed,
            "manifest_digest": self.manifest_digest,
            "profile_fingerprint": self.profile_fingerprint,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "protocol_version": self.protocol_version,
            "quality_assessed_at": _canonical_datetime(self.quality_assessed_at),
            "quality_passed": self.quality_passed,
            "quality_report_digest": self.quality_report_digest,
            "resource_id": self.resource_id,
            "review_id": self.review_id,
            "rights_assessed_at": _canonical_datetime(self.rights_assessed_at),
            "rights_status": self.rights_status.value,
            "scope_authorization_id": self.scope_authorization_id,
        }

    def canonical_bytes(self) -> bytes:
        return _dump_canonical(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()

    def canonical_path(self) -> str:
        return canonical_publication_review_path(
            review_id=self.review_id, digest=self.digest()
        )


#: Alias explicite : la classe non suffixée *est* la structure V1, comme
#: pour ``ScopeAuthorizationArtifactV1``. Elle reste lisible pour l'audit
#: historique et ne peut plus rien autoriser (ADR-0035 § 6).
PublicationReviewArtifactV1 = PublicationReviewArtifact


class PublicationReviewArtifactV2(PublicationReviewArtifact):
    """Décision de publication LOT42-V2 — *attribution-bound* (ADR-0035).

    V1 laissait les quatre faits d'attribution (``source_label``,
    ``official``, ``source_kind``, ``type_doc``) hors des octets relus :
    l'humain approuvait une publication sans jamais voir ce qui serait
    publié *comme* provenance. V2 rend ce silence impossible en plaçant le
    digest calculé par le control plane dans les octets canoniques eux-
    mêmes. Le champ étant obligatoire, un artefact V2 sans lui n'est pas
    « invalide » : il est **irreprésentable**.

    Conséquence voulue et non contournable : le digest entre dans
    ``canonical_bytes()``, donc dans ``digest()``, donc dans
    ``canonical_path()`` et dans le challenge soumis à l'humain. Modifier
    l'attribution après la revue change le chemin canonique — les octets
    approuvés ne peuvent plus être retrouvés là où l'attestation les
    cherche.
    """

    protocol_version: Literal["LOT42-V2"]  # type: ignore[assignment]

    #: Digest ``NEXUS-ATTRIBUTION-V1`` de la ligne
    #: ``ingestion_control.artifact_attributions`` de cet artefact, tel que
    #: calculé par la colonne générée du control plane. Jamais recalculé
    #: côté client, jamais « reconstruit » : l'artefact cite la base.
    attributed_facts_digest: StrictStr = Field(pattern=_HEX64)

    def canonical_document(self) -> dict[str, Any]:
        document = super().canonical_document()
        document["attributed_facts_digest"] = self.attributed_facts_digest
        return document


PublicationReviewArtifactAny: TypeAlias = (
    PublicationReviewArtifactV1 | PublicationReviewArtifactV2
)


def canonical_authorization_path(authorization_id: str) -> str:
    """Chemin Git canonique déterministe d'une autorisation. Dérivé de
    l'identifiant seul — jamais choisi par l'opérateur, jamais capable de
    désigner un fichier hors de ``governance/authorizations/``."""
    if not _IDENTIFIER_PATTERN.fullmatch(authorization_id):
        raise ValueError(
            f"authorization_id {authorization_id!r} must match "
            f"{_IDENTIFIER_PATTERN.pattern} before a canonical path can be derived"
        )
    return f"{AUTHORIZATIONS_DIR}/{authorization_id}.json"


def canonical_publication_review_path(*, review_id: str, digest: str) -> str:
    """Chemin Git canonique d'un artefact de revue de publication. Le
    digest fait partie du nom : une décision modifiée ne peut jamais
    réutiliser le chemin d'une décision déjà approuvée."""
    if not _IDENTIFIER_PATTERN.fullmatch(review_id):
        raise ValueError(f"review_id {review_id!r} must match {_IDENTIFIER_PATTERN.pattern}")
    if not re.fullmatch(_HEX64[1:-1], digest):
        raise ValueError(f"digest {digest!r} must be 64 lowercase hex characters")
    return f"{PUBLICATION_REVIEWS_DIR}/{review_id}-{digest}.json"


def _parse_canonical(raw: bytes, model: type[Any]) -> Any:
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CanonicalArtifactError(f"artifact bytes are not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CanonicalArtifactError(f"artifact bytes are not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CanonicalArtifactError("artifact must be a JSON object")
    try:
        parsed = model.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing, jamais silencieuse
        raise CanonicalArtifactError(f"artifact failed strict validation: {exc}") from exc
    reserialized = parsed.canonical_bytes()
    if reserialized != raw:
        raise CanonicalArtifactError(
            "artifact bytes are not in canonical form — the reviewed bytes and "
            "their canonical re-serialization differ, so the human review "
            "cannot be bound to this content. Commit the canonical form."
        )
    return parsed


def parse_scope_authorization_artifact(raw: bytes) -> ScopeAuthorizationArtifactAny:
    """Parse strict + exigence de canonicité **octet à octet**.

    L'égalité octet à octet est le cœur de l'item B : sans elle, deux
    fichiers différents (espaces, ordre des clés, casse d'un domaine)
    pourraient produire la même décision logique avec des digests
    différents — ou pire, un digest identique pour des octets que l'humain
    n'a pas relus."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CanonicalArtifactError(f"artifact bytes are not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CanonicalArtifactError(f"artifact bytes are not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CanonicalArtifactError("artifact must be a JSON object")

    protocol_version = document.get("protocol_version")
    model: type[ScopeAuthorizationArtifactAny]
    if protocol_version == LOT41A_PROTOCOL_VERSION:
        model = ScopeAuthorizationArtifactV1
    elif protocol_version == LOT41A_V2_PROTOCOL_VERSION:
        model = ScopeAuthorizationArtifactV2
    else:
        raise CanonicalArtifactError(
            f"unsupported scope authorization protocol_version {protocol_version!r}"
        )
    artifact: ScopeAuthorizationArtifactAny = _parse_canonical(raw, model)
    return artifact


def parse_publication_review_artifact(raw: bytes) -> PublicationReviewArtifactAny:
    """Même discipline canonique que ``parse_scope_authorization_artifact``,
    appliquée à la décision de publication LOT42 (item E).

    Dispatch **exact** sur ``protocol_version`` : V1 et V2 ne sont jamais
    interchangeables, et une version inconnue est refusée plutôt que
    devinée. V1 reste parsable pour l'audit historique ; c'est aux
    appelants qui autorisent quelque chose d'exiger V2 (ADR-0035 § 6)."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CanonicalArtifactError(f"artifact bytes are not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CanonicalArtifactError(f"artifact bytes are not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CanonicalArtifactError("artifact must be a JSON object")

    protocol_version = document.get("protocol_version")
    model: type[PublicationReviewArtifactAny]
    if protocol_version == LOT42_PROTOCOL_VERSION:
        model = PublicationReviewArtifactV1
    elif protocol_version == LOT42_V2_PROTOCOL_VERSION:
        model = PublicationReviewArtifactV2
    else:
        raise CanonicalArtifactError(
            f"unsupported publication review protocol_version {protocol_version!r}"
        )
    artifact: PublicationReviewArtifactAny = _parse_canonical(raw, model)
    return artifact


def require_publication_review_v2(
    artifact: PublicationReviewArtifactAny,
) -> PublicationReviewArtifactV2:
    """Barrière unique par laquelle passe tout appelant qui *autorise*
    quelque chose à partir d'un artefact de revue.

    Un artefact V1 est refusé ici, pas plus loin : il n'a jamais lié la
    provenance publiée à la relecture humaine, donc aucune attestation
    et aucune publication ne peut s'en réclamer sous ce runtime."""
    if not isinstance(artifact, PublicationReviewArtifactV2):
        raise CanonicalArtifactError(
            f"publication review artifact is {artifact.protocol_version}, but only "
            f"{LOT42_V2_PROTOCOL_VERSION} may be proposed for review, produce an "
            "attestation or authorize a publication — a "
            f"{LOT42_PROTOCOL_VERSION} artifact never bound the published "
            "attribution facts to the human review (ADR-0035). It is readable "
            "for audit only and is never relabelled automatically."
        )
    return artifact


def git_blob_sha1(raw: bytes) -> str:
    """SHA-1 de l'objet blob Git de ces octets exacts.

    Permet de recouper le digest canonique avec l'identifiant que GitHub
    renvoie pour le fichier : deux chemins indépendants doivent désigner
    les mêmes octets, sinon la relecture est refusée."""
    from hashlib import sha1

    header = f"blob {len(raw)}\0".encode()
    return sha1(header + raw, usedforsecurity=False).hexdigest()  # noqa: S324


__all__ = [
    "AUTHORIZATIONS_DIR",
    "AUTHORIZE_INGESTION_SCOPE_DECISION",
    "AUTHORIZE_PUBLICATION_DECISION",
    "CanonicalArtifactError",
    "LOT41A_PROTOCOL_VERSION",
    "LOT41A_V2_PROTOCOL_VERSION",
    "LOT42_PROTOCOL_VERSION",
    "LOT42_V2_PROTOCOL_VERSION",
    "PUBLICATION_REVIEWS_DIR",
    "PublicationReviewArtifact",
    "PublicationReviewArtifactAny",
    "PublicationReviewArtifactV1",
    "PublicationReviewArtifactV2",
    "ScopeAuthorizationArtifact",
    "ScopeAuthorizationArtifactAny",
    "ScopeAuthorizationArtifactV1",
    "ScopeAuthorizationArtifactV2",
    "canonical_authorization_path",
    "canonical_publication_review_path",
    "git_blob_sha1",
    "normalize_hostname",
    "parse_publication_review_artifact",
    "parse_scope_authorization_artifact",
    "require_publication_review_v2",
]
