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


def collect_promoted_content_set(top_level_release: Path) -> set[str]:
    """L'union des `content_sha256` de chaque sujet référencé par le manifeste racine."""
    manifest = json.loads(top_level_release.read_text(encoding="utf-8"))
    base = top_level_release.parent
    contents: set[str] = set()
    for subject in manifest["subjects"]:
        subject_manifest = json.loads((base / subject["path"]).read_text(encoding="utf-8"))
        for artifact in subject_manifest["artifacts"]:
            contents.add(str(artifact["content_sha256"]))
    return contents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    contents = collect_promoted_content_set(args.release)
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
