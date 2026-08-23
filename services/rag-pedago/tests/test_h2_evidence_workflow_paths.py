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
_PROMOTE_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "promote.yml"

#: Drapeaux dont l'argument est un chemin de fichier LITTÉRAL (jamais
#: interpolé par une variable de campagne) qui doit exister à HEAD.
_STATIC_PATH_FLAGS = (
    "--routing",
    "--rights",
    "--pii",
    "--golden",
    "--config",
    "--profile-proposal-matrix",
    "--release-registry",
    "--authority-required-contents",
    "--currentness-verification",
)

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
    # V2 rehache les inputs dans le producteur Python et ne duplique plus
    # leurs chemins gouvernés dans des commandes sha256sum du workflow.
    assert checked == 0


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
    producer = (
        _REPO_ROOT
        / "services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py"
    ).read_text(encoding="utf-8")
    assert '"governance/trust-anchors/review-binding-v1.json"' in producer
    assert '"governance/trust-anchors/authorization-revocations-v1.json"' in producer
    combined = "\n".join(_run_blocks(_load_workflow()))
    assert '--json-output "${RUNNER_TEMP}/h2-coverage-evidence.json"' in combined


def test_v2_route_has_one_set_and_no_singular_authority_fallback() -> None:
    combined = "\n".join(_run_blocks(_load_workflow()))
    assert "--authorization-set" in combined
    assert "--h2-coverage-evidence" in combined
    assert "h2-evidence-v2" in combined
    tokens = re.findall(r"(?<![A-Za-z0-9-])--[a-z0-9-]+", combined)
    assert "--authority" not in tokens
    assert "--authority-review-binding" not in tokens
    assert "--authorization-sha256" not in tokens


def test_untrusted_expressions_never_enter_shell_source() -> None:
    for path in (_WORKFLOW_PATH, _PROMOTE_WORKFLOW_PATH):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in document["jobs"].values():
            for step in job.get("steps", []):
                assert "${{" not in step.get("run", ""), (
                    f"{path.name}:{step.get('name')} interpolates a GitHub "
                    "expression into shell source instead of passing it via env"
                )


def test_promotion_v2_downloads_and_verifies_the_exact_h2_artifact() -> None:
    document = yaml.safe_load(_PROMOTE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = document["jobs"]["assemble"]["steps"]
    download = next(step for step in steps if step.get("name") == "Download exact H2 V2 artifact")
    assert download["with"]["name"] == "${{ needs.h2-evidence.outputs.artifact_name }}"
    combined = "\n".join(step.get("run", "") for step in steps)
    assert "promotion-evidence-v2" in combined
    assert "H2_EVIDENCE_SHA256" in combined
    assert "NEXUS-PROMOTION-EVIDENCE-V1" not in combined


def test_v2_evidence_and_promotion_refuse_an_old_main_ancestor() -> None:
    """Fresh V2 evidence is produced only for the checked-out trusted HEAD.

    Replaying an already signed immutable readiness release remains a separate
    deploy concern; regenerating fresh H2/promotion evidence for an ancestor
    would mix current producer inputs with a foreign release identity.
    """
    for path, job_name in (
        (_WORKFLOW_PATH, "produce"),
        (_PROMOTE_WORKFLOW_PATH, "identity"),
    ):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        identity = next(
            step
            for step in document["jobs"][job_name]["steps"]
            if step.get("id") == "identity"
        )
        body = identity["run"]
        assert 'current_main_sha="$(git rev-parse HEAD)"' in body
        assert '[ "$merge_sha" != "$current_main_sha" ]' in body
        assert "git merge-base --is-ancestor" not in body


def test_promotion_assembly_is_pinned_and_rechecks_main_before_publication() -> None:
    document = yaml.safe_load(_PROMOTE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = document["jobs"]["assemble"]["steps"]
    checkout = steps[0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["ref"] == "${{ needs.identity.outputs.merge_sha }}"
    assert checkout["with"]["persist-credentials"] is False

    upload_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Upload promotion evidence"
    )
    recheck = steps[upload_index - 1]
    assert recheck["name"] == "Recheck frozen merge is still main HEAD"
    assert recheck["env"]["FROZEN_MERGE_SHA"] == (
        "${{ needs.identity.outputs.merge_sha }}"
    )
    body = recheck["run"]
    assert "git fetch --no-tags origin main" in body
    assert 'current_main_sha="$(git rev-parse origin/main)"' in body
    assert '[ "$current_main_sha" != "$FROZEN_MERGE_SHA" ]' in body

    # No step output is published before the final main-HEAD recheck.
    assert all(
        "GITHUB_OUTPUT" not in step.get("run", "")
        for step in steps[: upload_index - 1]
    )


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
