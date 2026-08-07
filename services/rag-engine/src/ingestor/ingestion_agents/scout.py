"""Scout — découvre un ``ResourceCandidate`` à partir d'un ``SearchPlan`` (LOT44d).

Porte la transition ``DISCOVERED -> CANDIDATE``. Le cœur
(``discover_candidate_core``) est pur : aucune E/S, ``dedup_key`` est
calculé par un hachage déterministe de ``canonical_url`` (calcul local, pas
un accès réseau/disque). ``run_scout`` est la seule couche qui touche le
réseau (validation de ``source_url`` via ``ssrf_guard.validate_destination``
injecté) et l'écriture d'état (``apply_resource_transition``).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

import psycopg
from nexus_contracts.document import TypeDoc
from nexus_contracts.ingestion import ResourceCandidate, SearchPlan
from nexus_contracts.resource_state import ResourceState

from .dependencies import (
    DestinationValidator,
    default_validate_destination,
)
from .transitions import TransitionResult, apply_resource_transition


class DomainNotAllowedError(ValueError):
    """Le domaine du candidat découvert n'appartient pas à
    ``search_plan.allowed_domains`` — rejet explicite, jamais une
    acceptation silencieuse hors périmètre du plan."""


def _normalize_hostname(raw: str) -> str:
    """Normalisation canonique d'un nom d'hôte — minuscules, sans point
    final. Remédiation revue PR#90 (Cubic P2, revue incrémentale) : cette
    normalisation doit s'appliquer de façon **identique** aux trois
    sources de vérité comparées entre elles (``domain`` déclaré par
    l'appelant, entrées de ``search_plan.allowed_domains``, hôtes dérivés
    de ``source_url``/``canonical_url`` via ``_hostname_of``) — avant ce
    correctif, seul ``_hostname_of`` (donc les hôtes dérivés d'URL) était
    normalisé ; ``domain`` et les entrées de ``allowed_domains`` étaient
    comparés tels quels, casse et point final compris. Un profil déclarant
    ``allowed_domains: ["Eduscol.education.fr"]`` (majuscule) aurait alors
    rejeté à tort un ``canonical_host`` légitimement identique mais
    normalisé en minuscules par ``_hostname_of`` — un faux refus, jamais
    un contournement de sécurité, mais un défaut opérationnel discret et
    dépendant de la façon dont un opérateur a saisi le domaine."""
    return raw.rstrip(".").lower()


def _hostname_of(url: str) -> str:
    """Hôte canonique d'une URL — jamais une chaîne fournie par l'appelant.

    Remédiation revue PR#90 : ``discover_candidate_core`` comparait
    auparavant uniquement le paramètre ``domain`` (fourni par l'appelant,
    ex. l'opérateur via ``create_job_cli.py``) à ``allowed_domains``, sans
    jamais vérifier qu'il correspondait réellement à l'hôte de
    ``source_url``/``canonical_url`` — un appelant pouvait déclarer
    ``domain="eduscol.education.fr"`` tout en fournissant une
    ``source_url`` pointant vers un tout autre hôte, et le candidat était
    accepté. ``urlparse(...).hostname`` ignore déjà le port ; normalisé en
    minuscules et sans point final pour éviter un contournement trivial
    par la casse ou un point final superflu."""
    hostname = urlparse(url).hostname
    if not hostname:
        raise DomainNotAllowedError(f"cannot derive a hostname from url {url!r}")
    return _normalize_hostname(hostname)


def discover_candidate_core(
    *,
    search_plan: SearchPlan,
    resource_id: UUID,
    candidate_id: UUID,
    discovered_at: datetime,
    source_url: str,
    canonical_url: str,
    domain: str,
    proposed_type_doc: TypeDoc,
    title: str | None = None,
    publisher: str | None = None,
    language: str = "fr",
    relevance_evidence: tuple[str, ...] = (),
) -> ResourceCandidate:
    """Construit un ``ResourceCandidate`` déterministe — aucune E/S.

    ``dedup_key`` est le SHA-256 de ``canonical_url`` : un calcul local pur,
    jamais une lecture d'état externe — la déduplication réelle contre des
    candidats déjà connus reste la responsabilité de l'appelant (contrainte
    ``UNIQUE(collection, dedup_key)``, ADR-0027, non modifiée ici).

    Remédiation revue PR#90 : ``domain`` (fourni par l'appelant) n'est plus
    la seule source de vérité pour l'autorisation — il doit correspondre
    exactement à l'hôte réel de ``source_url``, et l'hôte de
    ``canonical_url`` doit lui aussi appartenir à ``allowed_domains``
    (``canonical_url`` sert d'identité de source faisant autorité —
    ``dedup_key`` en dépend déjà). Un appelant qui déclare un ``domain``
    allowlisté tout en fournissant une ``source_url`` vers un autre hôte
    est rejeté explicitement, jamais silencieusement accepté sur la seule
    foi de la chaîne déclarée.
    """
    source_host = _hostname_of(source_url)
    canonical_host = _hostname_of(canonical_url)
    # Remédiation revue PR#90 (Cubic P2, revue incrémentale) : normalise
    # `domain` (déclaré par l'appelant) et `allowed_domains` (config du
    # profil) exactement comme `_hostname_of` normalise les hôtes dérivés
    # d'URL — les trois sources doivent être comparées sur un pied
    # d'égalité, jamais l'une normalisée et les deux autres telles quelles.
    normalized_domain = _normalize_hostname(domain)
    normalized_allowed_domains = {
        _normalize_hostname(allowed) for allowed in search_plan.allowed_domains
    }

    if source_host != normalized_domain:
        raise DomainNotAllowedError(
            f"declared domain {domain!r} does not match the source_url host "
            f"{source_host!r} — refusing to trust a caller-supplied domain "
            "that disagrees with the actual URL"
        )
    if normalized_domain not in normalized_allowed_domains:
        raise DomainNotAllowedError(
            f"domain {domain!r} is not in search_plan.allowed_domains "
            f"{sorted(search_plan.allowed_domains)!r}"
        )
    if canonical_host not in normalized_allowed_domains:
        raise DomainNotAllowedError(
            f"canonical_url host {canonical_host!r} is not in "
            f"search_plan.allowed_domains {sorted(search_plan.allowed_domains)!r}"
        )

    dedup_key = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()

    return ResourceCandidate(
        candidate_id=candidate_id,
        resource_id=resource_id,
        run_id=search_plan.run_id,
        scope=search_plan.scope,
        discovered_at=discovered_at,
        source_url=source_url,
        canonical_url=canonical_url,
        domain=normalized_domain,
        proposed_type_doc=proposed_type_doc,
        title=title,
        publisher=publisher,
        language=language,
        relevance_evidence=list(relevance_evidence),
        dedup_key=dedup_key,
    )


def run_scout(
    conn: psycopg.Connection,
    *,
    search_plan: SearchPlan,
    resource_id: UUID,
    candidate_id: UUID,
    discovered_at: datetime,
    source_url: str,
    canonical_url: str,
    domain: str,
    proposed_type_doc: TypeDoc,
    expected_version: int,
    actor: str,
    job_id: UUID | None = None,
    title: str | None = None,
    publisher: str | None = None,
    language: str = "fr",
    relevance_evidence: tuple[str, ...] = (),
    validate_destination: DestinationValidator = default_validate_destination,
) -> tuple[ResourceCandidate, TransitionResult]:
    """Valide ``source_url`` (garde SSRF), construit le candidat, transitionne
    ``DISCOVERED -> CANDIDATE``. Échec explicite (propagation) à chaque étape
    — aucune acceptation partielle, aucun candidat retourné sans transition
    réussie."""
    validate_destination(source_url)

    candidate = discover_candidate_core(
        search_plan=search_plan,
        resource_id=resource_id,
        candidate_id=candidate_id,
        discovered_at=discovered_at,
        source_url=source_url,
        canonical_url=canonical_url,
        domain=domain,
        proposed_type_doc=proposed_type_doc,
        title=title,
        publisher=publisher,
        language=language,
        relevance_evidence=relevance_evidence,
    )

    transition = apply_resource_transition(
        conn,
        resource_id=resource_id,
        expected_state=ResourceState.DISCOVERED,
        expected_version=expected_version,
        new_state=ResourceState.CANDIDATE,
        actor=actor,
        run_id=search_plan.run_id,
        job_id=job_id,
        payload={"candidate_id": str(candidate_id), "dedup_key": candidate.dedup_key},
    )

    return candidate, transition


__all__ = ["DomainNotAllowedError", "discover_candidate_core", "run_scout"]
