"""Calcule l'ensemble des contenus que la lignée ACTIVE promeut aujourd'hui.

`pii_review_index_20260903.json` scelle l'ensemble d'une revue humaine passée
— il ne dit rien de ce que la lignée courante sert. Ce script part donc de
l'autorité qui désigne les releases actives, le **registre canonique**, et
non d'un manifeste historique nommé en dur : le corpus complet produira une
candidate bien plus large, et C1 ne doit pas être réécrit pour autant.

La chaîne, du haut vers le bas, chaque maillon confronté à son sceau :

    registre de releases
    → manifestes de release actifs      (expected_manifest_sha256)
    → manifestes de sujet scellés       (subjects[].sha256)
    → occurrences de contenu promu      (expected_counts.artifacts)
    → ensemble de contenus distincts

Ce script ne lit que des données publiques du dépôt — jamais le store privé.
Un contenu partagé par plusieurs sujets (PR #146) est compté une fois, pas
une fois par sujet qui le référence.

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_corpus_cas import content_set_digest  # noqa: E402

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

#: Racine sous laquelle tout chemin du registre doit se résoudre. Un sceau
#: correct sur un fichier HORS périmètre ne prouve rien du corpus gouverné :
#: il prouve seulement qu'on a bien lu le fichier qu'on a désigné.
GOVERNED_ROOT = (
    Path(__file__).resolve().parents[2] / "services" / "rag-pedago" / "data" / "releases"
)


class PromotedContentSetError(RuntimeError):
    """L'ensemble promu n'est pas celui que les autorités déclarent — refus."""


def _lire_borne(chemin: Path, racine: Path, quoi: str) -> bytes:
    """Lit un fichier après avoir prouvé qu'il est DANS le périmètre gouverné.

    `..`, chemin absolu et lien symbolique sortant sont refusés avant toute
    lecture : sans cette borne, une entrée de manifeste pourrait désigner un
    fichier extérieur, et son sceau correct ferait passer pour gouverné un
    contenu qui ne l'est pas."""
    ancre = racine.resolve(strict=False)
    resolu = chemin.resolve(strict=False)
    try:
        resolu.relative_to(ancre)
    except ValueError as exc:
        raise PromotedContentSetError(
            f"{quoi} : {chemin.as_posix()} se résout hors de la racine gouvernée"
        ) from exc
    # CHAQUE composant, pas seulement le dernier : un lien de répertoire
    # interne laisse la résolution finale à l'intérieur de la racine, et la
    # borne précédente le laisserait donc passer.
    courant = chemin
    while courant != racine and courant.parent != courant:
        if courant.is_symlink():
            raise PromotedContentSetError(
                f"{quoi} : {courant.as_posix()} est un lien symbolique — un chemin "
                "gouverné ne redirige sur aucun de ses composants"
            )
        courant = courant.parent
    if not resolu.is_file():
        raise PromotedContentSetError(f"{quoi} : {chemin.as_posix()} est introuvable")
    return resolu.read_bytes()


def _sceau_verifie(octets: bytes, attendu: object, quoi: str) -> None:
    if not isinstance(attendu, str) or len(attendu) != 64:
        raise PromotedContentSetError(
            f"{quoi} : empreinte déclarée absente ou illisible ({attendu!r})"
        )
    mesuree = hashlib.sha256(octets).hexdigest()
    if mesuree != attendu:
        raise PromotedContentSetError(
            f"{quoi} : l'autorité déclare {attendu[:16]}… et le fichier vaut "
            f"{mesuree[:16]}… — l'ensemble promu ne serait pas celui qu'elle scelle"
        )


def _occurrences_attendues(manifeste: dict, quoi: str) -> int:
    """`expected_counts.artifacts` est OBLIGATOIRE.

    Le tolérer absent désactivait silencieusement le seul contrôle capable de
    distinguer une lecture tronquée d'un ensemble légitimement dédupliqué."""
    comptes = manifeste.get("expected_counts")
    if not isinstance(comptes, dict):
        raise PromotedContentSetError(f"{quoi} : expected_counts absent ou illisible")
    attendues = comptes.get("artifacts")
    if isinstance(attendues, bool) or not isinstance(attendues, int):
        raise PromotedContentSetError(
            f"{quoi} : expected_counts.artifacts n'est pas un entier ({attendues!r})"
        )
    if attendues <= 0:
        raise PromotedContentSetError(
            f"{quoi} : expected_counts.artifacts vaut {attendues} — une lignée "
            "qui sert ne promeut pas zéro artefact"
        )
    return attendues


def collect_promoted_content_set(registry_path: Path) -> set[str]:
    """L'union des contenus que TOUTES les releases actives du registre servent."""
    racine = registry_path.resolve(strict=False).parent
    try:
        registre = json.loads(registry_path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromotedContentSetError(
            f"registre {registry_path.as_posix()} illisible : {type(exc).__name__}"
        ) from exc

    releases = registre.get("releases")
    if not isinstance(releases, list) or not releases:
        raise PromotedContentSetError(
            "le registre ne désigne aucune release active : l'ensemble promu "
            "serait vide, et un ensemble vide ne manque jamais de rien"
        )

    contenus: set[str] = set()
    for release in releases:
        identifiant = str(release.get("release_id", "?"))
        chemin = racine / str(release["manifest_path"])
        octets = _lire_borne(chemin, racine, f"release {identifiant}")
        _sceau_verifie(octets, release.get("expected_manifest_sha256"), f"release {identifiant}")
        contenus |= _contenus_dune_release(json.loads(octets.decode("utf-8")), chemin, racine, identifiant)

    if not contenus:
        raise PromotedContentSetError(
            "aucun contenu promu : le contrôle de couverture serait vrai par vacuité"
        )
    return contenus


def _contenus_dune_release(
    manifeste: dict, chemin: Path, racine: Path, identifiant: str
) -> set[str]:
    sujets = manifeste.get("subjects")
    if not isinstance(sujets, list) or not sujets:
        raise PromotedContentSetError(
            f"release {identifiant} : aucun sujet — une release qui sert n'est pas vide"
        )
    attendues = _occurrences_attendues(manifeste, f"release {identifiant}")

    base = chemin.parent
    contenus: set[str] = set()
    occurrences = 0
    for sujet in sujets:
        nom = str(sujet.get("collection", sujet.get("path", "?")))
        quoi = f"release {identifiant}, sujet {nom}"
        octets = _lire_borne(base / str(sujet["path"]), racine, quoi)
        _sceau_verifie(octets, sujet.get("sha256"), quoi)
        artefacts = json.loads(octets.decode("utf-8")).get("artifacts")
        if not isinstance(artefacts, list) or not artefacts:
            raise PromotedContentSetError(f"{quoi} : aucun artefact")
        for artefact in artefacts:
            contenus.add(str(artefact["content_sha256"]))
            occurrences += 1

    if occurrences != attendues:
        raise PromotedContentSetError(
            f"release {identifiant} : {occurrences} occurrence(s) d'artefact lues "
            f"contre {attendues} déclarées — lecture tronquée ou manifeste incohérent"
        )
    return contenus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help=(
            "registre désignant les releases actives ; le registre figé d'une "
            "candidate permet de qualifier celle-ci sans réécrire ce script"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        contents = collect_promoted_content_set(args.release_registry)
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
