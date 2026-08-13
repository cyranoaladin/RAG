"""Gate de readiness au runtime — défense en profondeur (ADR-0036).

**Ce que ce gate n'est pas.** Ce n'est pas une protection cryptographique
contre l'administrateur de l'hôte. Un root hostile ou compromis peut
remplacer ce fichier, patcher ce module, changer l'environnement ou
parler directement à PostgreSQL. Le modèle de menace d'ADR-0036 place
explicitement le root de l'hôte dans la base de confiance.

**Ce qu'il ferme réellement**, et c'est utile :

* le déploiement normal privé de preuve — un worker démarré sans qu'aucune
  chaîne de promotion n'ait abouti ;
* l'erreur de configuration — un manifeste d'un autre environnement, d'une
  autre release, ou dont le gate H2 n'était pas passant ;
* la substitution par un processus non privilégié — le fichier est refusé
  s'il est inscriptible par autre chose que son propriétaire ;
* le démarrage incomplet — un worker qui tournerait avec une partie
  seulement de sa chaîne d'autorité.

**Où il s'applique.** Avant le démarrage du worker, et **de nouveau** avant
chaque création de job de mutation. Le second point n'est pas redondant :
un manifeste retiré ou remplacé après le démarrage ne serait jamais vu par
un contrôle qui ne s'exécuterait qu'une fois, et la création de job est la
mutation qui compte.

**Il ne duplique aucun parseur.** Toute la validation vient du contrat
partagé ``nexus_contracts.production_readiness`` — le même que celui
qu'utilisera le wrapper de déploiement. Deux implémentations finiraient
par diverger, et un manifeste interprété différemment par le vérificateur
et par l'exécutant n'est plus une preuve.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from nexus_contracts.production_readiness import (
    PRODUCTION_ENVIRONMENT,
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    parse_production_readiness_trust_anchor,
    require_manifest_matches_release,
    verify_production_readiness_manifest,
)

#: Chemin du manifeste déposé par le wrapper de déploiement, monté en
#: lecture seule dans le conteneur.
MANIFEST_PATH_ENV = "NEXUS_READINESS_MANIFEST_PATH"

#: Commit de merge que ce déploiement croit exécuter. Injecté par le
#: wrapper ; comparé au manifeste signé.
RELEASE_SHA_ENV = "NEXUS_RELEASE_SHA"

#: ``production`` (défaut, fail-closed) ou ``rehearsal``.
ENVIRONMENT_ENV = "NEXUS_ENVIRONMENT"

#: Ancre publique de readiness. En production, **jamais** substituable par
#: un argument : le chemin est gouverné et versionné dans le dépôt.
GOVERNED_TRUST_ANCHOR_PATH = "governance/trust-anchors/production-readiness-v1.json"

#: Ancre de rehearsal, explicitement distincte.
#:
#: L'isolation entre répétition et production se fait par **identité du
#: fichier d'ancre**, pas par une étiquette dans le manifeste. Le contrat
#: ``NEXUS-PRODUCTION-READINESS-V1`` fixe ``environment="production"`` par
#: littéral, et ADR-0036 interdit de l'affaiblir pour accueillir une
#: répétition : un manifeste et une répétition de manifeste doivent rester
#: discernables. La conséquence est nette — le mode production ne lit
#: **que** le chemin gouverné, donc une clé de répétition déclarée dans un
#: autre fichier n'a aucun moyen d'être consultée en production, quel que
#: soit ce qu'elle affirme sur elle-même.
REHEARSAL_TRUST_ANCHOR_ENV = "NEXUS_READINESS_REHEARSAL_TRUST_ANCHOR"

#: Racine gouvernée, dérivée de l'emplacement de CE fichier — aucun
#: override, par aucun moyen. Même discipline que le gate H2-B côté
#: rag-pedago : une racine redirigeable rendrait « ancre gouvernée »
#: dépourvu de sens.
#:
#: Ce fichier vit à ``services/rag-engine/src/ingestor/ingestion_profiles/``,
#: soit 5 niveaux sous la racine du dépôt (ingestion_profiles, ingestor,
#: src, rag-engine, services) — jamais 3, qui désignerait ``services/
#: rag-engine`` lui-même et ferait échouer la résolution des marqueurs sur
#: tout checkout réel (cf. le même calcul pour le gate H2-B, ``rag_pedago/
#: imports/h2b_coverage_report.py``, 4 niveaux sous sa racine avec un seul
#: répertoire de paquet entre le fichier et le service).
_GOVERNED_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]

#: Marqueurs du dépôt. La dérivation par remontée n'est vraie que dans un
#: checkout ; installée ailleurs, elle désignerait un répertoire
#: arbitraire où une ancre déposée ferait autorité.
_GOVERNED_ROOT_MARKERS = ("services/rag-engine", "docs/adr")

_FAILURE_PREFIX = "WORKER_READINESS_GATE_FAILED"


class ReadinessGateError(RuntimeError):
    """Le manifeste ne prouve pas cette release — refus, jamais un défaut
    permissif."""


@dataclass(frozen=True)
class ReadinessGateResult:
    manifest: ProductionReadinessManifestV1
    manifest_path: Path
    environment: str
    release_sha: str


def _fail(reason: str) -> ReadinessGateError:
    return ReadinessGateError(f"{_FAILURE_PREFIX}: {reason}")


def _governed_anchor_path() -> Path:
    root = _GOVERNED_REPOSITORY_ROOT
    for marker in _GOVERNED_ROOT_MARKERS:
        if not (root / marker).exists():
            raise _fail(
                f"{root} does not look like the Nexus repository checkout "
                f"(missing {marker}); the governed readiness anchor cannot be "
                "resolved from an arbitrary directory"
            )
    candidate = root / GOVERNED_TRUST_ANCHOR_PATH
    walked = root
    for part in Path(GOVERNED_TRUST_ANCHOR_PATH).parts:
        walked = walked / part
        if walked.is_symlink():
            raise _fail(
                f"{walked} is a symlink — a governed path never redirects, on "
                "any of its components"
            )
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root / GOVERNED_TRUST_ANCHOR_PATH:
        raise _fail(
            f"resolved anchor {resolved} is not the canonical governed path"
        )
    return candidate


def _read_manifest_file(path: Path) -> bytes:
    """Lit le manifeste avec les refus de substitution.

    Les permissions sont vérifiées parce que le risque couvert est la
    substitution par un processus **non privilégié** : un fichier
    inscriptible par le groupe ou par tous n'est pas une preuve."""
    if path.is_symlink():
        raise _fail(
            f"{path} is a symlink — the readiness manifest is never followed "
            "through a redirection"
        )
    if not path.exists():
        raise _fail(
            f"{path} does not exist — this deployment carries no proof that a "
            "governed promotion produced it"
        )
    if not path.is_file():
        raise _fail(f"{path} is not a regular file")
    mode = path.stat().st_mode
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _fail(
            f"{path} is group- or world-writable — a manifest any process can "
            "rewrite proves nothing"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _fail(f"cannot read {path}: {exc}") from exc


def _resolve_anchor_bytes(environment: str) -> bytes:
    if environment == PRODUCTION_ENVIRONMENT:
        anchor = _governed_anchor_path()
        if not anchor.is_file():
            raise _fail(
                f"the governed production readiness anchor {anchor} does not "
                "exist — an unanchored signature proves nothing"
            )
        return anchor.read_bytes()

    raw_path = os.environ.get(REHEARSAL_TRUST_ANCHOR_ENV, "").strip()
    if not raw_path:
        raise _fail(
            f"{REHEARSAL_TRUST_ANCHOR_ENV} is required in rehearsal mode — a "
            "rehearsal never borrows the production anchor"
        )
    candidate = Path(raw_path)
    if not candidate.is_file():
        raise _fail(f"rehearsal readiness anchor {candidate} does not exist")
    return candidate.read_bytes()


def enforce_readiness_gate(
    *,
    manifest_path: Path | None = None,
    release_sha: str | None = None,
    environment: str | None = None,
) -> ReadinessGateResult:
    """Refuse tout ce qui ne prouve pas *cette* release.

    Les paramètres existent pour les tests et pour un appelant qui a déjà
    lu son environnement ; ils ne peuvent pas désigner une **ancre**, qui
    reste gouvernée en production. Aucune valeur de repli : chaque absence
    est un refus."""
    resolved_environment = (
        environment
        if environment is not None
        else os.environ.get(ENVIRONMENT_ENV, PRODUCTION_ENVIRONMENT).strip()
        or PRODUCTION_ENVIRONMENT
    )
    if resolved_environment not in (PRODUCTION_ENVIRONMENT, "rehearsal"):
        raise _fail(
            f"{ENVIRONMENT_ENV} must be 'production' or 'rehearsal', got "
            f"{resolved_environment!r}"
        )

    raw_manifest_path = (
        str(manifest_path)
        if manifest_path is not None
        else os.environ.get(MANIFEST_PATH_ENV, "").strip()
    )
    if not raw_manifest_path:
        raise _fail(
            f"{MANIFEST_PATH_ENV} is not configured — a worker never starts "
            "without naming the readiness manifest it runs under"
        )

    resolved_release_sha = (
        release_sha
        if release_sha is not None
        else os.environ.get(RELEASE_SHA_ENV, "").strip()
    )
    if not resolved_release_sha:
        raise _fail(
            f"{RELEASE_SHA_ENV} is not configured — without it the manifest "
            "cannot be tied to the revision actually running"
        )

    raw = _read_manifest_file(Path(raw_manifest_path))
    anchor_bytes = _resolve_anchor_bytes(resolved_environment)

    try:
        anchor = parse_production_readiness_trust_anchor(anchor_bytes)
        # ``environment`` reste ``production`` dans les deux modes : c'est
        # la valeur que le contrat impose au manifeste, et l'isolation
        # d'une répétition tient au fichier d'ancre consulté, jamais à un
        # assouplissement du contrat.
        manifest = verify_production_readiness_manifest(
            raw, trust_anchor=anchor, environment=PRODUCTION_ENVIRONMENT
        )
        require_manifest_matches_release(
            manifest, release_sha=resolved_release_sha
        )
    except ProductionReadinessError as exc:
        raise _fail(str(exc)) from exc

    return ReadinessGateResult(
        manifest=manifest,
        manifest_path=Path(raw_manifest_path),
        environment=resolved_environment,
        release_sha=resolved_release_sha,
    )


__all__ = [
    "ENVIRONMENT_ENV",
    "GOVERNED_TRUST_ANCHOR_PATH",
    "MANIFEST_PATH_ENV",
    "REHEARSAL_TRUST_ANCHOR_ENV",
    "RELEASE_SHA_ENV",
    "ReadinessGateError",
    "ReadinessGateResult",
    "enforce_readiness_gate",
]
