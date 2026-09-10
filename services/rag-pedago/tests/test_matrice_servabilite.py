"""La matrice doit rendre compte de toute sa population, et refuser de mentir.

Ces épreuves ne vérifient pas des chiffres figés : elles vérifient les
propriétés qui rendent la matrice utilisable comme instrument de go-live.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "construire_matrice_servabilite.py"
)


def _charger_module(repo_root: pathlib.Path, monkeypatch):
    monkeypatch.setenv("NEXUS_REPO_ROOT", str(repo_root))
    spec = importlib.util.spec_from_file_location("matrice_servabilite", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _ecrire(root: pathlib.Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _relation(sha: str, **overrides):
    base = {
        "content_sha256": sha,
        "artifact_id": sha,
        "catalogue_match": True,
        "catalogue_statuses": ["actuel"],
        "disposition": "URL_EVIDENCE_FOUND",
        "serving_relevance": "INDEXABLE",
        "source_role": "INSTITUTIONAL_PUBLICATION",
    }
    base.update(overrides)
    return base


def _monter(root: pathlib.Path, relations, *, compatibles=(), incompatibles=(), pii=()):
    _ecrire(root, "docs/reports/handoff/url_provenance_reconciliation.json",
            {"relations": relations})
    apparies = [r for r in relations if r["catalogue_match"]]
    _ecrire(root, "docs/reports/handoff/program_partition_v4.json", {
        "incompatible_artifacts": list(incompatibles),
        "PROGRAM_COMPATIBILITY_PROVEN": len(compatibles),
        "PROGRAM_INCOMPATIBILITY_PROVEN": len(incompatibles),
        "PROGRAM_COMPATIBILITY_UNKNOWN": len(apparies) - len(compatibles) - len(incompatibles),
        "PROGRAM_POPULATION_TOTAL": len(apparies),
    })
    _ecrire(root, "docs/reports/handoff/artifact_program_bindings.json", {
        "bindings": [
            {"content_sha256": s, "compatibility_verdict": "COMPATIBLE"} for s in compatibles
        ]
    })
    _ecrire(root, "docs/reports/evidence-index/pii_review_index_v2_20260907.json",
            {"bundles": [{"content_sha256": s} for s in pii]})
    _ecrire(root, "docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json",
            {"NON_PDF_BY_DISPOSITION": {}})


def test_chaque_relation_recoit_exactement_un_verdict(tmp_path, monkeypatch):
    relations = [_relation(f"{i:064x}") for i in range(1, 6)]
    _monter(tmp_path, relations)
    matrice = _charger_module(tmp_path, monkeypatch).build()

    assert matrice["SERVABILITY_ROWS_TOTAL"] == len(relations)
    assert sum(matrice["by_verdict"].values()) == len(relations)
    assert matrice["SERVABILITY_UNACCOUNTED"] == 0


def test_une_relation_hors_catalogue_n_est_pas_un_programme_inconnu(tmp_path, monkeypatch):
    """C'est la confusion qui gonflait l'inconnu et cassait la réconciliation."""
    dedans, dehors = f"{1:064x}", f"{2:064x}"
    _monter(tmp_path, [
        _relation(dedans),
        _relation(dehors, catalogue_match=False, catalogue_statuses=[],
                  disposition="NO_URL_EVIDENCE"),
    ])
    matrice = _charger_module(tmp_path, monkeypatch).build()

    assert matrice["by_program"]["UNKNOWN"] == 1
    assert matrice["by_program"]["OUTSIDE_PROGRAM_POPULATION"] == 1
    assert matrice["PROGRAM_RECONCILIATION"]["RECONCILES"] is True


def test_une_incompatibilite_prouvee_prime_sur_toute_autre_dimension(tmp_path, monkeypatch):
    sha = f"{7:064x}"
    _monter(tmp_path, [_relation(sha)], incompatibles=[sha], pii=[sha])
    matrice = _charger_module(tmp_path, monkeypatch).build()

    assert matrice["rows"][0]["verdict"] == "REFUSED_PROGRAM_INCOMPATIBLE"


def test_une_pii_non_tranchee_bloque_meme_un_contenu_par_ailleurs_propre(tmp_path, monkeypatch):
    sha = f"{8:064x}"
    _monter(tmp_path, [_relation(sha)], compatibles=[sha], pii=[sha])
    matrice = _charger_module(tmp_path, monkeypatch).build()

    assert matrice["rows"][0]["verdict"] == "BLOCKED_PII_HUMAN_REVIEW"


def test_la_matrice_refuse_de_s_ecrire_si_elle_ne_se_reconcilie_pas(tmp_path, monkeypatch):
    sha = f"{9:064x}"
    _monter(tmp_path, [_relation(sha)])
    # On sabote la partition : elle annonce une population qui n'existe pas.
    chemin = tmp_path / "docs/reports/handoff/program_partition_v4.json"
    partition = json.loads(chemin.read_text(encoding="utf-8"))
    partition["PROGRAM_POPULATION_TOTAL"] = 999
    chemin.write_text(json.dumps(partition), encoding="utf-8")

    module = _charger_module(tmp_path, monkeypatch)
    assert module.build()["PROGRAM_RECONCILIATION"]["RECONCILES"] is False
    assert module.main() == 1
    assert not (tmp_path / "docs/reports/handoff/servability_matrix_v1.json").exists()


def test_une_entree_absente_est_un_refus_pas_une_reconstruction(tmp_path, monkeypatch):
    _monter(tmp_path, [_relation(f"{3:064x}")])
    (tmp_path / "docs/reports/handoff/program_partition_v4.json").unlink()

    module = _charger_module(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        module.build()


def test_la_matrice_n_applique_rien(tmp_path, monkeypatch):
    _monter(tmp_path, [_relation(f"{4:064x}")])
    assert _charger_module(tmp_path, monkeypatch).build()["applied"] is False
