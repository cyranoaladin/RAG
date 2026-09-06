"""L'ensemble des contenus promus est celui que le corpus SERT aujourd'hui.

Ce script ne lit que ce que la lignée scellée publie — le manifeste racine et
ses sujets — jamais le store privé. Il doit dédoublonner un contenu partagé
par plusieurs sujets (PR #146), pas le compter deux fois.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from compute_promoted_content_set import (  # noqa: E402
    PromotedContentSetError,
    collect_promoted_content_set,
    main,
)
from verify_corpus_cas import content_set_digest  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_SHARED = "c" * 64


def _sceau(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _seed_release(tmp_path: Path, *, occurrences: int | None = 4) -> Path:
    """Une lignée d'épreuve COMPLÈTE : sujets scellés et occurrences déclarées.

    Le manifeste racine scelle chaque sujet par son empreinte et annonce le
    nombre d'occurrences. Une fixture qui omettrait l'un ou l'autre ne
    représenterait pas la lignée réelle, et les épreuves ne prouveraient rien
    des gardes qui les exigent.
    """
    _write(
        tmp_path / "subjects" / "sujet-a.release.json",
        {"artifacts": [{"content_sha256": SHA_A}, {"content_sha256": SHA_SHARED}]},
    )
    _write(
        tmp_path / "subjects" / "sujet-b.release.json",
        {"artifacts": [{"content_sha256": SHA_B}, {"content_sha256": SHA_SHARED}]},
    )
    top = tmp_path / "production-profile-gate.release.json"
    _write(
        top,
        {
            "expected_counts": {"artifacts": occurrences},
            "subjects": [
                {
                    "collection": "sujet-a",
                    "path": "subjects/sujet-a.release.json",
                    "sha256": _sceau(tmp_path / "subjects" / "sujet-a.release.json"),
                },
                {
                    "collection": "sujet-b",
                    "path": "subjects/sujet-b.release.json",
                    "sha256": _sceau(tmp_path / "subjects" / "sujet-b.release.json"),
                },
            ],
        },
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


def test_a_subject_manifest_that_drifted_from_its_seal_is_refused(
    tmp_path: Path,
) -> None:
    """Le manifeste racine SCELLE chaque sujet ; lire sans confronter le sceau
    laisserait un sujet réécrit changer l'ensemble promu sans que rien ne le
    dise."""
    top = _seed_release(tmp_path)
    _write(
        tmp_path / "subjects" / "sujet-a.release.json",
        {"artifacts": [{"content_sha256": SHA_A}]},
    )
    with pytest.raises(PromotedContentSetError) as refus:
        collect_promoted_content_set(top)
    assert "le manifeste racine déclare" in str(refus.value)


def test_a_truncated_read_is_visible_through_the_declared_occurrences(
    tmp_path: Path,
) -> None:
    """Un ensemble DÉDUPLIQUÉ plus petit est indiscernable d'une lecture
    tronquée : seule la comparaison des OCCURRENCES à ce que la lignée
    déclare rend la troncature visible."""
    top = _seed_release(tmp_path, occurrences=9)
    with pytest.raises(PromotedContentSetError) as refus:
        collect_promoted_content_set(top)
    assert "occurrence(s) d'artefact lues contre 9" in str(refus.value)


def test_a_release_without_any_subject_is_refused(tmp_path: Path) -> None:
    """Un ensemble promu vide ne manque jamais de rien."""
    top = tmp_path / "production-profile-gate.release.json"
    _write(top, {"subjects": [], "expected_counts": {"artifacts": 0}})
    with pytest.raises(PromotedContentSetError) as refus:
        collect_promoted_content_set(top)
    assert "aucun sujet" in str(refus.value)
