"""Vérifie qu'un store adressable par contenu rend EXACTEMENT le corpus attendu.

Le consommateur ne fait jamais confiance au NOM d'un objet : il lit les octets,
les hache, et confronte le résultat à l'ensemble attendu. Un objet posé sous le
bon localisateur mais porteur d'autres octets est un refus, pas un avertissement
— c'est précisément la substitution qu'un store adressable par contenu doit
rendre impossible à ignorer.

Aucun titre, aucune matière : ce script ne lit que des empreintes et des tailles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCHEMA = "NEXUS-CORPUS-CAS-MANIFEST-V1"


def content_set_digest(values: set[str]) -> str:
    """La MÊME dérivation que le producteur — `_final_set_digest`.

    Recopier une formule d'empreinte, c'est se donner deux vérités qui
    divergeront. Elle est reproduite ici littéralement et un test l'y confronte."""
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()


def _path_components(cas_root: Path, locator: str) -> list[Path]:
    """Chaque préfixe du localisateur, du store jusqu'à l'objet."""
    walked = cas_root
    parts = [walked]
    for element in Path(locator).parts:
        walked = walked / element
        parts.append(walked)
    return parts


def verify(
    cas_root: Path,
    expected_digest: str,
    expected_count: int,
    *,
    promoted: set[str] | None = None,
) -> tuple[int, list[str]]:
    manifest_path = cas_root / "manifest.json"
    if not manifest_path.is_file():
        return 1, ["le store ne porte aucun manifeste"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        return 1, [f"schéma de manifeste inattendu : {manifest.get('schema')!r}"]

    declared = {entry["content_sha256"]: entry for entry in manifest.get("entries", [])}
    problems: list[str] = []

    if len(declared) != expected_count:
        problems.append(
            f"le store déclare {len(declared)} contenus, {expected_count} attendus"
        )
    actual_digest = content_set_digest(set(declared))
    if actual_digest != expected_digest:
        problems.append(
            f"l'ensemble de contenus du store hache vers {actual_digest[:16]}… "
            f"alors que la lignée scellée attend {expected_digest[:16]}… — ce "
            "n'est pas le corpus que la revue humaine a couvert"
        )

    verified = 0
    #: Contenus dont les OCTETS ont été relus et vérifiés — pas
    #: seulement déclarés au manifeste.
    prouves: set[str] = set()
    absents: set[str] = set()
    discordants: set[str] = set()
    #: Octets corrects, taille déclarée fausse. Distinct d'une discordance
    #: d'empreinte : le manifeste ment sur une propriété différente.
    tailles: set[str] = set()
    invalides: set[str] = set()
    root = cas_root.resolve(strict=False)
    for content_sha256 in sorted(declared):
        entry = declared[content_sha256]
        # Un localisateur est une donnée du manifeste, donc une ENTRÉE : il peut
        # être absolu, remonter par `..`, ou pointer un lien symbolique sortant
        # du store. Sans cette borne, le vérificateur validerait un fichier
        # extérieur comme s'il l'avait récupéré — et prouverait la
        # reproductibilité d'un corpus qu'il n'a pas lu.
        locator = str(entry["locator"])
        blob = (cas_root / locator).resolve(strict=False)
        try:
            blob.relative_to(root)
        except ValueError:
            problems.append(
                f"{content_sha256[:16]}… : le localisateur {locator!r} sort du "
                "store — un objet hors du store n'est pas un objet récupéré"
            )
            invalides.add(content_sha256)
            continue
        # CHAQUE composant, pas seulement le dernier. Un lien de répertoire
        # interne — `alias -> objects` — laisse la résolution finale à
        # l'intérieur du store : la borne précédente le laisse donc passer,
        # et « un chemin gouverné ne redirige jamais » cesse d'être vrai.
        redirected = next(
            (
                str(part)
                for part in _path_components(cas_root, locator)
                if part.is_symlink()
            ),
            None,
        )
        if redirected is not None:
            problems.append(
                f"{content_sha256[:16]}… : {redirected!r} est un lien symbolique "
                "— un chemin gouverné ne redirige sur aucun de ses composants"
            )
            invalides.add(content_sha256)
            continue
        if not blob.is_file():
            problems.append(f"{content_sha256[:16]}… : objet absent du store")
            absents.add(content_sha256)
            continue
        payload = blob.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != content_sha256:
            problems.append(
                f"{content_sha256[:16]}… : les octets hachent vers {actual[:16]}… "
                "— le localisateur ne prouve rien, les octets si"
            )
            discordants.add(content_sha256)
            continue
        if int(entry["byte_size"]) != len(payload):
            problems.append(
                f"{content_sha256[:16]}… : taille déclarée {entry['byte_size']}, "
                f"lue {len(payload)}"
            )
            tailles.add(content_sha256)
            continue
        verified += 1
        prouves.add(content_sha256)

    info: list[str] = []
    if promoted is not None:
        if not promoted:
            # Un ensemble promu vide ne manque jamais de rien : il traverserait
            # le contrôle en publiant MISSING=0. Le refuser est la seule façon
            # que « 0 manquant » veuille dire « rien ne manque » plutôt que
            # « rien n'a été demandé ».
            problems.append(
                "l'ensemble des contenus promus est vide : la couverture serait "
                "vraie par vacuité"
            )
        else:
            # « Couvert » ne veut pas dire « déclaré au manifeste » : un
            # contenu dont le blob manque, dont les octets hachent ailleurs ou
            # dont le localisateur sort du store est DÉCLARÉ et pourtant
            # irrécupérable. Compter la déclaration ferait passer pour
            # reproductible un document qu'on ne sait pas relire.
            declares = set(declared)
            sans_declaration = sorted(promoted - declares)
            sans_blob = sorted(promoted & absents)
            discordance = sorted(promoted & (discordants | invalides))
            desaccord_taille = sorted(promoted & tailles)
            # L'agrégat bloquant : déclaration absente, blob absent, taille
            # fausse ou empreinte discordante. Un contenu promu n'est couvert
            # que si ses octets ont été RELUS et vérifiés.
            sans_couverture = sorted(promoted - prouves)
            surplus = sorted(declares - promoted)

            if sans_couverture:
                problems.append(
                    f"{len(sans_couverture)} contenu(s) promu(s) et servable(s) "
                    "aujourd'hui sans objet CAS vérifié : "
                    + ", ".join(sha[:16] + "…" for sha in sans_couverture[:5])
                )
            info.append(f"CURRENT_PROMOTED_CONTENTS={len(promoted)}")
            info.append(f"PROMOTED_CAS_DECLARATION_MISSING={len(sans_declaration)}")
            info.append(f"PROMOTED_CAS_BLOB_MISSING={len(sans_blob)}")
            info.append(f"PROMOTED_CAS_SIZE_MISMATCH={len(desaccord_taille)}")
            info.append(f"PROMOTED_CAS_HASH_MISMATCH={len(discordance)}")
            info.append(f"PROMOTED_CAS_COVERAGE_MISSING={len(sans_couverture)}")
            info.append(f"PROMOTED_CAS_COVERAGE_EXTRA={len(surplus)}")

    messages = problems or [f"{verified} objets vérifiés"]
    return (0 if not problems else 1), messages + info


def _charge_ensemble_promu(chemin: Path) -> set[str]:
    """Lit l'ensemble promu en le confrontant à ses PROPRES champs d'intégrité.

    Le fichier porte `count` et `content_set_sha256`. Les ignorer laissait un
    fichier tronqué mais non vide passer pour complet : la couverture était
    alors calculée contre moins de contenus qu'il n'y en a de promus, et
    « 0 manquant » ne voulait plus rien dire.
    """
    charge = json.loads(chemin.read_text(encoding="utf-8"))
    if not isinstance(charge, dict):
        raise ValueError(f"{chemin.name} : la racine n'est pas un objet")
    liste = charge.get("content_sha256")
    if not isinstance(liste, list) or not liste:
        raise ValueError(f"{chemin.name} : content_sha256 absent ou vide")
    promus = {str(valeur) for valeur in liste}
    if len(promus) != len(liste):
        raise ValueError(f"{chemin.name} : contient des doublons")
    if charge.get("count") != len(promus):
        raise ValueError(
            f"{chemin.name} : annonce {charge.get('count')!r} contenus et en "
            f"porte {len(promus)}"
        )
    attendu = charge.get("content_set_sha256")
    obtenu = content_set_digest(promus)
    if attendu != obtenu:
        raise ValueError(
            f"{chemin.name} : annonce l'empreinte {str(attendu)[:16]}… et ses "
            f"contenus hachent vers {obtenu[:16]}…"
        )
    return promus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cas-root", required=True, type=Path)
    parser.add_argument(
        "--expect-content-set-sha256",
        required=True,
        help="empreinte de l'ensemble de contenus que la lignée scellée produit",
    )
    parser.add_argument("--expect-count", required=True, type=int)
    parser.add_argument(
        "--promoted-content-set",
        type=Path,
        default=None,
        help=(
            "JSON produit par compute_promoted_content_set.py — refuse tout "
            "contenu promu et servable aujourd'hui qui serait absent du store"
        ),
    )
    args = parser.parse_args(argv)

    promoted = None
    if args.promoted_content_set is not None:
        try:
            promoted = _charge_ensemble_promu(args.promoted_content_set)
        except ValueError as exc:
            print(f"::error::PROMOTED_CONTENT_SET_INVALID: {exc}", file=sys.stderr)
            return 2

    code, messages = verify(
        args.cas_root,
        args.expect_content_set_sha256,
        args.expect_count,
        promoted=promoted,
    )
    for message in messages:
        print(("::error::" if code else "  ") + message, file=sys.stderr if code else sys.stdout)
    if code == 0:
        print(f"CORPUS_CAS_VERIFIED={args.expect_count}")
        print("CORPUS_CAS_MISSING=0")
        print("CORPUS_CAS_HASH_MISMATCH=0")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
