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


def _est_sha256(valeur: object) -> bool:
    return (
        isinstance(valeur, str)
        and len(valeur) == 64
        and all(caractere in "0123456789abcdef" for caractere in valeur)
    )


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


def _compte_declare(manifeste: dict, cle: str, quoi: str) -> int:
    """Un compte déclaré est OBLIGATOIRE.

    Le tolérer absent désactivait silencieusement le seul contrôle capable de
    distinguer une lecture tronquée d'un ensemble légitimement dédupliqué."""
    comptes = manifeste.get("expected_counts")
    if not isinstance(comptes, dict):
        raise PromotedContentSetError(f"{quoi} : expected_counts absent ou illisible")
    attendues = comptes.get(cle)
    if isinstance(attendues, bool) or not isinstance(attendues, int):
        raise PromotedContentSetError(
            f"{quoi} : expected_counts.{cle} n'est pas un entier ({attendues!r})"
        )
    if attendues <= 0:
        raise PromotedContentSetError(
            f"{quoi} : expected_counts.{cle} vaut {attendues} — une lignée qui "
            "sert ne promeut pas zéro artefact"
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
        manifeste = _charge_objet(octets, quoi)
        # Le registre DÉCLARE la nature de chaque release, et cette
        # déclaration est OBLIGATOIRE. La rendre facultative laissait le
        # manifeste choisir seul son lecteur : le contrôle croisé qu'elle
        # existe pour permettre disparaissait précisément sur les registres
        # tronqués ou malformés, que le runtime refuse par ailleurs.
        annonce = release.get("release_kind")
        if annonce not in (RELEASE_V1, RELEASE_V2):
            raise PromotedContentSetError(
                f"{quoi} : le registre ne déclare pas de release_kind connu "
                f"({annonce!r}) — le manifeste choisirait alors seul son lecteur"
            )
        if annonce != manifeste.get("release_kind"):
            raise PromotedContentSetError(
                f"{quoi} : le registre annonce {annonce!r} et le manifeste porte "
                f"{manifeste.get('release_kind')!r}"
            )
        contenus |= _contenus_dune_release(manifeste, chemin, identifiant, release)

    if not contenus:
        raise PromotedContentSetError(
            "aucun contenu promu : le contrôle de couverture serait vrai par vacuité"
        )
    return contenus


#: Les deux formes de manifeste que la gouvernance produit. La V1 énumère ses
#: artefacts sujet par sujet — un contenu partagé y apparaît plusieurs fois ;
#: la V2 les rassemble dans un registre d'artefacts SCELLÉ, déjà dédupliqué.
#: Les deux sont légitimes, et la candidate complète emploiera la seconde :
#: n'en connaître qu'une obligerait à réécrire ce gate au moment précis où il
#: doit servir.
RELEASE_V1 = "MULTILEVEL_AGGREGATE_RELEASE_V1"
RELEASE_V2 = "MULTILEVEL_AGGREGATE_RELEASE_V2"


def _contenus_dune_release(
    manifeste: dict, chemin: Path, identifiant: str, entree: dict | None = None
) -> set[str]:
    nature = manifeste.get("release_kind")
    if nature == RELEASE_V2:
        return _contenus_v2(manifeste, chemin, identifiant, entree or {})
    if nature == RELEASE_V1:
        return _contenus_v1(manifeste, chemin, identifiant, entree or {})
    raise PromotedContentSetError(
        f"release {identifiant} : release_kind inconnu ({nature!r}) — le ranger "
        f"d'office dans l'une des formes connues ({RELEASE_V1}, {RELEASE_V2}) "
        "lirait ses artefacts au mauvais endroit"
    )


def _contenus_v2(
    manifeste: dict, chemin: Path, identifiant: str, entree: dict
) -> set[str]:
    """V2 : un registre d'artefacts scellé, déjà dédupliqué."""
    quoi = f"release {identifiant}"
    attendus = _compte_declare(manifeste, "unique_artifacts", quoi)

    registre = manifeste.get("artifact_registry")
    if not isinstance(registre, dict):
        raise PromotedContentSetError(
            f"{quoi} : artifact_registry absent — la V2 y range ses contenus"
        )
    cible = chemin.parent / str(registre["path"])
    octets = _lire_gouverne(cible, f"{quoi}, registre d'artefacts")
    _sceau_verifie(octets, registre.get("sha256"), f"{quoi}, registre d'artefacts")

    ou = f"{quoi}, registre d'artefacts"
    charge = _charge_objet(octets, ou)
    artefacts = charge.get("artifacts")
    if not isinstance(artefacts, list) or not artefacts:
        raise PromotedContentSetError(f"{quoi} : registre d'artefacts vide")

    contenus = _contenus_des_artefacts(artefacts, ou)
    # Le registre d'artefacts porte SON PROPRE compte. Ne confronter qu'à
    # celui de l'agrégat laissait passer un registre tronqué dont on aurait
    # rescellé l'agrégat : les deux comptes doivent tomber juste, faute de
    # quoi l'un des deux ment.
    if len(contenus) != _compte_declare(charge, "unique_artifacts", ou):
        raise PromotedContentSetError(
            f"{ou} : {len(contenus)} contenu(s) distinct(s) lus contre "
            f"{charge['expected_counts']['unique_artifacts']} qu'il déclare"
        )
    if len(contenus) != attendus:
        raise PromotedContentSetError(
            f"{quoi} : {len(contenus)} contenu(s) distinct(s) lus contre "
            f"{attendus} déclarés par l'agrégat"
        )

    _croiser_les_placements_v2(manifeste, chemin, registre, contenus, quoi, entree)
    return contenus


def _croiser_les_placements_v2(
    manifeste: dict,
    chemin: Path,
    registre: dict,
    contenus: set[str],
    quoi: str,
    entree: dict,
) -> None:
    """Les sujets scellés doivent placer EXACTEMENT ce que le registre porte.

    Le registre d'artefacts et l'agrégat peuvent être rescellés ensemble sur
    un ensemble amputé ; les manifestes de sujet, eux, continuent de placer
    l'artefact retiré et de déclarer l'ancien sceau du registre. Ne pas les
    lire laissait donc passer un ensemble plus petit que le périmètre servi.
    """
    sujets = manifeste.get("subjects")
    if not isinstance(sujets, list) or not sujets:
        raise PromotedContentSetError(
            f"{quoi} : aucun sujet — une release qui sert n'est pas vide"
        )
    _exiger_les_collections(sujets, entree, quoi)

    if len(sujets) != _compte_declare(manifeste, "subjects", quoi):
        raise PromotedContentSetError(
            f"{quoi} : {len(sujets)} sujet(s) portés contre "
            f"{manifeste['expected_counts']['subjects']} déclarés"
        )

    base = chemin.parent
    places: set[str] = set()
    total_placements = 0
    for sujet in sujets:
        if not isinstance(sujet, dict):
            raise PromotedContentSetError(
                f"{quoi} : une entrée de sujet est {type(sujet).__name__}, pas un objet"
            )
        nom = str(sujet.get("collection", sujet.get("path", "?")))
        ou = f"{quoi}, sujet {nom}"
        octets = _lire_gouverne(base / str(sujet["path"]), ou)
        _sceau_verifie(octets, sujet.get("sha256"), ou)
        charge = _charge_objet(octets, ou)

        # Le sujet déclare le sceau du registre d'artefacts qu'il suppose.
        propre = charge.get("artifact_registry")
        if not isinstance(propre, dict) or propre.get("sha256") != registre.get("sha256"):
            raise PromotedContentSetError(
                f"{ou} : suppose le registre d'artefacts "
                f"{str((propre or {}).get('sha256'))[:16]}… quand l'agrégat porte "
                f"{str(registre.get('sha256'))[:16]}…"
            )

        placements = charge.get("placements")
        if not isinstance(placements, list) or not placements:
            raise PromotedContentSetError(f"{ou} : aucun placement")
        if len(placements) != _compte_declare(charge, "placements", ou):
            raise PromotedContentSetError(
                f"{ou} : {len(placements)} placement(s) lus contre "
                f"{charge['expected_counts']['placements']} qu'il déclare"
            )
        total_placements += len(placements)
        references: set[str] = set()
        for placement in placements:
            if not isinstance(placement, dict) or "artifact_id" not in placement:
                raise PromotedContentSetError(
                    f"{ou} : un placement ne porte pas d'artifact_id"
                )
            references.add(str(placement["artifact_id"]))
        # Le sujet déclare aussi combien d'artefacts DISTINCTS il référence.
        # Sans ce compte, retirer un artefact et remplacer ses placements par
        # des doublons d'un autre préserve tous les totaux vérifiés — et
        # rétrécit pourtant l'ensemble promu.
        if len(references) != _compte_declare(charge, "unique_artifact_references", ou):
            raise PromotedContentSetError(
                f"{ou} : {len(references)} artefact(s) distinct(s) référencé(s) "
                f"contre {charge['expected_counts']['unique_artifact_references']} "
                "qu'il déclare"
            )
        places |= references

    # L'agrégat déclare le TOTAL de placements que la release sert. Ne vérifier
    # que les comptes locaux laissait ce total mentir sans conséquence — et il
    # est l'autorité que le producteur enregistre.
    if total_placements != _compte_declare(manifeste, "placements", quoi):
        raise PromotedContentSetError(
            f"{quoi} : {total_placements} placement(s) portés par les sujets "
            f"contre {manifeste['expected_counts']['placements']} déclarés par "
            "l'agrégat"
        )

    orphelins = sorted(places - contenus)
    if orphelins:
        raise PromotedContentSetError(
            f"{quoi} : {len(orphelins)} artefact(s) placé(s) par un sujet et "
            "absent(s) du registre d'artefacts : "
            + ", ".join(sha[:16] + "…" for sha in orphelins[:3])
        )


def _contenus_v1(
    manifeste: dict, chemin: Path, identifiant: str, entree: dict
) -> set[str]:
    """V1 : les artefacts sont énumérés sujet par sujet, avec répétitions."""
    quoi = f"release {identifiant}"
    sujets = manifeste.get("subjects")
    if not isinstance(sujets, list) or not sujets:
        raise PromotedContentSetError(
            f"{quoi} : aucun sujet — une release qui sert n'est pas vide"
        )
    attendues = _compte_declare(manifeste, "artifacts", quoi)
    _exiger_les_collections(sujets, entree, quoi)

    base = chemin.parent
    contenus: set[str] = set()
    occurrences = 0
    for sujet in sujets:
        if not isinstance(sujet, dict):
            raise PromotedContentSetError(
                f"{quoi} : une entrée de sujet est {type(sujet).__name__}, pas un objet"
            )
        nom = str(sujet.get("collection", sujet.get("path", "?")))
        ou = f"{quoi}, sujet {nom}"
        octets = _lire_gouverne(base / str(sujet["path"]), ou)
        _sceau_verifie(octets, sujet.get("sha256"), ou)
        charge = _charge_objet(octets, ou)
        artefacts = charge.get("artifacts")
        if not isinstance(artefacts, list) or not artefacts:
            raise PromotedContentSetError(f"{ou} : aucun artefact")
        # CHAQUE sujet tient son propre compte. Ne vérifier que le total de
        # l'agrégat laissait deux erreurs se compenser : un sujet tronqué et
        # un autre porteur d'un doublon rendent la même somme, et l'ensemble
        # dédupliqué rétrécit sans que rien ne le dise — la couverture CAS
        # passerait alors sur un périmètre incomplet.
        if len(artefacts) != _compte_declare(charge, "artifacts", ou):
            raise PromotedContentSetError(
                f"{ou} : {len(artefacts)} artefact(s) lus contre "
                f"{charge['expected_counts']['artifacts']} qu'il déclare"
            )
        contenus |= _contenus_des_artefacts(artefacts, ou)
        occurrences += len(artefacts)

    if occurrences != attendues:
        raise PromotedContentSetError(
            f"{quoi} : {occurrences} occurrence(s) d'artefact lues contre "
            f"{attendues} déclarées — lecture tronquée ou manifeste incohérent"
        )
    return contenus


def _exiger_les_collections(sujets: list, entree: dict, quoi: str) -> None:
    """Le registre déclare les collections que la release SERT.

    Sans cette confrontation, une release amputée d'un sujet — comptes et
    sceaux refaits — était acceptée, alors que le registre continue de
    déclarer la collection disparue active. L'ensemble promu rétrécissait
    donc sur un périmètre que l'autorité dit toujours servi.
    """
    declarees = entree.get("collections")
    # Obligatoire, comme `release_kind` : une déclaration facultative ne garde
    # rien, et disparaîtrait précisément sur le registre tronqué qu'elle doit
    # attraper.
    if not isinstance(declarees, list) or not declarees:
        raise PromotedContentSetError(
            f"{quoi} : le registre ne déclare aucune collection ({declarees!r}) "
            "— le périmètre servi ne serait alors confronté à rien"
        )
    portees = {str(s.get("collection")) for s in sujets if isinstance(s, dict)}
    manquantes = sorted(set(map(str, declarees)) - portees)
    surplus = sorted(portees - set(map(str, declarees)))
    if manquantes or surplus:
        raise PromotedContentSetError(
            f"{quoi} : le registre déclare {len(declarees)} collection(s) et la "
            f"release en porte {len(portees)}"
            + (f" — absentes : {', '.join(manquantes[:3])}" if manquantes else "")
            + (f" — en trop : {', '.join(surplus[:3])}" if surplus else "")
        )


def _contenus_des_artefacts(artefacts: list, quoi: str) -> set[str]:
    contenus: set[str] = set()
    for artefact in artefacts:
        if not isinstance(artefact, dict) or "content_sha256" not in artefact:
            raise PromotedContentSetError(
                f"{quoi} : une entrée d'artefact ne porte pas de content_sha256"
            )
        empreinte = artefact["content_sha256"]
        # `str()` d'une valeur quelconque deviendrait un identifiant promu, que
        # le store ne pourrait par construction jamais contenir : la couverture
        # échouerait plus tard, sur un défaut dont l'origine serait perdue.
        if not _est_sha256(empreinte):
            raise PromotedContentSetError(
                f"{quoi} : content_sha256 invalide ({empreinte!r})"
            )
        contenus.add(empreinte)
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
