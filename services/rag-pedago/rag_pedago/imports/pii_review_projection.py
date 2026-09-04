"""Projeter un decision set PII scellé sur le scan courant du corpus (ADR-0047).

**Le producteur ne décide rien.** Il lit trois sources — le scan du corpus, la
décision humaine scellée, et l'index des paquets qui ont fondé cette décision —
et projette honnêtement leur résultat. Tout son travail consiste à refuser
lorsque ces trois sources ne décrivent pas le même monde.

**Pourquoi raisonner par ensembles et non par comptes.** « 320 − 23 = 297 » est
vrai et ne prouve rien : la même arithmétique tiendrait si un contenu approuvé
avait été silencieusement remplacé par un autre. Les ensembles, eux, ne se
compensent pas. Le module construit donc :

    C = contenus du corpus candidat            D = contenus détectés par le scan
    A = contenus APPROVED                      R = contenus REJECTED

et impose ``A ∩ R = ∅``, ``A ∪ R = D``, ``A ⊆ C``, ``R ⊆ C``, ``D ⊆ C`` avant
de dériver ``CLEARED = C − D`` puis ``AUTHORIZED = CLEARED ∪ A``. Les comptes
sont des vérifications a posteriori ; aucun n'est écrit ici.

**Le même univers de findings, pas le même nombre.** Comparer « 49 findings
scannés » à « 49 findings dispositionnés » laisserait passer un remplacement à
cardinalité constante. La comparaison porte donc sur les identités
(`finding_identity`), et sur les empreintes de matière derrière chacune.

**La détection n'est jamais effacée.** Un contenu approuvé ressort
``pii_detected=true`` sous ``DETECTED_REVIEWED_ACCEPTED``. Un contenu rejeté
ressort ``QUARANTINED_PII`` et n'entre dans aucun ensemble autorisé.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from nexus_contracts.pii_review_decisions import (
    ADMISSIBLE_DISPOSITIONS,
    PiiReviewDecisionSetV1,
)

#: Statuts projetés — ceux du contrat ADR-0047, pas un vocabulaire local.
STATUS_CLEARED = "CLEARED"
STATUS_REVIEWED_ACCEPTED = "DETECTED_REVIEWED_ACCEPTED"
STATUS_QUARANTINED = "QUARANTINED_PII"


#: Fenêtre de contexte figée dans les paquets de revue, en caractères de part
#: et d'autre de la correspondance. C'est ce que le reviewer a effectivement
#: lu autour du signal, et c'est sur ce texte que `context_sha256` est calculé.
CONTEXT_CHARS = 240


def finding_context(page_text: str, *, char_offset: int, match_length: int) -> str:
    """Rend le texte que le reviewer a vu autour d'une correspondance.

    **Pourquoi ce n'est pas le contexte du scanner.** `pii_scanner.extract_context`
    existe aussi, mais il sert au confort de lecture : 50 caractères, sauts de
    ligne remplacés par des espaces, bords rognés. Le paquet de revue, lui, fige
    240 caractères de texte de page BRUT. Les deux sont légitimes ; les confondre
    fait diverger `context_sha256`, et le producteur refuse alors une décision
    humaine parfaitement valide.

    Comme `finding_identity`, cette fenêtre est l'autorité unique : le
    préparateur de paquets l'utilise pour sceller, le producteur pour retrouver."""
    start = max(0, char_offset - CONTEXT_CHARS)
    end = min(len(page_text), char_offset + match_length + CONTEXT_CHARS)
    return page_text[start:end]


def finding_identity(
    *,
    content_sha256: str,
    pattern_id: str,
    page_number: int | None,
    char_offset: int,
    match_sha256: str,
) -> str:
    """Nomme un finding de scan sans jamais porter sa matière.

    Cinq composantes : le contenu, le motif, la page, la position, et
    l'EMPREINTE de la correspondance. Deux findings identiques au même endroit
    ne peuvent pas exister ; la même matière à deux endroits a deux identités.

    **Pourquoi cette fonction n'est pas dans `pii_scanner`, où sa place
    semblerait naturelle.** L'empreinte de `pii_scanner.py` est scellée dans
    l'ensemble de décisions humaines (`scanner_sha256`) : y ajouter ne
    serait-ce qu'une fonction change son digest, et rend — par la règle même
    d'ADR-0047 — les décisions déjà rendues caduques pour tous les contenus
    concernés. Une bonne place dans l'arbre ne vaut pas de détacher une revue
    humaine de son scan.

    C'est en revanche l'autorité UNIQUE de cette dérivation : le préparateur de
    paquets s'en sert pour sceller les findings soumis à la revue, le
    producteur pour retrouver ces mêmes findings dans son propre scan. Deux
    dérivations divergentes rendraient les deux ensembles disjoints. La formule
    ne se « simplifie » donc pas."""
    return sha256(
        f"{content_sha256}:{pattern_id}:{page_number}:{char_offset}:{match_sha256}".encode()
    ).hexdigest()


class PiiProjectionError(ValueError):
    """Les trois sources ne décrivent pas le même monde — refus explicite."""


@dataclass(frozen=True)
class ScannedFinding:
    """Une correspondance du scan courant, décrite sans sa matière."""

    finding_id: str
    pattern_id: str
    page: int
    match_sha256: str
    context_sha256: str


@dataclass(frozen=True)
class ScannedContent:
    """Le résultat du scan courant pour un contenu du corpus."""

    content_sha256: str
    pages_scanned: int
    characters_scanned: int
    ignored_empty_pages: tuple[int, ...]
    findings: tuple[ScannedFinding, ...]


@dataclass(frozen=True)
class PiiProjection:
    """Ce que le producteur a le droit d'écrire, et les ensembles qui le fondent."""

    entries: tuple[dict[str, Any], ...]
    counts: Mapping[str, int]
    corpus: frozenset[str]
    detected: frozenset[str]
    approved: frozenset[str]
    rejected: frozenset[str]
    cleared: frozenset[str]
    reviewed_accepted: frozenset[str]
    authorized: frozenset[str]
    decision_set_id: str | None


def _require_same_instruments(
    decision_set: PiiReviewDecisionSetV1,
    *,
    policy_sha256: str,
    scanner_sha256: str,
    page_policy_sha256: str,
) -> None:
    """Une décision porte sur un scan fait sous des instruments précis.

    Changer la politique, le scanner ou le foyer de pages rend la décision
    caduque pour les contenus concernés : elle ne parle plus du même mesurage."""
    for label, decided, current in (
        ("policy", decision_set.policy_sha256, policy_sha256),
        ("scanner", decision_set.scanner_sha256, scanner_sha256),
        ("page policy", decision_set.page_policy_sha256, page_policy_sha256),
    ):
        if decided != current:
            raise PiiProjectionError(
                f"the human review decided under {label} {decided[:16]}… while this "
                f"release scans under {current[:16]}… — the decisions no longer "
                "describe this measurement"
            )


def _require_same_finding_universe(
    content_sha256: str,
    scanned: ScannedContent,
    decision: Any,
) -> None:
    """Les findings scannés et dispositionnés doivent être les MÊMES."""
    scanned_by_id = {finding.finding_id: finding for finding in scanned.findings}
    decided_by_id = {finding.finding_id: finding for finding in decision.findings}

    undispositioned = sorted(set(scanned_by_id) - set(decided_by_id))
    if undispositioned:
        raise PiiProjectionError(
            f"content {content_sha256[:12]}… carries finding "
            f"{undispositioned[0][:12]}… with no disposition — the scan found "
            "something the reviewer never saw"
        )
    vanished = sorted(set(decided_by_id) - set(scanned_by_id))
    if vanished:
        raise PiiProjectionError(
            f"content {content_sha256[:12]}… was decided on finding "
            f"{vanished[0][:12]}… which the current scan no longer reports — the "
            "disposition rests on nothing measurable"
        )

    for finding_id, found in scanned_by_id.items():
        decided = decided_by_id[finding_id]
        for field, left, right in (
            ("match_sha256", found.match_sha256, decided.match_sha256),
            ("context_sha256", found.context_sha256, decided.context_sha256),
            ("page", found.page, decided.page),
            ("pattern_id", found.pattern_id, decided.pattern_id),
        ):
            if left != right:
                raise PiiProjectionError(
                    f"finding {finding_id[:12]}… of content {content_sha256[:12]}…: "
                    f"scan and decision disagree on {field} ({left!r} vs {right!r})"
                )


def project_pii_review(
    scanned: Sequence[ScannedContent],
    *,
    decision_set_document: Mapping[str, Any] | None,
    review_bundles: Mapping[str, str],
    policy_sha256: str,
    scanner_sha256: str,
    page_policy_sha256: str,
) -> PiiProjection:
    """Projette la décision humaine sur le scan, ou refuse.

    ``review_bundles`` associe un contenu à l'empreinte du paquet de revue que
    l'INDEX lui attribue — jamais celle que la décision revendique. Confronter
    la décision à sa propre revendication serait tautologique."""
    corpus_order: list[str] = []
    by_sha: dict[str, ScannedContent] = {}
    for content in scanned:
        if content.content_sha256 in by_sha:
            raise PiiProjectionError(
                f"content {content.content_sha256[:12]}… appears twice in the scan — "
                "which of the two measurements applies cannot be decided"
            )
        by_sha[content.content_sha256] = content
        corpus_order.append(content.content_sha256)

    corpus = frozenset(by_sha)
    detected = frozenset(sha for sha, c in by_sha.items() if c.findings)

    if decision_set_document is None:
        if detected:
            raise PiiProjectionError(
                f"{len(detected)} content(s) carry detections but no decision set was "
                "supplied — a detection without a human review admits nothing"
            )
        decision_set = None
        approved: frozenset[str] = frozenset()
        rejected: frozenset[str] = frozenset()
    else:
        try:
            decision_set = PiiReviewDecisionSetV1.model_validate(dict(decision_set_document))
        except Exception as exc:  # noqa: BLE001 - frontière de validation
            raise PiiProjectionError(f"the decision set is invalid: {exc}") from exc
        _require_same_instruments(
            decision_set,
            policy_sha256=policy_sha256,
            scanner_sha256=scanner_sha256,
            page_policy_sha256=page_policy_sha256,
        )
        approved = decision_set.approved_content_sha256
        rejected = frozenset(
            d.content_sha256 for d in decision_set.decisions if d.decision == "REJECTED"
        )

        # A ∩ R = ∅. Le contrat interdit déjà qu'un contenu apparaisse deux
        # fois ; on le vérifie tout de même, parce qu'une garde qui repose
        # entièrement sur une autre garde ne protège de rien si celle-ci bouge.
        both = sorted(approved & rejected)
        if both:
            raise PiiProjectionError(
                f"content {both[0][:12]}… is both APPROVED and REJECTED"
            )

        decided = approved | rejected
        outside = sorted(decided - corpus)
        if outside:
            raise PiiProjectionError(
                f"the decision set decides about content {outside[0][:12]}…, which is "
                "outside the corpus — a decision about nothing this release ships"
            )
        undecided = sorted(detected - decided)
        if undecided:
            raise PiiProjectionError(
                f"content {undecided[0][:12]}… is detected by the scan and has no "
                "decision — every detection must be dispositioned by a human"
            )
        stale = sorted(decided - detected)
        if stale:
            raise PiiProjectionError(
                f"content {stale[0][:12]}… was decided but has no current detection — "
                "the measurement changed under the decision"
            )

        for decision in decision_set.decisions:
            sha = decision.content_sha256
            indexed_bundle = review_bundles.get(sha)
            if indexed_bundle is None:
                raise PiiProjectionError(
                    f"content {sha[:12]}… has a decision but no review bundle in the "
                    "index — nothing establishes what the reviewer looked at"
                )
            if indexed_bundle != decision.review_bundle_sha256:
                raise PiiProjectionError(
                    f"content {sha[:12]}…: the index founds the review on bundle "
                    f"{indexed_bundle[:16]}… while the decision names "
                    f"{decision.review_bundle_sha256[:16]}…"
                )
            _require_same_finding_universe(sha, by_sha[sha], decision)
            if decision.decision == "APPROVED":
                inadmissible = [
                    f.finding_id
                    for f in decision.findings
                    if f.disposition not in ADMISSIBLE_DISPOSITIONS
                ]
                if inadmissible:
                    raise PiiProjectionError(
                        f"content {sha[:12]}… is APPROVED yet carries finding "
                        f"{inadmissible[0][:12]}… dispositioned as personal data present"
                    )

    cleared = corpus - detected
    reviewed_accepted = approved
    authorized = cleared | reviewed_accepted

    entries: list[dict[str, Any]] = []
    for sha in corpus_order:
        content = by_sha[sha]
        entry: dict[str, Any] = {
            "content_sha256": sha,
            "pages_scanned": content.pages_scanned,
            "characters_scanned": content.characters_scanned,
            "ignored_empty_pages": list(content.ignored_empty_pages),
        }
        if sha in reviewed_accepted:
            assert decision_set is not None  # garanti par `detected ⊆ approved ∪ rejected`
            decision = decision_set.decision_for(sha)
            assert decision is not None
            entry.update(
                status=STATUS_REVIEWED_ACCEPTED,
                pii_detected=True,
                review_status="APPROVED",
                review_bundle_sha256=decision.review_bundle_sha256,
                decision_set_id=decision_set.decision_set_id,
            )
        elif sha in rejected:
            assert decision_set is not None
            decision = decision_set.decision_for(sha)
            assert decision is not None
            entry.update(
                status=STATUS_QUARANTINED,
                pii_detected=True,
                review_status="REJECTED",
                review_bundle_sha256=decision.review_bundle_sha256,
                decision_set_id=decision_set.decision_set_id,
            )
        else:
            entry.update(status=STATUS_CLEARED, pii_detected=False)
        entries.append(entry)

    counts = {
        "scanned_count": len(corpus),
        "detected_count": len(detected),
        "cleared_count": len(cleared),
        "reviewed_accepted_count": len(reviewed_accepted),
        "rejected_count": len(rejected),
        "authorized_count": len(authorized),
        "quarantined_count": len(rejected),
    }

    return PiiProjection(
        entries=tuple(entries),
        counts=counts,
        corpus=corpus,
        detected=detected,
        approved=approved,
        rejected=rejected,
        cleared=cleared,
        reviewed_accepted=reviewed_accepted,
        authorized=authorized,
        decision_set_id=decision_set.decision_set_id if decision_set else None,
    )


__all__ = [
    "STATUS_CLEARED",
    "STATUS_QUARANTINED",
    "STATUS_REVIEWED_ACCEPTED",
    "PiiProjection",
    "PiiProjectionError",
    "ScannedContent",
    "ScannedFinding",
    "CONTEXT_CHARS",
    "finding_context",
    "finding_identity",
    "project_pii_review",
]
