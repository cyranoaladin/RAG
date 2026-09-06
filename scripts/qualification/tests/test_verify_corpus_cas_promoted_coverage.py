"""Le store CAS peut être plus grand que le corpus promu, jamais plus petit.

`content_set_sha256` prouve que le store est celui d'une lignée FIGÉE — pas
qu'il couvre encore ce que la lignée COURANTE sert. Un contenu promu absent
du store privé est un trou de reproductibilité pour un document servable
aujourd'hui : refus. Un contenu du store qui n'est plus promu (candidat
retiré, contenu superseded) n'en est pas un : accepté et compté.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verify_corpus_cas import SCHEMA, content_set_digest, verify  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_EXTRA = "c" * 64


def _seed_store(cas_root: Path, content_shas: list[str]) -> None:
    entries = []
    for sha in content_shas:
        payload = sha.encode("ascii")
        real_sha = hashlib.sha256(payload).hexdigest()
        locator = f"objects/{real_sha}"
        (cas_root / "objects").mkdir(parents=True, exist_ok=True)
        (cas_root / locator).write_bytes(payload)
        entries.append(
            {"content_sha256": real_sha, "locator": locator, "byte_size": len(payload)}
        )
    (cas_root / "manifest.json").write_text(
        json.dumps({"schema": SCHEMA, "entries": entries}), encoding="utf-8"
    )
    return {e["content_sha256"] for e in entries}


def test_a_promoted_content_missing_from_the_store_is_refused(tmp_path: Path) -> None:
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A])
    digest = content_set_digest(declared)
    code, messages = verify(
        cas_root, digest, len(declared), promoted=declared | {SHA_B}
    )
    assert code == 1
    assert any("promu" in m and "sans objet CAS vérifié" in m for m in messages)
    assert any("PROMOTED_CAS_DECLARATION_MISSING=1" in m for m in messages)
    assert any("PROMOTED_CAS_COVERAGE_MISSING=1" in m for m in messages)


def test_a_store_content_that_is_no_longer_promoted_is_accepted_and_reported(
    tmp_path: Path,
) -> None:
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A, SHA_EXTRA])
    digest = content_set_digest(declared)
    only_one = {sorted(declared)[0]}
    code, messages = verify(cas_root, digest, len(declared), promoted=only_one)
    assert code == 0
    assert any("PROMOTED_CAS_COVERAGE_MISSING=0" in m for m in messages)
    assert any("PROMOTED_CAS_COVERAGE_EXTRA=1" in m for m in messages)


def test_an_exact_match_reports_zero_missing_and_zero_extra(tmp_path: Path) -> None:
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A, SHA_B])
    digest = content_set_digest(declared)
    code, messages = verify(cas_root, digest, len(declared), promoted=declared)
    assert code == 0
    assert any("PROMOTED_CAS_COVERAGE_MISSING=0" in m for m in messages)
    assert any("PROMOTED_CAS_COVERAGE_EXTRA=0" in m for m in messages)


def test_without_promoted_argument_behaviour_is_unchanged(tmp_path: Path) -> None:
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A])
    digest = content_set_digest(declared)
    code, messages = verify(cas_root, digest, len(declared))
    assert code == 0
    assert not any("PROMOTED_CAS_COVERAGE" in m for m in messages)


def test_an_empty_promoted_set_is_refused_instead_of_passing_vacuously(
    tmp_path: Path,
) -> None:
    """Le trou du contrôle de couverture lui-même.

    Un ensemble promu vide ne manque jamais de rien : il traversait le
    contrôle en publiant `PROMOTED_CAS_COVERAGE_MISSING=0`. C'est la manière
    exacte dont un gate devient vert en PERDANT ses données — moins on en
    sait, plus le compte est bon. Le refuser est la seule façon que « 0
    manquant » veuille dire « rien ne manque » plutôt que « rien n'a été
    demandé ».
    """
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A])
    code, messages = verify(
        cas_root, content_set_digest(declared), len(declared), promoted=set()
    )
    assert code == 1
    assert any("vraie par vacuité" in message for message in messages)


# --- « couvert » ne veut pas dire « déclaré » --------------------------


def test_un_contenu_declare_dont_le_blob_manque_n_est_pas_couvert(
    tmp_path: Path,
) -> None:
    """Le trou que comptait l'ancienne sémantique.

    Un contenu peut figurer au manifeste du store et n'y avoir aucun octet
    lisible. Compter la DÉCLARATION faisait alors passer pour reproductible
    un document qu'on ne sait pas relire — exactement ce que C1 doit exclure.
    """
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A, SHA_B])
    manquant = sorted(declared)[0]
    entry = json.loads((cas_root / "manifest.json").read_text(encoding="utf-8"))
    locator = next(e["locator"] for e in entry["entries"] if e["content_sha256"] == manquant)
    (cas_root / locator).unlink()

    code, messages = verify(
        cas_root, content_set_digest(declared), len(declared), promoted=declared
    )
    assert code == 1
    assert any("PROMOTED_CAS_DECLARATION_MISSING=0" in m for m in messages)
    assert any("PROMOTED_CAS_BLOB_MISSING=1" in m for m in messages)
    assert any("PROMOTED_CAS_COVERAGE_MISSING=1" in m for m in messages)


def test_un_contenu_declare_dont_les_octets_hachent_ailleurs_n_est_pas_couvert(
    tmp_path: Path,
) -> None:
    """Le localisateur ne prouve rien, les octets si."""
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A, SHA_B])
    cible = sorted(declared)[0]
    entry = json.loads((cas_root / "manifest.json").read_text(encoding="utf-8"))
    locator = next(e["locator"] for e in entry["entries"] if e["content_sha256"] == cible)
    (cas_root / locator).write_bytes(b"d'autres octets")

    code, messages = verify(
        cas_root, content_set_digest(declared), len(declared), promoted=declared
    )
    assert code == 1
    assert any("PROMOTED_CAS_HASH_MISMATCH=1" in m for m in messages)
    assert any("PROMOTED_CAS_COVERAGE_MISSING=1" in m for m in messages)


def test_une_couverture_complete_rend_les_quatre_compteurs_a_zero(
    tmp_path: Path,
) -> None:
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A, SHA_B])
    code, messages = verify(
        cas_root, content_set_digest(declared), len(declared), promoted=declared
    )
    assert code == 0
    for compteur in (
        "CURRENT_PROMOTED_CONTENTS=2",
        "PROMOTED_CAS_DECLARATION_MISSING=0",
        "PROMOTED_CAS_BLOB_MISSING=0",
        "PROMOTED_CAS_HASH_MISMATCH=0",
        "PROMOTED_CAS_COVERAGE_MISSING=0",
    ):
        assert any(compteur in m for m in messages), compteur
