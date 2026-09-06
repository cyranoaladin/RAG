"""Calcule l'ensemble des contenus que la lignée ACTIVE promeut aujourd'hui.

`pii_review_index_20260903.json` scelle l'ensemble d'une revue humaine passée
— il ne dit rien de ce que la lignée courante sert. Ce script part donc de
l'autorité qui désigne les releases actives, le **registre canonique**.

**Il ne décide rien de la structure des releases.** Toute la sémantique —
quelles natures de release existent, comment leurs sujets sont scellés, où
vivent les contenus, quels comptes doivent tomber juste — appartient à
``nexus_release_chain.release_readiness``, que le RUNTIME de production
consomme déjà. La réimplémenter ici produisait un second runtime : chaque
règle omise devenait un faux vert, chaque règle ajoutée en amont demandait
d'être redécouverte ici. Onze rondes de revue ont mesuré ce coût.

Une seule autorité, donc. Ce fichier ne fait plus que deux choses que le
chargeur ne peut pas faire à sa place :

1. borner le chemin du registre à la racine gouvernée — une autorité
   d'entrée extérieure au périmètre qu'elle prétend gouverner ne le gouverne
   pas, et ses empreintes internes fussent-elles cohérentes ne prouveraient
   que la lecture du fichier désigné ;
2. réduire ce que le chargeur rend à l'ensemble des ``content_sha256``
   distincts, avec la formule d'empreinte du vérificateur CAS.

Ce script ne lit que des données publiques du dépôt — jamais le store privé.

Usage :
    python scripts/qualification/compute_promoted_content_set.py \\
        --output /tmp/promoted-content-set.json
    python scripts/qualification/compute_promoted_content_set.py \\
        --release-registry <registre figé de la candidate> --output …
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nexus_release_chain.release_readiness import (  # noqa: E402
    ReleaseReadinessError,
    load_release_registry_file,
)
from verify_corpus_cas import content_set_digest  # noqa: E402

#: Variables par lesquelles un DÉPLOIEMENT désigne le registre qu'il sert.
#: Ce sont celles que le runtime lit (`retrieval_v2_endpoint`), et non un
#: second câblage : sans elles, une stack pointée ailleurs par
#: `RAG_RELEASE_REGISTRY_HOST_DIR` verrait C1 qualifier l'ancien registre et
#: rendre vert sur un périmètre que personne ne sert.
REGISTRY_PATH_ENV = "RAG_RELEASE_REGISTRY_PATH"
REGISTRY_SHA256_ENV = "RAG_RELEASE_REGISTRY_SHA256"

#: Racine gouvernée, quand le registre vient d'un déploiement. La borne reste
#: exercée — mais contre la racine de CE déploiement, pas contre celle du
#: dépôt, qu'un conteneur ne connaît pas.
GOVERNED_ROOT_ENV = "NEXUS_C1_GOVERNED_ROOT"

#: Registre canonique de l'année scolaire servie. C'est un DÉFAUT, pas une
#: vérité en dur : `--release-registry` permet de qualifier une candidate
#: figée sans réécrire ce script.
DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "release-registry.json"
)

#: Racine sous laquelle le registre doit se résoudre.
GOVERNED_ROOT = (
    Path(__file__).resolve().parents[2] / "services" / "rag-pedago" / "data" / "releases"
)


class PromotedContentSetError(RuntimeError):
    """L'ensemble promu n'est pas celui que les autorités déclarent — refus."""


def _racine_gouvernee() -> Path:
    """La racine contre laquelle borner, telle que le déploiement la déclare."""
    declaree = os.environ.get(GOVERNED_ROOT_ENV)
    if declaree:
        return Path(declaree)
    return GOVERNED_ROOT


def registre_du_deploiement() -> tuple[Path | None, str | None]:
    """Le registre que la stack SERT, s'il en désigne un.

    Un déploiement peut monter un autre registre. Lire les mêmes variables que
    le runtime évite que C1 qualifie une lignée pendant qu'une autre est
    servie."""
    chemin = os.environ.get(REGISTRY_PATH_ENV)
    return (Path(chemin) if chemin else None, os.environ.get(REGISTRY_SHA256_ENV))


def _borner(chemin: Path) -> Path:
    """Prouve que le registre est DANS le périmètre gouverné, avant lecture.

    `..`, chemin absolu et lien symbolique sur n'importe quel composant sont
    refusés. Un lien vers l'extérieur est déjà attrapé par la borne de racine ;
    un lien INTERNE ne l'est pas — sa résolution reste à l'intérieur — et
    seule l'inspection de chaque composant le voit."""
    ancre = _racine_gouvernee().resolve(strict=False)
    resolu = chemin.resolve(strict=False)
    try:
        resolu.relative_to(ancre)
    except ValueError as exc:
        raise PromotedContentSetError(
            f"registre : {chemin.as_posix()} se résout hors de la racine "
            f"gouvernée ({ancre.as_posix()})"
        ) from exc

    courant = chemin if chemin.is_absolute() else Path.cwd() / chemin
    vus: set[Path] = set()
    while courant not in vus:
        vus.add(courant)
        if courant.is_symlink():
            raise PromotedContentSetError(
                f"registre : {courant.as_posix()} est un lien symbolique — un "
                "chemin gouverné ne redirige sur aucun de ses composants"
            )
        if courant.resolve(strict=False) == ancre or courant.parent == courant:
            break
        courant = courant.parent

    if not resolu.is_file():
        raise PromotedContentSetError(f"registre : {chemin.as_posix()} est introuvable")
    return resolu


def collect_promoted_content_set(
    registry_path: Path, expected_sha256: str | None = None
) -> set[str]:
    """L'union des contenus que TOUTES les releases actives du registre servent.

    La validation entière — natures supportées, sceaux, comptes, autorités,
    partitions de pages, collisions — est celle du chargeur canonique, celui
    que le runtime consomme. On n'en refait aucune."""
    resolu = _borner(registry_path)
    # Le registre est l'autorité d'ENTRÉE : le sceller contre lui-même ne
    # prouverait rien de plus que la borne ci-dessus. Une candidate figée
    # peut en revanche fournir son empreinte externe, et elle est alors
    # exigée telle quelle par le chargeur.
    attendue = expected_sha256 or hashlib.sha256(resolu.read_bytes()).hexdigest()
    try:
        registre = load_release_registry_file(resolu, attendue)
    except (ReleaseReadinessError, OSError, ValueError) as exc:
        raise PromotedContentSetError(
            f"{registry_path.name} : {type(exc).__name__}: {exc}"
        ) from exc

    contenus = {
        artefact.content_sha256
        for manifeste in registre.manifests
        for artefact in manifeste.expectation.artifacts
    }
    if not contenus:
        raise PromotedContentSetError(
            "aucun contenu promu : le contrôle de couverture serait vrai par vacuité"
        )
    return contenus


def collect_promoted_collections(
    registry_path: Path, expected_sha256: str | None = None
) -> set[str]:
    """Les collections que la lignée active sert, telles que le chargeur les rend."""
    resolu = _borner(registry_path)
    attendue = expected_sha256 or hashlib.sha256(resolu.read_bytes()).hexdigest()
    try:
        return set(load_release_registry_file(resolu, attendue).collections)
    except (ReleaseReadinessError, OSError, ValueError) as exc:
        raise PromotedContentSetError(
            f"{registry_path.name} : {type(exc).__name__}: {exc}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    depuis_deploiement, sceau_deploiement = registre_du_deploiement()
    parser.add_argument(
        "--release-registry",
        type=Path,
        default=depuis_deploiement or DEFAULT_REGISTRY,
        help=(
            "registre désignant les releases actives ; le registre figé d'une "
            "candidate permet de qualifier celle-ci sans réécrire ce script"
        ),
    )
    parser.add_argument(
        "--release-registry-sha256",
        default=sceau_deploiement,
        help="empreinte externe du registre, quand une candidate figée en fournit une",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        contents = collect_promoted_content_set(
            args.release_registry, args.release_registry_sha256
        )
    except (PromotedContentSetError, KeyError, TypeError, ValueError, OSError) as exc:
        # Une trace Python en CI dit où le code s'est arrêté, pas ce qui est
        # faux dans la lignée. Le gate doit nommer le défaut.
        print(f"::error::PROMOTED_CONTENT_SET_INVALID: {exc}", file=sys.stderr)
        return 2

    payload = {
        "content_sha256": sorted(contents),
        "count": len(contents),
        "content_set_sha256": content_set_digest(contents),
        "release_registry": args.release_registry.name,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PROMOTED_CONTENT_SET_COUNT={payload['count']}")
    print(f"PROMOTED_CONTENT_SET_SHA256={payload['content_set_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
