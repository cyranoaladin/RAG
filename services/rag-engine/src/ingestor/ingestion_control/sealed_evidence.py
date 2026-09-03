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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from nexus_contracts.authority_artifacts import git_blob_sha1
from nexus_contracts.document import Rights
from nexus_contracts.pii_review_decisions import (
    ADMISSIBLE_DISPOSITIONS,
    PiiReviewDecisionSetV1,
    parse_pii_review_decision_set,
)
from nexus_contracts.review_binding import (
    ReviewBindingError,
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    require_matches_pii_review_decision_set,
    verify_review_binding,
)

#: Statuts de scan PII (ADR-0047). Deux seulement autorisent la suite du
#: pipeline : `CLEARED` (rien n'a été trouvé) et `DETECTED_REVIEWED_ACCEPTED`
#: (quelque chose a été trouvé, un humain autorisé l'a examiné et admis). Les
#: deux autres nomment honnêtement une détection non admise.
PII_CLEARED = "CLEARED"
PII_DETECTED_REVIEWED_ACCEPTED = "DETECTED_REVIEWED_ACCEPTED"
PII_DETECTED_RECORDED = "DETECTED_RECORDED"
PII_QUARANTINED = "QUARANTINED_PII"

#: Type de preuve attendu — un document d'un autre genre, même bien formé,
#: ne décrit pas un scan de corpus.
PII_EVIDENCE_KIND = "REAL_CORPUS_PII_SCAN"

#: Zone du corpus institutionnel couverte par la décision humaine Nexus
#: Réussite enregistrée dans le registre de droits.
EDUSCOL_ZONE = "01_EDUSCOL_OFFICIEL/"

#: Dépôt dont un reçu de revue peut faire autorité ici. Constante du module,
#: comme dans l'outillage de provenance : une revue faite ailleurs ne décide
#: rien dans ce dépôt. Ce n'est pas l'identité d'une campagne, qui, elle,
#: n'apparaît jamais dans le code.
CANONICAL_REPOSITORY = "cyranoaladin/RAG"

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


def _require_admission_is_founded(
    sha: str, entry: dict[str, Any], authority: ReviewAuthority | None
) -> None:
    """Une entrée qui se déclare admise doit s'appuyer sur une décision réelle.

    Le statut est écrit par le producteur ; il ne se croit pas lui-même. Tout
    ce qui suit confronte cette prétention à l'ensemble scellé, pour ce SHA
    exact. Le moindre écart est un refus — jamais une entrée dégradée."""
    if authority is None:
        raise SealedEvidenceError(
            f"content {sha} claims {PII_DETECTED_REVIEWED_ACCEPTED} but no sealed "
            "decision set was supplied — the claim founds nothing on its own"
        )
    decision = authority.decision_set.decision_for(sha)
    if decision is None:
        raise SealedEvidenceError(
            f"content {sha} claims {PII_DETECTED_REVIEWED_ACCEPTED} but is absent "
            "from decision set — nobody decided about these exact bytes"
        )
    if decision.decision != "APPROVED":
        raise SealedEvidenceError(
            f"content {sha} was decided {decision.decision!r} by the human review — "
            "a REJECTED content is never admitted"
        )
    inadmissible = [
        finding.finding_id
        for finding in decision.findings
        if finding.disposition not in ADMISSIBLE_DISPOSITIONS
    ]
    if inadmissible:
        raise SealedEvidenceError(
            f"content {sha} carries finding {inadmissible[0][:12]}… dispositioned "
            "as personal data present — no approval admits it"
        )
    if entry.get("pii_detected") is not True:
        raise SealedEvidenceError(
            f"content {sha} is marked {PII_DETECTED_REVIEWED_ACCEPTED} yet reports "
            "no detected personal data — an admission never erases the detection"
        )
    if entry.get("review_bundle_sha256") != decision.review_bundle_sha256:
        raise SealedEvidenceError(
            f"content {sha} names review bundle "
            f"{str(entry.get('review_bundle_sha256'))[:16]}… while the decision was "
            f"founded on {decision.review_bundle_sha256[:16]}… — the reviewer did "
            "not look at this material"
        )
    declared_set = entry.get("decision_set_id")
    if declared_set is not None and declared_set != authority.decision_set.decision_set_id:
        raise SealedEvidenceError(
            f"content {sha} names decision set {declared_set!r}, not "
            f"{authority.decision_set.decision_set_id!r}"
        )


@dataclass(frozen=True)
class PIIClearance:
    """La preuve qu'un contenu précis peut entrer dans le pipeline.

    Deux voies seulement, et elles ne se confondent jamais (ADR-0047) :
    `CLEARED` — le scanner n'a rien trouvé ; `DETECTED_REVIEWED_ACCEPTED` — il
    a trouvé quelque chose, un humain autorisé l'a examiné et admis. Dans le
    second cas ``pii_detected`` reste **vrai** : une admission ne réécrit pas
    l'histoire du document, elle s'y ajoute. Les trois dimensions (détection,
    revue, admission) restent lisibles séparément."""

    content_sha256: str
    pages_scanned: int
    characters_scanned: int
    evidence_sha256: str
    status: str = PII_CLEARED
    review_status: str | None = None
    decision_set_id: str | None = None

    @property
    def pii_detected(self) -> bool:
        """Le constat de détection, jamais effacé par l'admission."""
        return self.status == PII_DETECTED_REVIEWED_ACCEPTED

    @property
    def is_reviewed_accepted(self) -> bool:
        """Vrai seulement pour une admission adossée à une décision humaine."""
        return self.status == PII_DETECTED_REVIEWED_ACCEPTED


@dataclass(frozen=True)
class ReviewAuthority:
    """L'ensemble de décisions humaines scellé, et la preuve qu'il fait autorité.

    Cet objet n'existe que si la chaîne complète a été vérifiée hors ligne :
    octets canoniques, empreinte attendue, ancre de confiance, signature du
    reçu, fenêtre de validité, puis liaison du reçu à ces octets exacts. Rien
    ici ne nomme une campagne : l'identité vient des fichiers injectés."""

    decision_set: PiiReviewDecisionSetV1
    binding: ScopeAuthorizationReviewBindingV1
    decision_set_sha256: str

    @classmethod
    def verify(
        cls,
        *,
        decision_set_path: Path,
        expected_decision_set_sha256: str | None,
        receipt_path: Path | None,
        expected_receipt_sha256: str | None,
        trust_anchor_path: Path | None,
        expected_trust_anchor_sha256: str | None,
        environment: Literal["production", "test"],
        expected_repository: str,
        accepted_reviewers: tuple[str, ...] | None,
        now: datetime,
    ) -> ReviewAuthority:
        if not decision_set_path.exists():
            raise SealedEvidenceError(
                f"decision set {decision_set_path.name} is missing — a human review "
                "that cannot be read authorizes nothing"
            )
        if expected_decision_set_sha256 is not None:
            _require_digest(
                decision_set_path,
                expected_decision_set_sha256,
                label="PII review decision set",
            )
        raw_decision_set = decision_set_path.read_bytes()
        try:
            decision_set = parse_pii_review_decision_set(raw_decision_set)
        except Exception as exc:  # noqa: BLE001 - frontière de parsing
            raise SealedEvidenceError(f"the decision set is not readable: {exc}") from exc

        if receipt_path is None or not receipt_path.exists():
            raise SealedEvidenceError(
                "no ADR-0035 receipt accompanies the decision set — an unsigned "
                "decision set is a draft, never an authorization"
            )
        if expected_receipt_sha256 is not None:
            _require_digest(receipt_path, expected_receipt_sha256, label="PII review receipt")
        if trust_anchor_path is None or not trust_anchor_path.exists():
            raise SealedEvidenceError(
                "no trust anchor is available to verify the review receipt"
            )
        if expected_trust_anchor_sha256 is not None:
            _require_digest(
                trust_anchor_path, expected_trust_anchor_sha256, label="review trust anchor"
            )
        try:
            anchor = TrustAnchor.model_validate(
                json.loads(trust_anchor_path.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001 - frontière de parsing
            raise SealedEvidenceError(f"the trust anchor is not usable: {exc}") from exc

        # `accepted_reviewers=None` désactiverait le contrôle d'allowlist dans
        # le contrat : ici c'est un refus, pas un défaut permissif.
        if not accepted_reviewers:
            raise SealedEvidenceError(
                "no reviewer allowlist was supplied — the worker refuses to accept "
                "a review from an unbounded set of logins"
            )

        try:
            binding = verify_review_binding(
                receipt_path.read_bytes(),
                trust_anchor=anchor,
                environment=environment,
                now=now,
            )
            require_matches_pii_review_decision_set(
                binding,
                decision_set_id=decision_set.decision_set_id,
                decision_set_bytes=raw_decision_set,
                decision_set_git_blob_sha1=git_blob_sha1(raw_decision_set),
                expected_repository=expected_repository,
                accepted_reviewers=accepted_reviewers,
            )
        except ReviewBindingError as exc:
            raise SealedEvidenceError(f"the review receipt is refused: {exc}") from exc
        except SealedEvidenceError:
            raise
        except Exception as exc:  # noqa: BLE001 - toute autre anomalie est un refus
            raise SealedEvidenceError(
                f"the review receipt could not be verified: {exc}"
            ) from exc

        return cls(
            decision_set=decision_set,
            binding=binding,
            decision_set_sha256=hashlib.sha256(raw_decision_set).hexdigest(),
        )


@dataclass(frozen=True)
class VerifiedPIIEvidenceRegistry:
    """Résultats de scan PII, indexés par SHA de contenu.

    Immuable et chargé une fois : le worker interroge une structure en
    mémoire dont l'identité a été prouvée au démarrage."""

    evidence_sha256: str
    corpus_manifest_sha256: str
    policy_sha256: str
    _by_content: dict[str, dict[str, Any]]
    review_authority: ReviewAuthority | None = None

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_evidence_sha256: str,
        expected_corpus_manifest_sha256: str,
        decision_set_path: Path | None = None,
        expected_decision_set_sha256: str | None = None,
        receipt_path: Path | None = None,
        expected_receipt_sha256: str | None = None,
        trust_anchor_path: Path | None = None,
        expected_trust_anchor_sha256: str | None = None,
        environment: Literal["production", "test"] = "production",
        expected_repository: str = CANONICAL_REPOSITORY,
        accepted_reviewers: tuple[str, ...] | None = None,
        now: datetime | None = None,
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

        authority: ReviewAuthority | None = None
        if decision_set_path is not None:
            authority = ReviewAuthority.verify(
                decision_set_path=decision_set_path,
                expected_decision_set_sha256=expected_decision_set_sha256,
                receipt_path=receipt_path,
                expected_receipt_sha256=expected_receipt_sha256,
                trust_anchor_path=trust_anchor_path,
                expected_trust_anchor_sha256=expected_trust_anchor_sha256,
                environment=environment,
                expected_repository=expected_repository,
                accepted_reviewers=accepted_reviewers,
                now=now or datetime.now(UTC),
            )
            # Une décision porte sur un contenu scanné *sous une politique, un
            # scanner et un foyer de pages donnés*. Si la preuve en nomme
            # d'autres, les décisions ne parlent plus de ce scan-ci. Le contrôle
            # est inconditionnel : une clé absente serait un contrôle éteint.
            for field, expected in (
                ("policy_sha256", authority.decision_set.policy_sha256),
                ("scanner_sha256", authority.decision_set.scanner_sha256),
                ("page_policy_sha256", authority.decision_set.page_policy_sha256),
            ):
                declared = document.get(field)
                label = field.replace("_sha256", "").replace("_", "-")
                if declared is None:
                    raise SealedEvidenceError(
                        f"the PII scan declares no {field} — it cannot be confronted "
                        f"with the reviewed {label}"
                    )
                if str(declared) != expected:
                    raise SealedEvidenceError(
                        f"{label} mismatch: the scan was produced under "
                        f"{str(declared)[:16]}… while the human review decided under "
                        f"{expected[:16]}…"
                    )

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
            if entry.get("status") == PII_DETECTED_REVIEWED_ACCEPTED:
                _require_admission_is_founded(sha, entry, authority)
            by_content[sha] = entry

        return cls(
            evidence_sha256=evidence_sha,
            corpus_manifest_sha256=str(manifest),
            policy_sha256=str(document.get("policy_sha256", "")),
            _by_content=by_content,
            review_authority=authority,
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
        if status == PII_CLEARED:
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
                status=PII_CLEARED,
            )
        if status == PII_DETECTED_REVIEWED_ACCEPTED:
            # Déjà fondée au chargement ; revérifiée ici parce qu'un registre
            # se lit plus souvent qu'il ne se charge, et qu'un contrôle qui
            # n'existe qu'au démarrage n'en est pas un.
            _require_admission_is_founded(content_sha256, entry, self.review_authority)
            assert self.review_authority is not None  # garanti par l'appel ci-dessus
            return PIIClearance(
                content_sha256=content_sha256,
                pages_scanned=int(entry.get("pages_scanned", 0)),
                characters_scanned=int(entry.get("characters_scanned", 0)),
                evidence_sha256=self.evidence_sha256,
                status=PII_DETECTED_REVIEWED_ACCEPTED,
                review_status="APPROVED",
                decision_set_id=self.review_authority.decision_set.decision_set_id,
            )
        if status == PII_DETECTED_RECORDED:
            raise SealedEvidenceError(
                f"content {content_sha256} is {PII_DETECTED_RECORDED!r}: personal data "
                "was found and no approved human review covers it"
            )
        if status == PII_QUARANTINED:
            raise SealedEvidenceError(
                f"content {content_sha256} is {PII_QUARANTINED!r} and is never published"
            )
        raise SealedEvidenceError(
            f"content {content_sha256} is {status!r}, neither {PII_CLEARED!r} nor "
            f"{PII_DETECTED_REVIEWED_ACCEPTED!r}"
        )

    @property
    def cleared_count(self) -> int:
        """Contenus où le scanner n'a rien trouvé. Jamais les contenus admis
        après revue : les confondre effacerait la vérité PII dans les journaux."""
        return sum(
            1
            for entry in self._by_content.values()
            if entry.get("status") == PII_CLEARED
        )

    @property
    def reviewed_accepted_count(self) -> int:
        """Contenus détectés, examinés par un humain autorisé, et admis."""
        return sum(
            1
            for entry in self._by_content.values()
            if entry.get("status") == PII_DETECTED_REVIEWED_ACCEPTED
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
