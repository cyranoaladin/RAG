"""L'ensemble des contenus promus est celui que le corpus SERT aujourd'hui.

Ce script ne lit que ce que la lignée scellée publie — le manifeste racine et
ses sujets — jamais le store privé. Il doit dédoublonner un contenu partagé
par plusieurs sujets (PR #146), pas le compter deux fois.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compute_promoted_content_set import collect_promoted_content_set, main  # noqa: E402
from verify_corpus_cas import content_set_digest  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_SHARED = "c" * 64


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _seed_release(tmp_path: Path) -> Path:
    top = tmp_path / "production-profile-gate.release.json"
    _write(
        top,
        {
            "subjects": [
                {"collection": "sujet-a", "path": "subjects/sujet-a.release.json"},
                {"collection": "sujet-b", "path": "subjects/sujet-b.release.json"},
            ]
        },
    )
    _write(
        tmp_path / "subjects" / "sujet-a.release.json",
        {"artifacts": [{"content_sha256": SHA_A}, {"content_sha256": SHA_SHARED}]},
    )
    _write(
        tmp_path / "subjects" / "sujet-b.release.json",
        {"artifacts": [{"content_sha256": SHA_B}, {"content_sha256": SHA_SHARED}]},
    )
    return top


def test_collects_content_across_every_subject(tmp_path: Path) -> None:
    top = _seed_release(tmp_path)
    assert collect_promoted_content_set(top) == {SHA_A, SHA_B, SHA_SHARED}


def test_a_content_shared_by_two_subjects_is_not_double_counted(tmp_path: Path) -> None:
    top = _seed_release(tmp_path)
    assert len(collect_promoted_content_set(top)) == 3


def test_main_writes_the_set_and_the_same_digest_formula_as_the_cas_verifier(
    tmp_path: Path,
) -> None:
    top = _seed_release(tmp_path)
    output = tmp_path / "promoted.json"
    code = main(["--release", str(top), "--output", str(output)])
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert sorted(payload["content_sha256"]) == sorted([SHA_A, SHA_B, SHA_SHARED])
    assert payload["count"] == 3
    assert payload["content_set_sha256"] == content_set_digest({SHA_A, SHA_B, SHA_SHARED})
