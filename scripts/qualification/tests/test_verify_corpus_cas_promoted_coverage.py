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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verify_corpus_cas import SCHEMA, content_set_digest, verify  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_EXTRA = "c" * 64


def _seed_store(cas_root: Path, content_shas: list[str]) -> set[str]:
    """Sème un store d'épreuve et rend les contenus qu'il déclare."""
    entries: list[dict[str, object]] = []
    declares: set[str] = set()
    for sha in content_shas:
        payload = sha.encode("ascii")
        real_sha = hashlib.sha256(payload).hexdigest()
        locator = f"objects/{real_sha}"
        (cas_root / "objects").mkdir(parents=True, exist_ok=True)
        (cas_root / locator).write_bytes(payload)
        entries.append(
            {"content_sha256": real_sha, "locator": locator, "byte_size": len(payload)}
        )
        declares.add(real_sha)
    (cas_root / "manifest.json").write_text(
        json.dumps({"schema": SCHEMA, "entries": entries}), encoding="utf-8"
    )
    return declares


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
        "PROMOTED_CAS_SIZE_MISMATCH=0",
        "PROMOTED_CAS_HASH_MISMATCH=0",
        "PROMOTED_CAS_COVERAGE_MISSING=0",
    ):
        assert any(compteur in m for m in messages), compteur


def test_une_taille_declaree_fausse_n_est_pas_une_discordance_d_empreinte(
    tmp_path: Path,
) -> None:
    """Deux propriétés différentes, deux compteurs différents.

    Les octets peuvent hacher juste et la taille déclarée être fausse : le
    manifeste ment alors sur autre chose que le contenu. Les confondre
    priverait l'exploitant de l'information qui dit QUOI réparer.
    """
    cas_root = tmp_path / "cas"
    declared = _seed_store(cas_root, [SHA_A, SHA_B])
    cible = sorted(declared)[0]
    manifeste = json.loads((cas_root / "manifest.json").read_text(encoding="utf-8"))
    for entree in manifeste["entries"]:
        if entree["content_sha256"] == cible:
            entree["byte_size"] = entree["byte_size"] + 1
    (cas_root / "manifest.json").write_text(json.dumps(manifeste), encoding="utf-8")

    code, messages = verify(
        cas_root, content_set_digest(declared), len(declared), promoted=declared
    )
    assert code == 1
    assert any("PROMOTED_CAS_SIZE_MISMATCH=1" in m for m in messages)
    assert any("PROMOTED_CAS_HASH_MISMATCH=0" in m for m in messages)
    assert any("PROMOTED_CAS_COVERAGE_MISSING=1" in m for m in messages)


# --- le fichier d'ensemble promu doit se prouver lui-même --------------


def _ecrire_ensemble(chemin: Path, contenus: set[str], **surcharges: object) -> Path:
    charge: dict[str, object] = {
        "content_sha256": sorted(contenus),
        "count": len(contenus),
        "content_set_sha256": content_set_digest(contenus),
    }
    charge.update(surcharges)
    chemin.write_text(json.dumps(charge), encoding="utf-8")
    return chemin


def test_un_ensemble_promu_tronque_mais_non_vide_est_refuse(tmp_path: Path) -> None:
    """Le fichier porte `count` et `content_set_sha256`. Les ignorer laissait
    un fichier tronqué passer pour complet : la couverture était alors
    calculée contre moins de contenus qu'il n'y a de promus, et « 0 manquant »
    ne voulait plus rien dire."""
    from verify_corpus_cas import _charge_ensemble_promu

    complet = {SHA_A, SHA_B}
    fichier = _ecrire_ensemble(tmp_path / "p.json", complet)
    charge = json.loads(fichier.read_text(encoding="utf-8"))
    charge["content_sha256"] = charge["content_sha256"][:1]  # tronqué
    fichier.write_text(json.dumps(charge), encoding="utf-8")

    with pytest.raises(ValueError, match="annonce 2 contenus et en porte 1"):
        _charge_ensemble_promu(fichier)


def test_un_ensemble_promu_dont_l_empreinte_ne_correspond_pas_est_refuse(
    tmp_path: Path,
) -> None:
    from verify_corpus_cas import _charge_ensemble_promu

    fichier = _ecrire_ensemble(
        tmp_path / "p.json", {SHA_A, SHA_B}, content_set_sha256="0" * 64
    )
    with pytest.raises(ValueError, match="annonce l'empreinte"):
        _charge_ensemble_promu(fichier)


def test_un_ensemble_promu_vide_est_refuse_des_le_chargement(tmp_path: Path) -> None:
    from verify_corpus_cas import _charge_ensemble_promu

    fichier = tmp_path / "p.json"
    fichier.write_text(
        json.dumps({"content_sha256": [], "count": 0, "content_set_sha256": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="absent ou vide"):
        _charge_ensemble_promu(fichier)


def test_un_ensemble_promu_conforme_est_accepte(tmp_path: Path) -> None:
    from verify_corpus_cas import _charge_ensemble_promu

    complet = {SHA_A, SHA_B}
    assert _charge_ensemble_promu(_ecrire_ensemble(tmp_path / "p.json", complet)) == complet
