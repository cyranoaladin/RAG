"""Calcule l'ensemble des contenus que la lignée promue sert AUJOURD'HUI.

`pii_review_index_20260903.json` scelle l'ensemble d'une revue humaine passée
— il ne dit rien de ce que la lignée COURANTE promeut. Ce script ne lit que
des données publiques du dépôt (le manifeste racine et ses sujets) : jamais
le store privé. Un contenu partagé par plusieurs sujets (PR #146) est compté
une fois, pas une fois par sujet qui le référence.

Usage :
    python scripts/qualification/compute_promoted_content_set.py \\
        --output /tmp/promoted-content-set.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_corpus_cas import content_set_digest  # noqa: E402

DEFAULT_RELEASE = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "profile_gate"
    / "production-profile-gate.release.json"
)


class PromotedContentSetError(RuntimeError):
    """L'ensemble promu n'est pas celui que le manifeste déclare — refus."""


def collect_promoted_content_set(top_level_release: Path) -> set[str]:
    """L'union des `content_sha256` de chaque sujet référencé par le manifeste racine.

    Trois vérifications, et aucune n'est décorative. Un ensemble promu que l'on
    calcule sans les faire pourrait être VIDE ou TRONQUÉ sans que rien ne le
    dise — et un ensemble vide traverse victorieusement le contrôle de
    couverture, puisqu'il ne manque alors jamais rien. C'est exactement la
    manière dont un gate devient vert en perdant ses données.

    1. chaque manifeste de sujet est confronté à l'empreinte que le manifeste
       RACINE déclare pour lui : un sujet périmé ou réécrit change l'ensemble
       promu sans changer le fichier qu'on lit ;
    2. le nombre d'OCCURRENCES est confronté à `expected_counts.artifacts` :
       une lecture tronquée est visible, alors qu'un ensemble dédupliqué plus
       petit ne l'est pas ;
    3. l'ensemble ne peut pas être vide.
    """
    manifest = json.loads(top_level_release.read_text(encoding="utf-8"))
    base = top_level_release.parent

    subjects = manifest.get("subjects") or []
    if not subjects:
        raise PromotedContentSetError(
            "le manifeste racine ne référence aucun sujet : l'ensemble promu "
            "serait vide, et un ensemble vide ne manque jamais de rien"
        )

    contents: set[str] = set()
    occurrences = 0
    for subject in subjects:
        chemin = base / subject["path"]
        octets = chemin.read_bytes()
        declaree = str(subject.get("sha256") or "")
        mesuree = hashlib.sha256(octets).hexdigest()
        if declaree != mesuree:
            raise PromotedContentSetError(
                f"{subject['path']} : le manifeste racine déclare "
                f"{declaree[:16]}… et le fichier vaut {mesuree[:16]}… — "
                "l'ensemble promu ne serait pas celui que la lignée scelle"
            )
        subject_manifest = json.loads(octets.decode("utf-8"))
        for artifact in subject_manifest["artifacts"]:
            contents.add(str(artifact["content_sha256"]))
            occurrences += 1

    attendues = manifest.get("expected_counts", {}).get("artifacts")
    if attendues is not None and occurrences != int(attendues):
        raise PromotedContentSetError(
            f"{occurrences} occurrence(s) d'artefact lues contre "
            f"{attendues} déclarées par la lignée — lecture tronquée ou "
            "manifeste incohérent"
        )

    if not contents:
        raise PromotedContentSetError(
            "aucun contenu promu : le contrôle de couverture serait vrai par "
            "vacuité"
        )
    return contents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        contents = collect_promoted_content_set(args.release)
    except (PromotedContentSetError, KeyError, OSError) as exc:
        # Une trace Python en CI dit où le code s'est arrêté, pas ce qui est
        # faux dans la lignée. Le gate doit nommer le défaut.
        print(f"::error::PROMOTED_CONTENT_SET_INVALID: {exc}", file=sys.stderr)
        return 2
    payload = {
        "content_sha256": sorted(contents),
        "count": len(contents),
        "content_set_sha256": content_set_digest(contents),
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
