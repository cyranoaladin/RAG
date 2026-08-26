"""Le registre de release et le catalogue doivent rester réconciliables (P0-L1A).

Ces tests portent sur l'auditeur, pas sur le verdict du jour : ils doivent
rester verts avant comme après la correction de la release. Le garde-fou qui
exigera `RELEASE_CATALOGUE_COHERENCE=PASS` sur les données réelles arrive avec
cette correction, pas avant.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "services/rag-pedago/scripts/release_catalogue_coherence_audit.py"


def _module() -> Any:
    specification = importlib.util.spec_from_file_location(
        "release_catalogue_coherence_audit", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    # `dataclasses` résout les annotations différées via `sys.modules` : sans
    # cet enregistrement, la classe du module chargé dynamiquement échoue.
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audited() -> tuple[Any, list[Any], dict[str, Any]]:
    module = _module()
    rows, summary = module.audit()
    return module, rows, summary


def test_every_release_subject_is_audited_exactly_once(
    audited: tuple[Any, list[Any], dict[str, Any]],
) -> None:
    _module_, rows, summary = audited
    assert len(rows) == summary["manifest_subjects"]
    assert len({row.collection for row in rows}) == len(rows)


def test_declared_totals_are_the_sum_of_the_audited_subjects(
    audited: tuple[Any, list[Any], dict[str, Any]],
) -> None:
    """Le manifest annonce des totaux ; ils doivent être ceux des sujets.

    Le moteur exige exactement ces totaux en base avant d'accepter du trafic :
    un écart entre l'annonce et la somme rendrait la porte de démarrage
    insatisfaisable quoi qu'on publie.
    """
    _module_, rows, summary = audited
    assert summary["declared_totals"] == {
        "artifacts": sum(row.expected_artifacts for row in rows),
        "placements": sum(row.expected_placements for row in rows),
        "chunks": sum(row.expected_chunks for row in rows),
    }
    assert summary["declared_totals"] == summary["manifest_expected_counts"]


def test_coherent_and_incoherent_partition_the_release(
    audited: tuple[Any, list[Any], dict[str, Any]],
) -> None:
    module, rows, summary = audited
    coherent = [row for row in rows if row.verdict == module.VERDICT_COHERENT]
    assert len(coherent) == summary["coherent_collections"]
    assert len(rows) - len(coherent) == summary["incoherent_collections"]

    for key in ("artifacts", "placements", "chunks"):
        assert (
            summary["coherent_totals"][key] + summary["unservable_work_if_kept"][key]
            == summary["declared_totals"][key]
        )


def test_ingestibility_is_exactly_the_coherent_verdict(
    audited: tuple[Any, list[Any], dict[str, Any]],
) -> None:
    """`instanciee: false` rend la collection définitivement non servable.

    `resolve_collection_v2` la refuse fail-closed ; aucune publication ne peut
    la rendre interrogeable tant que le catalogue ne l'instancie pas. Le drapeau
    d'ingestibilité ne doit donc jamais diverger du verdict.
    """
    module, rows, _summary = audited
    for row in rows:
        assert row.ingestible_by_current_policy is (
            row.verdict == module.VERDICT_COHERENT
        ), row.collection
        if row.ingestible_by_current_policy:
            assert row.instanciee is True
            assert row.in_catalogue is True
            assert row.ingestion_profile is not None


def test_a_release_naming_a_non_instanciated_collection_is_reported_p0(
    audited: tuple[Any, list[Any], dict[str, Any]],
) -> None:
    module, rows, _summary = audited
    for row in rows:
        if row.in_catalogue and row.instanciee is not True:
            assert row.verdict == module.VERDICT_INCOHERENT, row.collection
            assert row.verdict.startswith("P0_")


def test_check_mode_fails_exactly_when_a_collection_is_incoherent(
    monkeypatch: pytest.MonkeyPatch,
    audited: tuple[Any, list[Any], dict[str, Any]],
) -> None:
    module, rows, summary = audited
    coherent = [row for row in rows if row.verdict == module.VERDICT_COHERENT]
    assert coherent, "the fixture needs at least one coherent collection"

    healthy_summary = dict(summary)
    healthy_summary["incoherent_collections"] = 0
    monkeypatch.setattr(module, "audit", lambda: (coherent, healthy_summary))
    assert module.main(["--check"]) == 0

    broken = replace(coherent[0], instanciee=False, verdict=module.VERDICT_INCOHERENT)
    broken_summary = dict(summary)
    broken_summary["incoherent_collections"] = 1
    monkeypatch.setattr(module, "audit", lambda: ([broken], broken_summary))
    assert module.main(["--check"]) == 1
    # Sans --check l'auditeur reste un rapport : il ne casse aucune commande.
    assert module.main([]) == 0


def test_the_machine_readable_evidence_is_versioned_and_matches_the_audit(
    audited: tuple[Any, list[Any], dict[str, Any]],
) -> None:
    """La preuve committée doit être régénérable, jamais rédigée à la main."""
    import json

    evidence_path = (
        ROOT / "docs/reports/evidence/release_catalogue_coherence_20260826.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    _module_, rows, summary = audited

    assert evidence["protocol_version"] == "NEXUS-RELEASE-CATALOGUE-COHERENCE-V1"
    assert evidence["summary"] == summary
    assert [entry["collection"] for entry in evidence["collections"]] == [
        row.collection for row in rows
    ]


# ═══════════════════════════════════════════════════════════════════════
# Algèbre des ensembles et matrice de périmètre GO-LIVE
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def sets(audited: tuple[Any, list[Any], dict[str, Any]]) -> dict[str, Any]:
    module, _rows, _summary = audited
    return module.collection_sets()


@pytest.fixture(scope="module")
def matrix(audited: tuple[Any, list[Any], dict[str, Any]]) -> list[dict[str, Any]]:
    module, _rows, _summary = audited
    return module.go_live_scope_matrix()


def test_quarantine_is_never_counted_as_a_servable_instanciated_collection(
    sets: dict[str, Any],
) -> None:
    """`rag_nexus_quarantine` est instanciée mais non retrievable par design.

    La compter comme servable fausserait chaque différence : c'est exactement
    l'erreur qui avait donné « 13 autorités pour 11 collections » dans un
    rapport antérieur.
    """
    assert set(sets["QUARANTINE"]) <= set(sets["INSTANCIEE_RAW"])
    assert not set(sets["QUARANTINE"]) & set(sets["INSTANCIEE"])
    assert len(sets["INSTANCIEE"]) == len(sets["INSTANCIEE_RAW"]) - len(
        sets["QUARANTINE"]
    )


def test_the_three_differences_partition_the_two_sets_exactly(
    sets: dict[str, Any],
) -> None:
    release = set(sets["CURRENT_RELEASE"])
    instanciee = set(sets["INSTANCIEE"])

    intersection = set(sets["CURRENT_RELEASE_INTERSECT_INSTANCIEE"])
    only_release = set(sets["CURRENT_RELEASE_MINUS_INSTANCIEE"])
    only_instanciee = set(sets["INSTANCIEE_MINUS_CURRENT_RELEASE"])

    assert intersection | only_release == release
    assert intersection | only_instanciee == instanciee
    assert not intersection & only_release
    assert not intersection & only_instanciee
    assert len(release) == len(intersection) + len(only_release)
    assert len(instanciee) == len(intersection) + len(only_instanciee)


def test_the_first_release_candidate_is_exactly_the_intersection(
    sets: dict[str, Any],
) -> None:
    assert sets["FIRST_RELEASE_CANDIDATE"] == sets[
        "CURRENT_RELEASE_INTERSECT_INSTANCIEE"
    ]


def test_no_collection_is_activation_authorized_without_being_instanciated(
    sets: dict[str, Any],
) -> None:
    """Une ADR qui active une collection non instanciée serait restée sans effet."""
    assert sets["AUTHORIZED_NOT_INSTANCIEE"] == []


def test_instanciated_collections_without_a_named_authority_stay_visible(
    sets: dict[str, Any],
) -> None:
    """Instancier sans ADR reste possible, mais jamais implicite.

    Les deux collections NSI précèdent le régime ADR-0039/ADR-0041. L'audit
    doit continuer de les nommer plutôt que de les fondre dans un total.
    """
    for collection in sets["INSTANCIEE_WITHOUT_NAMED_AUTHORITY"]:
        assert collection in sets["INSTANCIEE"]
        assert collection not in sets["ACTIVATION_AUTHORIZED"]


def test_the_scope_matrix_classifies_every_catalogue_collection_exactly_once(
    sets: dict[str, Any], matrix: list[dict[str, Any]]
) -> None:
    assert len(matrix) == len(sets["CATALOGUE"])
    assert [row["collection"] for row in matrix] == sets["CATALOGUE"]
    assert all(row["exists_in_catalogue"] for row in matrix)


def test_every_scope_row_names_the_source_that_governs_it(
    matrix: list[dict[str, Any]],
) -> None:
    for row in matrix:
        assert row["governing_source"], row["collection"]
        assert len(row["reason"]) > 40, row["collection"]


def test_final_go_live_requirement_comes_from_the_roadmap_pilot_only(
    matrix: list[dict[str, Any]],
) -> None:
    """Le référentiel scolaire décrit le système éducatif, pas le produit.

    L'autorité de périmètre est la décision de cadrage du ROADMAP — vertical
    pilote Terminale générale, spécialités Maths + NSI — et rien d'autre.
    """
    required = [row for row in matrix if row["final_go_live_required"]]
    assert {row["collection"] for row in required} == {
        "rag_nexus_maths_terminale_gen_specialite",
        "rag_nexus_nsi_terminale_specialite",
    }
    for row in required:
        assert row["product_scope"] == "pilot_vertical"
        assert row["governing_source"] == "roadmap_pilot"


def test_the_pilot_vertical_is_covered_by_the_first_release_candidate(
    sets: dict[str, Any], matrix: list[dict[str, Any]]
) -> None:
    """Réduire la release aux collections instanciées ne rétrécit pas le produit.

    Si le pilote n'était pas entièrement couvert, le retrait des collections non
    instanciées serait une réduction silencieuse de périmètre, pas une
    correction de cohérence.
    """
    pilot = {row["collection"] for row in matrix if row["product_scope"] == "pilot_vertical"}
    assert pilot <= set(sets["FIRST_RELEASE_CANDIDATE"]), pilot - set(
        sets["FIRST_RELEASE_CANDIDATE"]
    )


def test_first_release_required_never_exceeds_the_release_itself(
    sets: dict[str, Any], matrix: list[dict[str, Any]]
) -> None:
    required = {row["collection"] for row in matrix if row["first_release_required"]}
    assert required == set(sets["FIRST_RELEASE_CANDIDATE"])


def test_the_report_verdict_does_not_depend_on_the_check_flag(
    monkeypatch: pytest.MonkeyPatch,
    audited: tuple[Any, list[Any], dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un rapport affichant PASS sous une table d'incohérences serait pire que muet."""
    module, rows, summary = audited
    broken = dict(summary)
    broken["incoherent_collections"] = 3
    monkeypatch.setattr(module, "audit", lambda: (rows, broken))

    assert module.main([]) == 0
    captured = capsys.readouterr()
    assert "RELEASE_CATALOGUE_COHERENCE=FAIL" in captured.err
    assert "RELEASE_CATALOGUE_COHERENCE=PASS" not in captured.out
