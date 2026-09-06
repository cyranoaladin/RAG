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


def _lire_gouverne(chemin: Path, quoi: str) -> bytes:
    """Primitive CANONIQUE d'accès à une autorité. Toutes les entrées passent
    par elle — registre compris.

    Trois implémentations de la même borne divergeraient : celle qu'on oublie
    de durcir devient le chemin d'entrée. Elle vérifie, dans cet ordre, que le
    chemin se résout DANS la racine gouvernée, qu'aucun de ses composants
    n'est un lien symbolique, et qu'il désigne un fichier ordinaire — puis
    seulement lit.

    Le registre lui-même y est soumis : une autorité d'entrée extérieure au
    périmètre qu'elle prétend gouverner ne le gouverne pas. Un faux registre
    dont toutes les empreintes seraient cohérentes prouverait seulement qu'on
    a bien lu le fichier qu'on a désigné.
    """
    racine = GOVERNED_ROOT.resolve(strict=False)
    resolu = chemin.resolve(strict=False)
    try:
        resolu.relative_to(racine)
    except ValueError as exc:
        raise PromotedContentSetError(
            f"{quoi} : {chemin.as_posix()} se résout hors de la racine gouvernée "
            f"({racine.as_posix()})"
        ) from exc

    # CHAQUE composant, pas seulement le dernier : un lien de RÉPERTOIRE
    # interne laisse la résolution finale à l'intérieur de la racine, et la
    # borne précédente le laisserait donc passer.
    courant = chemin if chemin.is_absolute() else Path.cwd() / chemin
    vus: set[Path] = set()
    while courant not in vus:
        vus.add(courant)
        if courant.is_symlink():
            raise PromotedContentSetError(
                f"{quoi} : {courant.as_posix()} est un lien symbolique — un "
                "chemin gouverné ne redirige sur aucun de ses composants"
            )
        if courant.resolve(strict=False) == racine or courant.parent == courant:
            break
        courant = courant.parent

    if not resolu.is_file():
        raise PromotedContentSetError(f"{quoi} : {chemin.as_posix()} est introuvable")
    return resolu.read_bytes()


def _charge_objet(octets: bytes, quoi: str) -> dict:
    """Décode un manifeste et exige un OBJET.

    Un JSON parfaitement valide peut être `[]`, `"registry"` ou `42` : appeler
    `.get()` dessus rendrait une trace Python là où le gate doit nommer le
    défaut."""
    try:
        charge = json.loads(octets.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PromotedContentSetError(
            f"{quoi} : illisible ({type(exc).__name__})"
        ) from exc
    if not isinstance(charge, dict):
        raise PromotedContentSetError(
            f"{quoi} : la racine du document est {type(charge).__name__}, pas un objet"
        )
    return charge


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
    registre = _charge_objet(
        _lire_gouverne(registry_path, "registre"), "registre"
    )
    racine = registry_path.resolve(strict=False).parent

    releases = registre.get("releases")
    if not isinstance(releases, list) or not releases:
        raise PromotedContentSetError(
            "le registre ne désigne aucune release active : l'ensemble promu "
            "serait vide, et un ensemble vide ne manque jamais de rien"
        )

    contenus: set[str] = set()
    for release in releases:
        if not isinstance(release, dict):
            raise PromotedContentSetError(
                f"registre : une entrée de release est {type(release).__name__}, "
                "pas un objet"
            )
        identifiant = str(release.get("release_id", "?"))
        chemin = racine / str(release["manifest_path"])
        quoi = f"release {identifiant}"
        octets = _lire_gouverne(chemin, quoi)
        _sceau_verifie(octets, release.get("expected_manifest_sha256"), quoi)
        contenus |= _contenus_dune_release(
            _charge_objet(octets, quoi), chemin, identifiant
        )

    if not contenus:
        raise PromotedContentSetError(
            "aucun contenu promu : le contrôle de couverture serait vrai par vacuité"
        )
    return contenus


def _contenus_dune_release(
    manifeste: dict, chemin: Path, identifiant: str
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
        if not isinstance(sujet, dict):
            raise PromotedContentSetError(
                f"release {identifiant} : une entrée de sujet est "
                f"{type(sujet).__name__}, pas un objet"
            )
        nom = str(sujet.get("collection", sujet.get("path", "?")))
        quoi = f"release {identifiant}, sujet {nom}"
        octets = _lire_gouverne(base / str(sujet["path"]), quoi)
        _sceau_verifie(octets, sujet.get("sha256"), quoi)
        artefacts = _charge_objet(octets, quoi).get("artifacts")
        if not isinstance(artefacts, list) or not artefacts:
            raise PromotedContentSetError(f"{quoi} : aucun artefact")
        for artefact in artefacts:
            if not isinstance(artefact, dict) or "content_sha256" not in artefact:
                raise PromotedContentSetError(
                    f"{quoi} : une entrée d'artefact ne porte pas de content_sha256"
                )
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
