"""Preuves scellées consommées par le worker — PII et droits.

**Le défaut fermé ici.** Le worker décidait deux choses sans preuve :

``pii_detected = False``
    un fait inventé, écrit en dur, qui traversait le point de contrôle PII
    sans que rien ne l'ait établi ;
``license=None`` puis ``artifact.license``
    une valeur venue du *payload du job*, donc de l'opérateur qui soumet
    la ressource. Un champ que l'appelant contrôle ne peut pas décider de
    ses propres droits.

Les deux sont remplacés par des registres chargés **une fois au
démarrage**, vérifiés contre des digests attendus, et interrogés par SHA
de contenu. Recharger un fichier mutable à chaque job rouvrirait
exactement la faille : un opérateur pourrait éditer la preuve entre deux
ressources et la modification ne serait jamais revérifiée.

**Fail-closed par construction.** Aucune méthode ne rend « inconnu » ou
``None`` : soit la preuve existe et couvre le contenu exact, soit l'appel
lève. Une ressource dont les droits ou le statut PII ne peuvent pas être
prouvés n'est pas une ressource dégradée — c'est une ressource qu'on ne
sait pas publier.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from nexus_contracts.document import Rights

#: Statuts de scan PII qui autorisent la suite du pipeline. Un seul.
PII_CLEARED = "CLEARED"

#: Type de preuve attendu — un document d'un autre genre, même bien formé,
#: ne décrit pas un scan de corpus.
PII_EVIDENCE_KIND = "REAL_CORPUS_PII_SCAN"

#: Zone du corpus institutionnel couverte par la décision humaine Nexus
#: Réussite enregistrée dans le registre de droits.
EDUSCOL_ZONE = "01_EDUSCOL_OFFICIEL/"

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class SealedEvidenceError(RuntimeError):
    """La preuve ne couvre pas ce contenu — refus explicite.

    Jamais dégradée en avertissement : publier sans preuve et publier
    contre une preuve produisent le même résultat pour l'élève."""


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_digest(path: Path, expected: str, *, label: str) -> str:
    if not _SHA256.match(expected):
        raise SealedEvidenceError(
            f"expected {label} digest must be a lowercase 64-hex SHA-256"
        )
    actual = _digest(path)
    if actual != expected:
        raise SealedEvidenceError(
            f"{label} at {path.name} hashes to {actual}, not the expected "
            f"{expected} — the file on disk is not the evidence that was approved"
        )
    return actual


# ─────────────────────────────────────────────────────────────────────────
# PII
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PIIClearance:
    """La preuve qu'un contenu précis a été scanné et déclaré propre."""

    content_sha256: str
    pages_scanned: int
    characters_scanned: int
    evidence_sha256: str

    @property
    def pii_detected(self) -> bool:
        """Toujours ``False`` : cet objet n'existe que pour un CLEARED.

        La valeur n'est pas un champ modifiable — c'est la conséquence
        d'avoir obtenu la clairance, ce qui interdit de la fabriquer."""
        return False


@dataclass(frozen=True)
class VerifiedPIIEvidenceRegistry:
    """Résultats de scan PII, indexés par SHA de contenu.

    Immuable et chargé une fois : le worker interroge une structure en
    mémoire dont l'identité a été prouvée au démarrage."""

    evidence_sha256: str
    corpus_manifest_sha256: str
    policy_sha256: str
    _by_content: dict[str, dict[str, Any]]

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_evidence_sha256: str,
        expected_corpus_manifest_sha256: str,
    ) -> VerifiedPIIEvidenceRegistry:
        evidence_sha = _require_digest(
            path, expected_evidence_sha256, label="PII evidence"
        )
        document = json.loads(path.read_text(encoding="utf-8"))

        if document.get("evidence_kind") != PII_EVIDENCE_KIND:
            raise SealedEvidenceError(
                f"evidence_kind is {document.get('evidence_kind')!r}, expected "
                f"{PII_EVIDENCE_KIND!r}"
            )
        manifest = document.get("corpus_manifest_sha256")
        if manifest != expected_corpus_manifest_sha256:
            raise SealedEvidenceError(
                "the PII scan describes corpus manifest "
                f"{manifest!r}, not {expected_corpus_manifest_sha256!r} — a scan "
                "of a different corpus proves nothing about this one"
            )
        if document.get("remote_access_mode") != "READ_ONLY":
            raise SealedEvidenceError("the PII scan was not read-only")
        if document.get("remote_write_operations") not in (0, None):
            raise SealedEvidenceError("the PII scan reports write operations")
        for flag in ("raw_pii_in_output", "raw_pii_in_logs"):
            if document.get(flag) is not False:
                raise SealedEvidenceError(
                    f"{flag} is not false — the evidence itself may carry personal "
                    "data, which must never enter this pipeline"
                )

        results = document.get("results")
        if not isinstance(results, list) or not results:
            raise SealedEvidenceError("the PII scan carries no result")

        by_content: dict[str, dict[str, Any]] = {}
        for entry in results:
            sha = entry.get("content_sha256")
            if not isinstance(sha, str) or not _SHA256.match(sha):
                raise SealedEvidenceError("a PII result carries no valid content SHA")
            if sha in by_content:
                raise SealedEvidenceError(
                    f"content {sha} appears twice in the PII scan — which of the "
                    "two verdicts applies cannot be decided"
                )
            by_content[sha] = entry

        return cls(
            evidence_sha256=evidence_sha,
            corpus_manifest_sha256=str(manifest),
            policy_sha256=str(document.get("policy_sha256", "")),
            _by_content=by_content,
        )

    def verify_content_clearance(self, content_sha256: str) -> PIIClearance:
        """Rend la clairance du contenu exact, ou refuse.

        Le SHA est celui des octets **réellement téléchargés**, pas celui
        que le job annonçait : c'est le seul qui décrit ce qui sera
        indexé."""
        entry = self._by_content.get(content_sha256)
        if entry is None:
            raise SealedEvidenceError(
                f"content {content_sha256} was never scanned for personal data — "
                "refusing rather than assuming a document nobody looked at is clean"
            )
        status = str(entry.get("status", ""))
        if status != PII_CLEARED:
            raise SealedEvidenceError(
                f"content {content_sha256} is {status!r}, not {PII_CLEARED!r}"
            )
        if entry.get("pii_detected") is not False:
            raise SealedEvidenceError(
                f"content {content_sha256} is marked CLEARED yet reports detected "
                "personal data — the evidence contradicts itself and is refused"
            )
        return PIIClearance(
            content_sha256=content_sha256,
            pages_scanned=int(entry.get("pages_scanned", 0)),
            characters_scanned=int(entry.get("characters_scanned", 0)),
            evidence_sha256=self.evidence_sha256,
        )

    @property
    def cleared_count(self) -> int:
        return sum(
            1
            for entry in self._by_content.values()
            if entry.get("status") == PII_CLEARED
        )


# ─────────────────────────────────────────────────────────────────────────
# Droits
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RightsClearance:
    """Les droits résolus depuis la preuve gouvernée, jamais depuis un payload."""

    content_sha256: str
    rights: Rights
    zone: str
    decision_id: str
    registry_sha256: str


@dataclass(frozen=True)
class VerifiedRightsEvidenceRegistry:
    """Décisions de droits gouvernées, résolues par zone et par contenu.

    La décision humaine Nexus Réussite couvre une **zone** du corpus, pas
    un fichier ; c'est pourquoi la résolution part du chemin scellé. Une
    exception tierce identifiée sur un document précis reprend la main sur
    la couverture générique : une approbation de zone ne peut pas éteindre
    un droit d'auteur constaté sur une page."""

    registry_sha256: str
    corpus_manifest_sha256: str
    registry_id: str
    _zone_decisions: dict[str, tuple[str, Rights]]
    _excepted_content: frozenset[str]

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_registry_sha256: str,
        expected_corpus_manifest_sha256: str,
    ) -> VerifiedRightsEvidenceRegistry:
        registry_sha = _require_digest(
            path, expected_registry_sha256, label="rights registry"
        )
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise SealedEvidenceError("the rights registry is not a mapping")

        decisions = document.get("human_rights_decisions")
        if not isinstance(decisions, dict) or not decisions:
            raise SealedEvidenceError(
                "the rights registry records no human decision — provenance is not "
                "rights, and an automated inference never becomes one"
            )

        # Deux structures, deux rôles. ``human_rights_decisions`` dit
        # *qu'une zone est approuvée pour la production* ; ``source_evidence``
        # dit *quelle catégorie de droits* s'y applique. Les deux sont
        # nécessaires : une approbation sans catégorie ne dit pas ce qui est
        # publiable, et une catégorie sans approbation n'est qu'une
        # recommandation.
        approved_zones: dict[str, str] = {}
        for decision_id, decision in decisions.items():
            if not isinstance(decision, dict):
                continue
            # YAML lit un digest entièrement numérique comme un entier, et
            # ``str()`` ne le rattrape pas : ``0077…`` a déjà perdu ses
            # zéros de tête au parsing, donc la conversion produirait un
            # digest silencieusement faux. On exige la forme chaîne — le
            # registre doit citer ses digests entre guillemets.
            manifest = decision.get("scope_manifest_sha256")
            if not isinstance(manifest, str) or not _SHA256.match(manifest):
                raise SealedEvidenceError(
                    f"decision {decision_id!r} carries scope_manifest_sha256="
                    f"{manifest!r}; it must be a quoted lowercase 64-hex string. "
                    "An unquoted all-digit digest is parsed as an integer and may "
                    "already have lost leading zeros"
                )
            if manifest != expected_corpus_manifest_sha256:
                raise SealedEvidenceError(
                    f"decision {decision_id!r} covers corpus manifest {manifest!r}, "
                    f"not {expected_corpus_manifest_sha256!r} — a decision taken on "
                    "another corpus does not transfer"
                )
            if decision.get("approved_for_production_rag") is not True:
                continue
            raw = decision.get("scope_zones") or decision.get("scope_zone")
            zones = [raw] if isinstance(raw, str) else list(raw or ())
            if not zones:
                raise SealedEvidenceError(
                    f"decision {decision_id!r} approves production without naming a "
                    "zone — an unbounded approval is refused"
                )
            for zone in zones:
                approved_zones[str(zone)] = str(decision_id)

        if not approved_zones:
            raise SealedEvidenceError(
                "no human decision approves production for any zone"
            )

        sources = document.get("source_evidence")
        if not isinstance(sources, dict):
            raise SealedEvidenceError("the rights registry declares no source evidence")

        zone_decisions: dict[str, tuple[str, Rights]] = {}
        for source_id, source in sources.items():
            if not isinstance(source, dict):
                continue
            source_zone = source.get("zone")
            category = source.get("recommended_rights_category")
            if not isinstance(source_zone, str) or not category:
                # Une zone sans catégorie n'est pas publiable : elle reste
                # simplement absente de la table de résolution, et toute
                # demande la concernant sera refusée nommément.
                continue
            if source_zone not in approved_zones:
                continue
            try:
                rights = Rights(str(category))
            except ValueError as exc:
                raise SealedEvidenceError(
                    f"source {source_id!r} recommends unknown rights category "
                    f"{category!r}"
                ) from exc
            if rights is Rights.unknown:
                raise SealedEvidenceError(
                    f"source {source_id!r} resolves to unknown rights; an approval "
                    "cannot grant a right nobody named"
                )
            zone_decisions[source_zone] = (approved_zones[source_zone], rights)

        if not zone_decisions:
            raise SealedEvidenceError(
                "no zone is both approved for production and assigned a rights "
                "category"
            )

        excepted = document.get("document_specific_exceptions") or []
        excepted_content = frozenset(
            str(item.get("content_sha256"))
            for item in excepted
            if isinstance(item, dict) and item.get("content_sha256")
        )

        return cls(
            registry_sha256=registry_sha,
            corpus_manifest_sha256=expected_corpus_manifest_sha256,
            registry_id=str(document.get("registry_id", "")),
            _zone_decisions=dict(sorted(zone_decisions.items())),
            _excepted_content=excepted_content,
        )

    def resolve_rights(
        self, *, content_sha256: str, source_path: str
    ) -> RightsClearance:
        """Résout les droits d'un objet scellé, ou refuse.

        ``source_path`` est le chemin **dans le manifeste scellé** — la
        seule désignation qu'un opérateur ne choisit pas."""
        if content_sha256 in self._excepted_content:
            raise SealedEvidenceError(
                f"content {content_sha256} carries an identified third-party "
                "restriction; a zone-level approval cannot extinguish it"
            )

        # Zone la plus spécifique d'abord : ``04_.../02_RESSOURCES_AUTEUR_NEXUS/``
        # doit gagner sur ``04_.../`` si les deux étaient déclarées, sinon un
        # contenu auteur hériterait des droits d'une zone institutionnelle.
        for zone in sorted(self._zone_decisions, key=len, reverse=True):
            if source_path.startswith(zone):
                decision_id, rights = self._zone_decisions[zone]
                return RightsClearance(
                    content_sha256=content_sha256,
                    rights=rights,
                    zone=zone,
                    decision_id=decision_id,
                    registry_sha256=self.registry_sha256,
                )

        raise SealedEvidenceError(
            f"{source_path!r} falls outside every zone a human approved "
            f"({sorted(self._zone_decisions)}) — refusing rather than inferring "
            "rights from the reputation of the source"
        )


__all__ = [
    "EDUSCOL_ZONE",
    "PII_CLEARED",
    "PII_EVIDENCE_KIND",
    "PIIClearance",
    "RightsClearance",
    "SealedEvidenceError",
    "VerifiedPIIEvidenceRegistry",
    "VerifiedRightsEvidenceRegistry",
]
