"""Points de contrôle LOT41A pendant l'ingestion (ADR-0032 § 4bis).

Remédiation GATE H1, item **D**.

**Le problème résolu ici.** Une ``VerifiedAuthorization`` calculée puis
ignorée n'autorise rien : elle donne seulement le droit de *commencer*.
Tant que ``allowed_domains``, ``rights_categories``, ``exclusions``, le
profil, le manifest et la fenêtre de validité ne sont pas confrontés aux
faits réels du pipeline, l'autorisation décrit un périmètre que rien
n'applique — un job autorisé pour ``eduscol.education.fr`` pouvait
télécharger ailleurs, et un artefact aux droits interdits pouvait
traverser toute la chaîne.

Ce module transforme chaque contrainte de l'autorisation en une assertion
exécutée au moment où le fait correspondant devient connu :

===========================  =========================================
Point de contrôle            Ce qui est confronté
===========================  =========================================
``enforce_before_fetch``     scope, authorization_id, manifest digest,
                             profil (id/version/fingerprint), fenêtre
                             de validité
``enforce_destination``      hostname normalisé de CHAQUE saut réseau
                             (URL initiale, canonique, et toute
                             redirection) contre ``allowed_domains`` et
                             ``exclusions``
``enforce_content_sha256``   SHA-256 des octets bruts contre l'allowlist
                             positive LOT41A-V2, avant stockage/extraction
``enforce_rights``           catégorie de droits produite par le
                             RightsAgent contre ``rights_categories``
``enforce_pii``              absence de PII (cette release n'ingère
                             aucune PII, quelle que soit l'autorisation)
===========================  =========================================

Toute violation lève ``ScopeEnforcementViolation`` — sous-classe de
``ScopeAuthorizationDeniedError``, de sorte que l'appelant qui journalise
déjà ``SCOPE_AUTHORIZATION_DENIED`` capture aussi ces refus, sans jamais
qu'un chemin d'erreur distinct puisse passer inaperçu.

**Revalidation live.** Ces fonctions sont *pures* : elles ne parlent ni à
PostgreSQL ni à GitHub. La politique de revalidation appartient à
l'appelant (``ingestion_worker.runner``), qui relance
``verify_scope_authorization`` — donc une relecture GitHub complète — à
trois moments : avant tout accès réseau, après le téléchargement mais avant
``FETCHED``/stockage, et de nouveau avant que la ressource ne franchisse
l'étape des droits. Une révocation intervenue pendant un run long est donc
effective avant que la ressource n'avance, sans imposer une requête GitHub
par saut de redirection.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from nexus_contracts.authority_artifacts import normalize_hostname
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceScope

from .scope_authority import ScopeAuthorizationDeniedError, VerifiedAuthorization, scope_key

_LOWERCASE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ScopeEnforcementViolation(ScopeAuthorizationDeniedError):
    """Un fait réel du pipeline sort du périmètre autorisé — fail-closed,
    jamais un avertissement, jamais une poursuite « en mode dégradé »."""

    def __init__(self, checkpoint: str, message: str) -> None:
        self.checkpoint = checkpoint
        super().__init__(f"[{checkpoint}] {message}")


def enforce_before_fetch(
    authorization: VerifiedAuthorization,
    *,
    authorization_id: str,
    scope: ResourceScope,
    manifest_digest: str,
    profile_id: str,
    profile_version: str,
    profile_fingerprint: str,
    now: datetime,
) -> None:
    """Premier point de contrôle : avant tout accès réseau.

    Vérifie que l'autorisation vérifiée est bien *celle que le job nomme*
    et qu'elle couvre exactement le profil et le manifest que le worker
    s'apprête à utiliser. Un drift de profil ou de manifest arrêté ici n'a
    jamais provoqué de requête sortante."""
    if authorization.authorization_id != authorization_id:
        raise ScopeEnforcementViolation(
            "pre_fetch",
            f"job names scope_authorization_id={authorization_id!r} but the "
            f"verified authorization is {authorization.authorization_id!r}",
        )
    if scope_key(authorization.scope) != scope_key(scope):
        raise ScopeEnforcementViolation(
            "pre_fetch",
            f"authorization {authorization_id!r} covers scope "
            f"{scope_key(authorization.scope)!r}, not the job scope "
            f"{scope_key(scope)!r}",
        )
    if authorization.manifest_digest != manifest_digest:
        raise ScopeEnforcementViolation(
            "pre_fetch",
            f"manifest drift: authorized {authorization.manifest_digest!r}, "
            f"worker is running {manifest_digest!r}",
        )
    if authorization.profile_id != profile_id:
        raise ScopeEnforcementViolation(
            "pre_fetch",
            f"profile drift: authorized profile_id={authorization.profile_id!r}, "
            f"job uses {profile_id!r}",
        )
    if authorization.profile_version != profile_version:
        raise ScopeEnforcementViolation(
            "pre_fetch",
            f"profile drift: authorized profile_version="
            f"{authorization.profile_version!r}, job uses {profile_version!r}",
        )
    if authorization.profile_fingerprint != profile_fingerprint:
        raise ScopeEnforcementViolation(
            "pre_fetch",
            f"profile drift: authorized profile_fingerprint="
            f"{authorization.profile_fingerprint!r}, worker loaded "
            f"{profile_fingerprint!r}",
        )
    enforce_validity_window(authorization, now=now, checkpoint="pre_fetch")


def enforce_validity_window(
    authorization: VerifiedAuthorization, *, now: datetime, checkpoint: str
) -> None:
    """``valid_from <= now < valid_until``, réévalué à chaque point de
    contrôle : une autorisation qui expire *pendant* un traitement long
    cesse d'autoriser les étapes suivantes, jamais seulement les jobs
    futurs."""
    if now < authorization.valid_from:
        raise ScopeEnforcementViolation(
            checkpoint,
            f"authorization {authorization.authorization_id!r} is not valid yet "
            f"(valid_from={authorization.valid_from.isoformat()}, now={now.isoformat()})",
        )
    if now >= authorization.valid_until:
        raise ScopeEnforcementViolation(
            checkpoint,
            f"authorization {authorization.authorization_id!r} expired at "
            f"{authorization.valid_until.isoformat()} (now={now.isoformat()})",
        )


def enforce_destination(
    authorization: VerifiedAuthorization, *, url: str, checkpoint: str = "destination"
) -> str:
    """Deuxième point de contrôle : à chaque URL réellement atteinte.

    Appelé pour l'URL source, l'URL canonique, **et chaque saut de
    redirection** — c'est le seul endroit où le domaine réellement contacté
    devient connu. Le hostname est normalisé avec exactement la même
    fonction que celle qui a normalisé ``allowed_domains`` dans l'artefact
    revu : les deux côtés de la comparaison partagent leur forme
    canonique, jamais deux normalisations divergentes.

    La comparaison est une **égalité exacte** — jamais un suffixe : une
    autorisation pour ``education.fr`` n'autorise pas
    ``education.fr.attacker.test``, et une autorisation pour
    ``eduscol.education.fr`` n'autorise pas ``www.eduscol.education.fr``
    (un sous-domaine doit être autorisé nommément)."""
    hostname = urlsplit(url).hostname or ""
    if not hostname:
        raise ScopeEnforcementViolation(checkpoint, f"URL {url!r} has no hostname")
    try:
        normalized: str = normalize_hostname(hostname)
    except ValueError as exc:
        raise ScopeEnforcementViolation(
            checkpoint, f"URL {url!r} has a non-normalizable hostname: {exc}"
        ) from exc

    if normalized not in authorization.allowed_domains:
        raise ScopeEnforcementViolation(
            checkpoint,
            f"host {normalized!r} (from {url!r}) is not in the authorized domains "
            f"{list(authorization.allowed_domains)!r} of authorization "
            f"{authorization.authorization_id!r}",
        )
    for exclusion in authorization.exclusions:
        if _matches_exclusion(url=url, hostname=normalized, exclusion=exclusion):
            raise ScopeEnforcementViolation(
                checkpoint,
                f"URL {url!r} matches exclusion {exclusion!r} of authorization "
                f"{authorization.authorization_id!r}",
            )
    return normalized


def _require_canonical_v2_allowlist(
    authorization: VerifiedAuthorization,
) -> tuple[str, ...]:
    """Relit défensivement la frontière V2 déjà vérifiée.

    Le modèle canonique et PostgreSQL garantissent normalement ces
    invariants. Les reproduire au point d'usage empêche toutefois un état
    injecté, une doublure de test défectueuse ou une future régression de
    désérialisation de transformer ``None``/``()`` en autorisation large.
    """
    allowlist = authorization.allowed_content_sha256
    if not isinstance(allowlist, tuple) or not allowlist:
        raise ScopeEnforcementViolation(
            "content",
            f"authorization {authorization.authorization_id!r} is LOT41A-V2 "
            "but has no canonical non-empty allowed_content_sha256 boundary",
        )
    if any(
        not isinstance(value, str) or not _LOWERCASE_SHA256_RE.fullmatch(value)
        for value in allowlist
    ):
        raise ScopeEnforcementViolation(
            "content",
            f"authorization {authorization.authorization_id!r} carries a malformed "
            "allowed_content_sha256 boundary",
        )
    if tuple(sorted(allowlist)) != allowlist or len(set(allowlist)) != len(allowlist):
        raise ScopeEnforcementViolation(
            "content",
            f"authorization {authorization.authorization_id!r} carries a non-canonical "
            "allowed_content_sha256 boundary",
        )
    return allowlist


def enforce_content_sha256(
    authorization: VerifiedAuthorization, *, content_sha256: str
) -> None:
    """Contrôle les octets téléchargés avant ``FETCHED`` et tout stockage.

    V1 conserve sa sémantique historique : il ne possède pas de frontière
    de contenu et ce point de contrôle ne lui en invente aucune. La politique
    H2, distincte, appelle :func:`require_h2_content_bound_authority` quand
    elle exige explicitement V2.
    """
    if authorization.protocol_version == "LOT41A-V1":
        return
    if authorization.protocol_version != "LOT41A-V2":
        raise ScopeEnforcementViolation(
            "content",
            f"authorization {authorization.authorization_id!r} uses unsupported "
            f"protocol {authorization.protocol_version!r}",
        )
    if not isinstance(content_sha256, str) or not _LOWERCASE_SHA256_RE.fullmatch(
        content_sha256
    ):
        raise ScopeEnforcementViolation(
            "content", f"downloaded content SHA-256 {content_sha256!r} is not canonical"
        )
    allowlist = _require_canonical_v2_allowlist(authorization)
    if content_sha256 not in allowlist:
        raise ScopeEnforcementViolation(
            "content",
            f"downloaded content SHA-256 {content_sha256!r} is not in authorization "
            f"{authorization.authorization_id!r} allowed_content_sha256",
        )


def require_h2_content_bound_authority(authorization: VerifiedAuthorization) -> None:
    """Exige la frontière positive requise par la politique H2 réelle."""
    if authorization.protocol_version != "LOT41A-V2":
        raise ScopeEnforcementViolation(
            "content",
            "CONTENT_ALLOWLIST_AUTHORITY_REQUIRED: H2 real-document publication "
            "requires a LOT41A-V2 authorization",
        )
    _require_canonical_v2_allowlist(authorization)


def _matches_exclusion(*, url: str, hostname: str, exclusion: str) -> bool:
    """Une exclusion vise soit un hôte entier, soit un préfixe de chemin.

    Volontairement littéral : ni glob ni expression régulière. Une
    exclusion doit être lisible sans ambiguïté par l'humain qui approuve
    l'artefact — une syntaxe de motif y introduirait un écart entre ce
    qu'il lit et ce que la machine applique."""
    if exclusion == hostname:
        return True
    parts = urlsplit(url)
    path = parts.path or "/"
    if exclusion.startswith("/"):
        return path == exclusion or path.startswith(exclusion.rstrip("/") + "/")
    if "/" in exclusion:
        excluded_host, _, excluded_path = exclusion.partition("/")
        excluded_path = "/" + excluded_path
        return excluded_host == hostname and (
            path == excluded_path or path.startswith(excluded_path.rstrip("/") + "/")
        )
    return False


def enforce_rights(
    authorization: VerifiedAuthorization, *, rights: Rights | str, now: datetime | None = None
) -> None:
    """Troisième point de contrôle : la catégorie de droits **produite par
    le pipeline** doit appartenir à celles autorisées.

    L'autorisation ne décide pas des droits — le RightsAgent le fait. Elle
    décide seulement lesquels sont publiables sous ce scope."""
    value = rights.value if isinstance(rights, Rights) else str(rights)
    if now is not None:
        enforce_validity_window(authorization, now=now, checkpoint="rights")
    if value == Rights.unknown.value:
        raise ScopeEnforcementViolation(
            "rights",
            "the pipeline produced rights_status='unknown' — undetermined "
            "rights are never covered by any authorization",
        )
    if value not in authorization.rights_categories:
        raise ScopeEnforcementViolation(
            "rights",
            f"rights category {value!r} is not among the authorized categories "
            f"{list(authorization.rights_categories)!r} of authorization "
            f"{authorization.authorization_id!r}",
        )


def enforce_pii(
    authorization: VerifiedAuthorization,
    *,
    pii_detected: bool,
    reviewed_accepted: bool = False,
) -> None:
    """Quatrième point de contrôle : politique PII (élargi par ADR-0047).

    Une détection reste un refus. La seule exception est nommée : une revue
    humaine documentée, scellée et vérifiée l'a admise, fait que seul le
    registre de preuves peut établir — jamais l'appelant, jamais le payload
    du job. ``reviewed_accepted`` vaut ``False`` par défaut, pour qu'un
    appelant qui l'ignore reste du côté fermé.

    **Les deux dimensions restent INDÉPENDANTES.** ADR-0047 le dit dès son
    en-tête : « ce document ne lève aucun verrou — `pii_absence_required` reste
    `true` sur tous les cas d'autorisation ; ce que ce contrat rend admissible
    est une DÉTECTION revue et jugée non personnelle ou publique et licite ».
    L'admission porte donc sur un CONTENU ; l'attestation porte sur une
    AUTORISATION. Faire dépendre la seconde de la première ouvrirait une
    autorisation qui n'atteste rien, sur la foi d'un verdict qui ne parle pas
    d'elle. Le contrat rend d'ailleurs le cas irreprésentable —
    `ScopeAuthorizationArtifact` refuse `pii_absence_attested=False` — et cette
    garde reste volontairement redondante par construction."""
    if pii_detected and not reviewed_accepted:
        raise ScopeEnforcementViolation(
            "pii",
            f"PII was detected in a document under authorization "
            f"{authorization.authorization_id!r} and no approved human review "
            "admits it — this release ingests no unreviewed PII",
        )
    if not authorization.pii_absence_attested:
        raise ScopeEnforcementViolation(
            "pii",
            f"authorization {authorization.authorization_id!r} does not attest "
            "PII absence",
        )


__all__ = [
    "ScopeEnforcementViolation",
    "enforce_before_fetch",
    "enforce_content_sha256",
    "enforce_destination",
    "enforce_pii",
    "enforce_rights",
    "enforce_validity_window",
    "require_h2_content_bound_authority",
]
