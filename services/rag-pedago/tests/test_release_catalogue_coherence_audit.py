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
