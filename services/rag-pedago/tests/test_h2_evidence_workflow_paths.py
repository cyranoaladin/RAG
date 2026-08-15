"""Garde-fou structurel — `.github/workflows/_produce-h2-evidence.yml`.

Ce workflow est resté cassé depuis son introduction (même commit que les
fichiers réels, différemment nommés, PR #95 ; 0 exécution jamais) parce
que rien ne vérifiait automatiquement que les chemins littéraux qu'il
référence existent réellement dans le dépôt. Ce test ferme cette classe
de défaut : il n'exécute jamais le workflow (aucun accès réseau/GHCR ici),
il parse son YAML et confronte chaque chemin littéral qu'il référence à
l'arbre réel du dépôt.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = (
    _REPO_ROOT / ".github" / "workflows" / "_produce-h2-evidence.yml"
)

#: Drapeaux dont l'argument est un chemin de fichier LITTÉRAL (jamais
#: interpolé par une variable de campagne) qui doit exister à HEAD.
_STATIC_PATH_FLAGS = ("--routing", "--rights", "--pii", "--golden", "--config")

#: Interdits absolus dans un step `run:` réel (jamais seulement en
#: commentaire) : `h2b_coverage_report.py` les REFUSE explicitement en
#: `--authority-environment production` (TRUST_ANCHOR_ARGUMENT_FORBIDDEN /
#: REVOCATION_REGISTRY_ARGUMENT_FORBIDDEN) — les fournir n'est pas
#: seulement redondant, c'est un refus garanti.
_FORBIDDEN_PRODUCTION_FLAGS = ("--authority-trust-anchor", "--authority-revocations")


def _load_workflow() -> dict:
    return yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _run_blocks(document: dict) -> list[str]:
    """Le contenu de chaque `steps[].run:` du job `produce` — jamais les
    commentaires YAML (`#`), qui vivent hors de la structure parsée."""
    jobs = document.get("jobs", {})
    produce = jobs.get("produce", {})
    steps = produce.get("steps", [])
    return [
        step["run"]
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]


def _static_paths_after_flag(run_block: str, flag: str) -> list[str]:
    """Chemins suivant `flag` qui ne portent aucune interpolation
    `${...}` — donc résolvables statiquement, sans exécuter le workflow."""
    pattern = re.compile(re.escape(flag) + r" (\S+)")
    return [
        value
        for value in pattern.findall(run_block)
        if "${" not in value and "$" not in value
    ]


def _sha256sum_paths(run_block: str) -> list[str]:
    pattern = re.compile(r"sha256sum (\S+)")
    return [
        value
        for value in pattern.findall(run_block)
        if "${" not in value and "$" not in value and value != "|"
    ]


def test_workflow_yaml_is_valid() -> None:
    document = _load_workflow()
    assert isinstance(document, dict)
    assert "jobs" in document


def test_workflow_only_reachable_via_workflow_call() -> None:
    document = _load_workflow()
    assert set(document["on"]) == {"workflow_call"}


@pytest.mark.parametrize("flag", _STATIC_PATH_FLAGS)
def test_static_flag_paths_exist_on_disk(flag: str) -> None:
    document = _load_workflow()
    run_blocks = _run_blocks(document)
    found_any = False
    for run_block in run_blocks:
        for relative_path in _static_paths_after_flag(run_block, flag):
            found_any = True
            candidate = _REPO_ROOT / relative_path
            assert candidate.is_file(), (
                f"{flag} references {relative_path!r}, which does not exist "
                f"at {candidate} — this is exactly the class of bug that "
                "left this workflow broken and unrun since PR #95"
            )
    assert found_any, f"expected at least one static {flag} reference to check"


def test_sha256sum_static_paths_exist_on_disk() -> None:
    document = _load_workflow()
    run_blocks = _run_blocks(document)
    checked = 0
    for run_block in run_blocks:
        for relative_path in _sha256sum_paths(run_block):
            checked += 1
            candidate = _REPO_ROOT / relative_path
            assert candidate.is_file(), (
                f"sha256sum references {relative_path!r}, which does not "
                f"exist at {candidate}"
            )
    assert checked >= 6, "expected multiple static sha256sum references to check"


@pytest.mark.parametrize("forbidden_flag", _FORBIDDEN_PRODUCTION_FLAGS)
def test_production_forbidden_authority_flags_never_passed(forbidden_flag: str) -> None:
    """`h2b_coverage_report.py --authority-environment production` refuse
    explicitement `--authority-trust-anchor`/`--authority-revocations`
    (TRUST_ANCHOR_ARGUMENT_FORBIDDEN / REVOCATION_REGISTRY_ARGUMENT_
    FORBIDDEN) — le gate lit ces deux preuves lui-même aux chemins
    gouvernés. Un futur round qui les réintroduirait ferait échouer le
    gate H2 à coup sûr ; ce test l'attrape avant l'exécution réelle."""
    document = _load_workflow()
    for run_block in _run_blocks(document):
        assert forbidden_flag not in run_block, (
            f"{forbidden_flag} must never appear in a `run:` step of the "
            "H2 evidence production workflow while --authority-environment "
            "production is used — the real CLI refuses it outright"
        )


def test_governed_trust_anchor_and_revocation_registry_are_hashed_from_real_paths() -> None:
    """La preuve doit enregistrer le digest des fichiers RÉELLEMENT
    consultés par le gate en production (chemins gouvernés dans
    `h2b_coverage_report._resolve_trust_anchor_path`/`_load_revoked_
    authorization_ids`), jamais un chemin fictif qui n'a jamais existé."""
    document = _load_workflow()
    run_blocks = _run_blocks(document)
    combined = "\n".join(run_blocks)
    assert "governance/trust-anchors/review-binding-v1.json" in combined
    assert "governance/trust-anchors/authorization-revocations-v1.json" in combined


def test_actions_are_pinned_by_commit_sha() -> None:
    document = _load_workflow()
    jobs = document.get("jobs", {})
    produce = jobs.get("produce", {})
    steps = produce.get("steps", [])
    uses_lines = [step["uses"] for step in steps if isinstance(step, dict) and "uses" in step]
    assert uses_lines, "expected at least one 'uses:' step"
    for uses in uses_lines:
        _, _, ref = uses.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", ref), (
            f"{uses!r} is not pinned to a 40-hex commit SHA"
        )


def test_no_private_signing_key_material_referenced() -> None:
    """Ce workflow *constate* ; il ne signe jamais rien — aucune clé
    privée ne doit apparaître, même sous forme de nom de secret."""
    raw = _WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("private_key", "signing_key", "readiness_key"):
        assert forbidden not in raw, f"found forbidden reference: {forbidden}"
