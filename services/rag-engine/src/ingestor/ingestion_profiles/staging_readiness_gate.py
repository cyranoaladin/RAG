"""Porte d'entrée d'une **répétition** — distincte de celle de production.

``enforce_readiness_gate`` (``readiness_gate.py``) répond à : *l'hôte
exécute-t-il exactement la release relue et promue ?* Ce module n'y touche
pas, ne l'appelle pas, et ne partage avec lui ni ancre, ni protocole, ni
variable. Il répond à une autre question : *ai-je le droit d'ingérer CE
corpus, avec CE code, dans CE plan de contrôle ?*

**Aucune valeur de repli.** Chaque variable absente, vide, ou faite
d'espaces est un refus — jamais un défaut silencieux. En particulier
``NEXUS_ENVIRONMENT`` n'a pas de défaut ici : non renseignée, elle refuse,
au lieu de retomber sur une valeur que personne n'a écrite.

**Trois barrières contre l'emprunt de l'autorité de production**, chacune
suffisante à elle seule :

1. l'ancre de production porte ``NEXUS-PRODUCTION-READINESS-V1`` et échoue
   donc au parsing d'une ancre de répétition — pointer la variable sur son
   chemin ne marche pas ;
2. ce module refuse **nommément** un chemin d'ancre qui désigne l'ancre
   gouvernée de production, avant même de la lire ;
3. le littéral ``environment: "rehearsal"`` du contrat rend une clé ou un
   manifeste de production structurellement inacceptables.

La première suffirait. Les trois existent parce qu'une seule garde, un jour,
se contourne par un chemin auquel personne n'avait pensé.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nexus_contracts.staging_readiness import (
    REHEARSAL_ENVIRONMENT,
    STAGING_READINESS_PROTOCOL,
    StagingReadinessError,
    StagingReadinessManifestV1,
    parse_staging_readiness_trust_anchor,
    verify_staging_readiness_manifest,
)

from .readiness_gate import ENVIRONMENT_ENV, GOVERNED_TRUST_ANCHOR_PATH

#: Les cinq variables. Aucune n'a de défaut, aucune n'accepte le vide.
EXPECTED_PROTOCOL_ENV = "NEXUS_EXPECTED_READINESS_PROTOCOL"
MANIFEST_PATH_ENV = "NEXUS_READINESS_MANIFEST_PATH"
MANIFEST_SHA256_ENV = "NEXUS_READINESS_MANIFEST_SHA256"
TRUST_ANCHOR_ENV = "NEXUS_STAGING_READINESS_TRUST_ANCHOR"

#: Identité de l'image RÉELLEMENT en cours d'exécution.
#:
#: Le manifeste signé nomme une image ; rien, jusqu'ici, ne vérifiait que
#: c'était celle qui tournait. Un conteneur lancé depuis une autre image
#: passait donc le gate sans être détecté — la signature couvrait une
#: intention, pas un fait.
#:
#: Un processus ne peut pas lire de façon fiable le digest de l'image dont il
#: est issu : ``/proc`` ne le porte pas, et le lire depuis le conteneur
#: reviendrait à demander au suspect de décliner son identité. L'inspection
#: se fait donc sur l'HÔTE (``docker inspect --format '{{index .RepoDigests
#: 0}}'``), et le résultat est injecté ici. Le runbook impose cet ordre :
#: inspecter d'abord, injecter ensuite, jamais une valeur écrite à la main.
ACTUAL_WORKER_IMAGE_ENV = "NEXUS_ACTUAL_WORKER_IMAGE"

#: Une référence d'image n'est une identité que si elle porte un digest.
_PINNED_IMAGE_REF = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")

_FAILURE_PREFIX = "STAGING_READINESS_GATE_FAILED"


class StagingReadinessGateError(RuntimeError):
    """Refus de démarrage. Ce module ne connaît aucune autre issue."""


@dataclass(frozen=True)
class StagingReadinessGateResult:
    """Ce qui a été vérifié — jamais ce qui a été supposé."""

    environment: str
    manifest: StagingReadinessManifestV1
    manifest_sha256: str
    trust_anchor_path: Path
    verified_at: datetime


def _fail(reason: str) -> StagingReadinessGateError:
    return StagingReadinessGateError(f"{_FAILURE_PREFIX}: {reason}")


def _required_env(name: str) -> str:
    """Une variable absente et une variable vide sont le même refus.

    Une chaîne d'espaces est le cas le plus traître : elle « existe »,
    passe un test de présence, et ne nomme rien."""
    raw = os.environ.get(name)
    if raw is None:
        raise _fail(f"{name} is not configured — no default is ever assumed here")
    if not raw.strip():
        raise _fail(
            f"{name} is set but blank — a blank value names nothing and is never "
            "treated as absent-but-acceptable"
        )
    return raw.strip()


def _governed_production_anchor() -> Path:
    """Chemin de l'ancre gouvernée de production, dérivé comme elle l'est."""
    root = Path(__file__).resolve().parents[5]
    return root / GOVERNED_TRUST_ANCHOR_PATH


def _require_no_symlink_component(path: Path, *, label: str) -> None:
    """Un composant en lien symbolique rendrait le chemin vérifié menteur."""
    absolute = path.absolute()
    walked = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        walked /= part
        if walked.is_symlink():
            raise _fail(f"{label} path component {walked} is a symlink")


def _read_anchor(raw_path: str) -> tuple[Path, bytes]:
    candidate = Path(raw_path)
    governed = _governed_production_anchor()
    # Barrière 2 : refus NOMMÉ, avant toute lecture. Le contrat refuserait
    # de toute façon ce fichier, mais un refus qui dit pourquoi vaut mieux
    # qu'une erreur de parsing que l'opérateur devra interpréter.
    try:
        same_file = candidate.resolve() == governed.resolve()
    except OSError:  # pragma: no cover - dépend du système de fichiers
        same_file = False
    if same_file or candidate.name == governed.name:
        raise _fail(
            f"{TRUST_ANCHOR_ENV} points at the governed PRODUCTION readiness "
            f"anchor ({candidate}) — a rehearsal never borrows the production "
            "anchor, and this chain never signs for production"
        )
    _require_no_symlink_component(candidate, label="staging readiness trust anchor")
    if not candidate.is_file():
        raise _fail(f"staging readiness trust anchor {candidate} does not exist")
    return candidate, candidate.read_bytes()


def enforce_staging_readiness_gate(
    *, now: datetime | None = None
) -> StagingReadinessGateResult:
    """Refuse tout ce qui ne prouve pas cette répétition-ci.

    ``now`` n'existe que pour les tests de fenêtre de validité ; un appelant
    réel ne le fournit pas et laisse ce module lire l'horloge, de sorte
    qu'une revalidation ultérieure voie réellement le temps passer.
    """
    moment = now or datetime.now(UTC)

    environment = _required_env(ENVIRONMENT_ENV)
    if environment != REHEARSAL_ENVIRONMENT:
        raise _fail(
            f"{ENVIRONMENT_ENV} is {environment!r}; this chain only ever runs "
            f"under {REHEARSAL_ENVIRONMENT!r} and has no authority in production"
        )

    protocol = _required_env(EXPECTED_PROTOCOL_ENV)
    if protocol != STAGING_READINESS_PROTOCOL:
        raise _fail(
            f"{EXPECTED_PROTOCOL_ENV} must explicitly pin "
            f"{STAGING_READINESS_PROTOCOL!r}; got {protocol!r}"
        )

    manifest_path = Path(_required_env(MANIFEST_PATH_ENV))
    expected_sha256 = _required_env(MANIFEST_SHA256_ENV).lower()
    _require_no_symlink_component(manifest_path, label="staging readiness manifest")
    if not manifest_path.is_file():
        raise _fail(f"staging readiness manifest {manifest_path} does not exist")
    raw = manifest_path.read_bytes()
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise _fail(
            f"staging readiness manifest digest mismatch: {MANIFEST_SHA256_ENV} "
            f"names {expected_sha256}, the file on disk is {observed_sha256}"
        )

    anchor_path, anchor_bytes = _read_anchor(_required_env(TRUST_ANCHOR_ENV))

    try:
        anchor = parse_staging_readiness_trust_anchor(anchor_bytes)
        manifest = verify_staging_readiness_manifest(
            raw, trust_anchor=anchor, now=moment
        )
    except StagingReadinessError as exc:
        raise _fail(str(exc)) from exc

    return StagingReadinessGateResult(
        environment=environment,
        manifest=manifest,
        manifest_sha256=observed_sha256,
        trust_anchor_path=anchor_path,
        verified_at=moment,
    )


def require_running_image_matches_manifest(
    manifest: StagingReadinessManifestV1, *, actual: str | None = None
) -> str:
    """Exige que l'image en cours soit EXACTEMENT celle que le manifeste signe.

    Aucun repli : la variable absente est un refus, pas une dispense. Une
    référence sans digest est un refus : un tag désigne une cible mouvante,
    et la signature porterait alors sur un nom, pas sur des octets.

    ``actual`` n'existe que pour les tests ; un appelant réel laisse ce module
    lire l'environnement que le runbook a rempli après inspection sur l'hôte.
    """
    declared = getattr(manifest, "worker_image", None)
    if not isinstance(declared, str) or not declared.strip():
        raise _fail(
            "the signed staging readiness manifest names no worker_image — "
            "there is nothing to bind the running image to"
        )
    declared = declared.strip()
    if _PINNED_IMAGE_REF.fullmatch(declared) is None:
        raise _fail(
            f"the signed manifest declares worker_image {declared!r}, which is "
            "not pinned as name@sha256:<64 hex>"
        )

    observed = actual if actual is not None else os.environ.get(ACTUAL_WORKER_IMAGE_ENV)
    if observed is None:
        raise _fail(
            f"{ACTUAL_WORKER_IMAGE_ENV} is not configured — the running image "
            "must be inspected on the host and injected; it is never assumed"
        )
    if not observed.strip():
        raise _fail(
            f"{ACTUAL_WORKER_IMAGE_ENV} is set but blank — a blank value names "
            "no image and is never treated as absent-but-acceptable"
        )
    observed = observed.strip()
    if _PINNED_IMAGE_REF.fullmatch(observed) is None:
        raise _fail(
            f"{ACTUAL_WORKER_IMAGE_ENV} is {observed!r}, which carries no digest "
            "— a tag is a moving target, never an identity"
        )
    if observed != declared:
        raise _fail(
            f"the running image is {observed}, but the signed readiness manifest "
            f"authorises {declared} — the signature covers that image and no other"
        )
    return observed


def require_control_dsn_differs_from_product(
    *, control_dsn: str, product_dsn: str | None
) -> None:
    """Vérifie l'invariant que le manifeste DÉCLARE, au lieu de le croire.

    ``control_dsn_differs_from_product`` est un littéral ``True`` dans le
    contrat : le manifeste ne peut pas dire autre chose. Raison de plus pour
    le mesurer — une déclaration qu'on ne peut pas contredire ne prouve rien
    par elle-même."""
    if product_dsn is None or not product_dsn.strip():
        return
    if control_dsn.strip() == product_dsn.strip():
        raise _fail(
            "the ingestion-control DSN and the product DSN are the same "
            "connection — the staging readiness manifest declares them distinct, "
            "and they are not"
        )


__all__ = [
    "ACTUAL_WORKER_IMAGE_ENV",
    "EXPECTED_PROTOCOL_ENV",
    "MANIFEST_PATH_ENV",
    "MANIFEST_SHA256_ENV",
    "TRUST_ANCHOR_ENV",
    "StagingReadinessGateError",
    "StagingReadinessGateResult",
    "enforce_staging_readiness_gate",
    "require_control_dsn_differs_from_product",
    "require_running_image_matches_manifest",
]
