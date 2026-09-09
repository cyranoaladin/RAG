"""Registre de révocation gouverné, partagé (F2, ADR-0035/ADR-0036/ADR-0042).

Un seul parseur strict pour
``governance/trust-anchors/authorization-revocations-v1.json``, consommé
par `rag-pedago` (le gate de campagne H2-B) et `rag-engine` (le signer de
readiness) : deux parseurs indépendants finiraient par diverger, et un
registre interprété différemment par les deux services ne serait plus une
preuve commune.

Porté fidèlement depuis l'ancien
``rag_pedago.imports.h2b_coverage_report._parse_revocation_registry``
(comportement identique, jamais assoupli) — voir ADR-0042 pour le
contexte de cette migration.
"""
from __future__ import annotations

import json
from typing import Any

#: Versionné : un futur format ne peut jamais être relu comme celui-ci
#: par accident.
REVOCATIONS_PROTOCOL_VERSION = "NEXUS-AUTHORIZATION-REVOCATIONS-V1"

_EXPECTED_KEYS = frozenset({"protocol_version", "revoked_authorization_ids"})


class AuthorizationRevocationsError(ValueError):
    """Le registre de révocation ne prouve rien — fail-closed.

    Une seule exception pour tout refus : JSON malformé, clé inconnue,
    protocole erroné, identifiant vide, doublon."""


def parse_revoked_authorization_ids(
    raw: bytes, *, origin: str = "revocation registry"
) -> frozenset[str]:
    """Analyse stricte du registre de révocation gouverné.

    Un registre **gouverné vide** est valide : « aucune autorisation
    révoquée » est une affirmation légitime, et le fichier prouve que
    quelqu'un l'a affirmée. C'est l'*absence* de registre qui ne l'est
    pas — elle ne distingue pas « rien n'est révoqué » de « personne n'a
    regardé ». Cette fonction ne tranche pas cette distinction ; elle
    incombe à l'appelant (le registre est requis ou non selon
    l'environnement).

    Un doublon est refusé plutôt qu'absorbé par le ``frozenset`` : deux
    lignes identiques signalent une édition concurrente mal fusionnée, et
    un registre de révocation dont on ignore l'historique d'édition ne
    mérite pas la confiance qu'on lui accorde.
    """
    try:
        document: Any = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise AuthorizationRevocationsError(
            f"REVOCATION_REGISTRY_INVALID: {origin} is not valid UTF-8: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise AuthorizationRevocationsError(
            f"REVOCATION_REGISTRY_INVALID: {origin} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise AuthorizationRevocationsError(
            f"REVOCATION_REGISTRY_INVALID: {origin} must be a JSON object"
        )

    unexpected = set(document) - _EXPECTED_KEYS
    if unexpected:
        raise AuthorizationRevocationsError(
            f"REVOCATION_REGISTRY_INVALID: {origin} carries unknown keys "
            f"{sorted(unexpected)!r} — a governed registry never smuggles fields "
            "past the schema"
        )

    protocol_version = document.get("protocol_version")
    if protocol_version != REVOCATIONS_PROTOCOL_VERSION:
        raise AuthorizationRevocationsError(
            f"REVOCATION_REGISTRY_INVALID: {origin} declares protocol_version "
            f"{protocol_version!r}, expected {REVOCATIONS_PROTOCOL_VERSION!r}"
        )

    revoked = document.get("revoked_authorization_ids")
    if not isinstance(revoked, list) or any(
        not isinstance(item, str) or not item.strip() for item in revoked
    ):
        raise AuthorizationRevocationsError(
            f"REVOCATION_REGISTRY_INVALID: {origin} must declare "
            "revoked_authorization_ids as a list of non-empty strings"
        )
    duplicates = sorted({item for item in revoked if revoked.count(item) > 1})
    if duplicates:
        raise AuthorizationRevocationsError(
            f"REVOCATION_REGISTRY_INVALID: {origin} repeats authorization ids "
            f"{duplicates!r} — a revocation registry is a set, and a duplicate "
            "signals an unreviewed merge"
        )
    return frozenset(revoked)
