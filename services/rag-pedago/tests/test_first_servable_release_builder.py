"""Le producteur de la FIRST_SERVABLE_RELEASE énumère, il ne filtre pas.

Un producteur qui construirait la release par `if instanciee: include` ferait
disparaître silencieusement tout membre dont le drapeau bascule, et apparaître
silencieusement toute collection nouvellement instanciée. Ces tests portent sur
le refus, pas sur le contenu du jour.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "services/rag-pedago/scripts/build_first_servable_release.py"


def _module() -> Any:
    specification = importlib.util.spec_from_file_location(
        "build_first_servable_release", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder() -> Any:
    return _module()


# ─────────────────────────────────────────────────────────────────────────
# Les trois invariants qui exigent la release CORRIGÉE arrivent avec la
# régénération, pas avant : `release ⊆ instanciee`, `membership == release`
# et l'idempotence de `--check`. Les poser ici rendrait la suite rouge sur
# `main` pour documenter un travail non fait — ce que le projet interdit.
# Ils sont nommés dans le rapport de lot comme critère de fermeture.
# ─────────────────────────────────────────────────────────────────────────


def test_the_expected_counts_are_the_sum_of_the_member_subjects(builder: Any) -> None:
    _registry, manifest = builder.build()
    totals = {"artifacts": 0, "placements": 0, "chunks": 0}
    for subject in manifest["subjects"]:
        counts = builder.json.loads(
            (builder.RELEASES / "profile_gate" / subject["path"]).read_text("utf-8")
        )["expected_counts"]
        for key in totals:
            totals[key] += counts[key]
    assert manifest["expected_counts"] == totals


def test_a_member_that_is_not_instanciated_is_refused_not_dropped(
    builder: Any,
) -> None:
    """Le désaccord doit être tranché par une décision, pas absorbé par l'outil."""
    with pytest.raises(builder.ReleaseMembershipError) as failure:
        builder.require_membership_is_admissible(
            [*yaml.safe_load(builder.MEMBERSHIP.read_text("utf-8"))["members"],
             "rag_nexus_maths_premiere_stmg_tc"]
        )
    assert "RELEASE_MEMBER => INSTANCIEE" in str(failure.value)
    assert "never drops a declared member" in str(failure.value)


def test_a_member_absent_from_the_catalogue_is_refused(builder: Any) -> None:
    with pytest.raises(builder.ReleaseMembershipError) as failure:
        builder.require_membership_is_admissible(["rag_nexus_not_a_collection"])
    assert "absent from the catalogue" in str(failure.value)


def test_a_repeated_member_is_refused(builder: Any) -> None:
    members = yaml.safe_load(builder.MEMBERSHIP.read_text("utf-8"))["members"]
    with pytest.raises(builder.ReleaseMembershipError) as failure:
        builder.require_membership_is_admissible([*members, members[0]])
    assert "repeats collections" in str(failure.value)


def test_an_empty_membership_is_refused(builder: Any) -> None:
    with pytest.raises(builder.ReleaseMembershipError):
        builder.require_membership_is_admissible([])


def test_the_rebuilt_registry_entry_matches_the_runtime_field_set(
    builder: Any,
) -> None:
    """Le registre est une autorité runtime au schéma fermé.

    Le moteur refuse toute entrée dont l'ensemble de champs diffère
    (`releases[i] fields mismatch`). L'égalité des deux ensembles est mesurée,
    jamais supposée : `rag-pedago` n'importe pas le code de `rag-engine`.
    """
    engine_source = (
        ROOT / "services/rag-engine/src/ingestor/release_readiness.py"
    ).read_text(encoding="utf-8")
    block = engine_source[engine_source.index("_REGISTRY_ENTRY_FIELDS = frozenset("):]
    block = block[: block.index(")")]
    engine_fields = set(re.findall(r'"([a-z0-9_]+)"', block))

    assert engine_fields == set(builder.REGISTRY_ENTRY_FIELDS)

    registry, _manifest = builder.build()
    assert set(registry["releases"][0]) == engine_fields


def test_the_milestone_marking_never_enters_the_runtime_registry(
    builder: Any,
) -> None:
    """« Ce jalon n'est pas le GO-LIVE » est une donnée de gouvernance.

    L'injecter dans le registre ferait refuser le démarrage du moteur, dont le
    schéma est fermé. Le fait vit dans le membership versionné.
    """
    registry, _manifest = builder.build()
    entry = registry["releases"][0]
    for governance_field in ("release_type", "go_live_complete", "release_name"):
        assert governance_field not in entry

    membership = yaml.safe_load(builder.MEMBERSHIP.read_text("utf-8"))
    assert membership["release_type"] == "intermediate"
    assert membership["go_live_complete"] is False
