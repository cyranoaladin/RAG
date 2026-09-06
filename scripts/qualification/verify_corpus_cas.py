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

    info: list[str] = []
    if promoted is not None and not promoted:
        # Un ensemble promu vide ne manque jamais de rien : il traverserait le
        # contrôle en publiant MISSING=0. Le refuser est la seule façon que
        # « 0 manquant » veuille dire « rien ne manque » plutôt que « rien n'a
        # été demandé ».
        problems.append(
            "l'ensemble des contenus promus est vide : la couverture serait "
            "vraie par vacuité"
        )
    elif promoted is not None:
        # Le store peut être plus grand que la lignée COURANTE — un contenu
        # candidat retiré ou superseded n'est pas un défaut. L'inverse l'est :
        # un contenu que la lignée promeut et sert aujourd'hui, absent du
        # store, est un trou de reproductibilité pour un document servable.
        manquants = sorted(promoted - set(declared))
        surplus = sorted(set(declared) - promoted)
        if manquants:
            problems.append(
                f"{len(manquants)} contenu(s) promu(s) et servable(s) "
                "aujourd'hui, absent(s) du store : "
                + ", ".join(sha[:16] + "…" for sha in manquants[:5])
            )
        info.append(f"PROMOTED_CAS_COVERAGE_MISSING={len(manquants)}")
        info.append(f"PROMOTED_CAS_COVERAGE_EXTRA={len(surplus)}")

    verified = 0
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
            continue
        if not blob.is_file():
            problems.append(f"{content_sha256[:16]}… : objet absent du store")
            continue
        payload = blob.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != content_sha256:
            problems.append(
                f"{content_sha256[:16]}… : les octets hachent vers {actual[:16]}… "
                "— le localisateur ne prouve rien, les octets si"
            )
            continue
        if int(entry["byte_size"]) != len(payload):
            problems.append(
                f"{content_sha256[:16]}… : taille déclarée {entry['byte_size']}, "
                f"lue {len(payload)}"
            )
            continue
        verified += 1
    messages = problems or [f"{verified} objets vérifiés"]
    return (0 if not problems else 1), messages + info


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
        promoted = set(
            json.loads(args.promoted_content_set.read_text(encoding="utf-8"))[
                "content_sha256"
            ]
        )

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
