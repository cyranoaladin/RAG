"""Tests des points d'entrée CLI et de la structure du workflow producteur.

Le workflow est chargé et interrogé comme une structure de données. Ce
n'est pas une inspection de texte : ce sont les clés que GitHub Actions
lit réellement, et une propriété comme « `workflow_call` uniquement » n'a
pas d'autre représentation vérifiable.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from rag_pedago.governance import cli as governance_cli
from rag_pedago.governance.cli import build_parser
from rag_pedago.governance.release_scope_placement import (
    ReleaseScopePlacementGitInputs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCER = REPO_ROOT / ".github" / "workflows" / "_produce-h2-evidence.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    if not PRODUCER.is_file():
        pytest.fail(f"the canonical producer workflow is missing at {PRODUCER}")
    return yaml.safe_load(PRODUCER.read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    # PyYAML lit le `on:` non quoté comme le booléen True ; le fichier le
    # quote, mais on accepte les deux pour ne pas dépendre du parseur.
    return workflow.get("on") or workflow.get(True)


class TestProducerWorkflowShape:
    def test_it_can_only_be_called_never_triggered(self, workflow: dict) -> None:
        """Une preuve produite par un `push` décrirait du code non fusionné,
        donc du code que personne n'a approuvé sous sa forme finale."""
        assert list(triggers(workflow)) == ["workflow_call"]

    def test_it_carries_no_write_permission(self, workflow: dict) -> None:
        assert workflow["permissions"] == {
            "contents": "read",
            "packages": "read",
            "pull-requests": "read",
        }

    def test_it_runs_in_the_protected_environment(self, workflow: dict) -> None:
        assert workflow["jobs"]["produce"]["environment"] == "production"

    def test_it_declares_no_secret_input(self, workflow: dict) -> None:
        """Le workflow constate ; il ne signe pas. Une clé ici permettrait
        à un producteur compromis de fabriquer une preuve *signée*."""
        call = triggers(workflow)["workflow_call"]
        assert "secrets" not in call

    def test_its_inputs_cannot_designate_a_corpus(self, workflow: dict) -> None:
        """Un input qui nommerait une référence OCI rendrait la campagne
        décorative."""
        inputs = triggers(workflow)["workflow_call"]["inputs"]
        assert set(inputs) == {"pull_request_number", "campaign_id"}
        joined = " ".join(inputs).lower()
        for forbidden in ("digest", "reference", "registry", "tag", "url", "path"):
            assert forbidden not in joined

    def test_it_publishes_the_derived_artifact_name(self, workflow: dict) -> None:
        upload = workflow["jobs"]["produce"]["steps"][-1]
        assert upload["uses"].startswith("actions/upload-artifact@")
        assert upload["with"]["name"] == ("${{ steps.evidence.outputs.artifact_name }}")
        assert upload["with"]["if-no-files-found"] == "error"

    def test_evidence_is_retained_through_human_approval(self, workflow: dict) -> None:
        upload = workflow["jobs"]["produce"]["steps"][-1]
        assert int(upload["with"]["retention-days"]) >= 90

    def test_every_action_is_pinned_to_a_digest(self, workflow: dict) -> None:
        """Un tag d'action est repointable : `@v4` aujourd'hui et demain ne
        sont pas le même code."""
        for step in workflow["jobs"]["produce"]["steps"]:
            uses = step.get("uses")
            if uses is None:
                continue
            _, _, ref = uses.partition("@")
            assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), (
                f"{uses} is not pinned to a full commit SHA"
            )

    def test_it_exports_every_digest_the_promotion_needs(self, workflow: dict) -> None:
        outputs = set(triggers(workflow)["workflow_call"]["outputs"])
        assert {
            "merge_sha",
            "artifact_name",
            "evidence_sha256",
            "source_oci_digest",
            "manifest_sha256",
            "catalog_sha256",
            "review_view_sha256",
        } <= outputs

    def test_the_governance_code_comes_from_main(self, workflow: dict) -> None:
        """Un producteur qui exécuterait le code qu'il doit vérifier
        pourrait se déclarer conforme."""
        checkout = workflow["jobs"]["produce"]["steps"][0]
        assert checkout["with"]["ref"] == "refs/heads/main"
        assert checkout["with"]["persist-credentials"] is False

    def test_it_calls_the_sealed_compiler_not_the_legacy_one(self, workflow: dict) -> None:
        """Sans `--sealed-manifest`, la CLI compilerait l'inventaire TSV
        historique, explicitement non autoritaire."""
        body = "\n".join(step.get("run", "") for step in workflow["jobs"]["produce"]["steps"])
        assert "--sealed-manifest" in body
        assert "corpus_catalog_compiler \\\n            --manifest" not in body

    def test_the_three_gate_flags_are_checked_separately(self, workflow: dict) -> None:
        """Un « et » global masquerait laquelle des trois preuves a manqué.

        Chaque drapeau doit être lu du rapport et refusé par sa propre
        garde, avec son propre message : trois lectures, trois sorties en
        erreur distinctes."""
        gate_step = next(
            step for step in workflow["jobs"]["produce"]["steps"] if step.get("id") == "gate"
        )
        body = gate_step["run"]
        for flag in (
            "h2_coverage_gate_pass",
            "authority_revocations_checked",
            "coverage_complete",
        ):
            assert f".{flag}" in body, f"{flag} is never read from the report"

        guards = [line for line in body.splitlines() if "exit 1" in line]
        assert len(guards) == 3, f"expected one guard per flag, found {len(guards)}"
        # Trois messages distincts : un opérateur doit savoir laquelle des
        # trois preuves a manqué sans relire le rapport.
        assert len({line.strip() for line in guards}) == 3


class TestGovernanceCli:
    @staticmethod
    def _valid_republish_v2_argv(tmp_path: Path) -> list[str]:
        return [
            "republish-catalog-v2",
            "--campaign-relative-path",
            "governance/corpus-campaigns/campaign-v2/campaign.json",
            "--catalog",
            str(tmp_path / "catalog.json"),
            "--authorization-set-relative-path",
            "governance/authorization-sets/release-v1.json",
            "--repository-root",
            str(tmp_path / "repo"),
            "--source-tree-sha",
            "a" * 40,
            "--profile-proposal-matrix",
            "docs/reports/profile-matrix.json",
            "--placements",
            "governance/release-scope/accepted.json",
            "--release-registry",
            "governance/releases/release.json",
            "--expected-contents",
            "docs/reports/final-set.txt",
            "--verified-profiles",
            "governance/profiles/verified.json",
            "--profile-manifest",
            "services/rag-engine/configs/ingestion_profiles/manifest.yml",
            "--out-root",
            str(tmp_path / "out"),
        ]

    def test_the_nine_subcommands_exist(self) -> None:
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
        assert set(choices) == {
            "resolve-corpus",
            "resolve-corpus-v2",
            "review-view",
            "h2-evidence",
            "h2-evidence-v2",
            "promotion-evidence-v2",
            "republish-catalog",
            "republish-catalog-v2",
            "release-scope-placement",
        }

    def test_resolve_v2_has_no_legacy_protocol_fallback(self) -> None:
        parser = build_parser()
        resolve = parser._subparsers._group_actions[0].choices["resolve-corpus-v2"]  # type: ignore[union-attr]
        flags = {
            option
            for action in resolve._actions
            for option in action.option_strings
        }
        assert flags == {"-h", "--help", "--campaign", "--destination", "--output"}

    def test_republish_catalog_requires_every_binding(self) -> None:
        """Un champ optionnel serait un champ qu'un producteur peut omettre
        en silence — même discipline que ``h2-evidence``."""
        parser = build_parser()
        republish = parser._subparsers._group_actions[0].choices["republish-catalog"]  # type: ignore[union-attr]
        optional = [
            action.option_strings[0]
            for action in republish._actions
            if action.option_strings and action.option_strings[0] != "-h" and not action.required
        ]
        assert optional == []

    def test_republish_catalog_v2_uses_set_and_exact_git_placement_only(self) -> None:
        parser = build_parser()
        republish = parser._subparsers._group_actions[0].choices[  # type: ignore[union-attr]
            "republish-catalog-v2"
        ]
        flags = {
            option
            for action in republish._actions
            for option in action.option_strings
        }
        assert {
            "--campaign-relative-path",
            "--catalog",
            "--authorization-set-relative-path",
            "--repository-root",
            "--source-tree-sha",
            "--profile-proposal-matrix",
            "--placements",
            "--release-registry",
            "--expected-contents",
            "--verified-profiles",
            "--profile-manifest",
            "--out-root",
        } <= flags
        for forbidden in (
            "--authority",
            "--authority-review-binding",
            "--authorization-file",
            "--review-binding",
        ):
            assert forbidden not in flags

    def test_republish_v1_and_v2_arguments_cannot_be_mixed(self, tmp_path: Path) -> None:
        parser = build_parser()
        v2 = self._valid_republish_v2_argv(tmp_path)
        with pytest.raises(SystemExit):
            parser.parse_args([*v2, "--authority", str(tmp_path / "authority.json")])

        v1 = [
            "republish-catalog",
            "--campaign",
            str(tmp_path / "campaign.json"),
            "--catalog",
            str(tmp_path / "catalog.json"),
            "--authority",
            str(tmp_path / "authority.json"),
            "--authority-review-binding",
            str(tmp_path / "binding.json"),
            "--out-root",
            str(tmp_path / "out"),
        ]
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    *v1,
                    "--authorization-set-relative-path",
                    "governance/authorization-sets/release-v1.json",
                ]
            )

    def test_republish_catalog_v2_builds_the_frozen_git_input_descriptor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_republish_catalog_v2(**kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(
                catalog_path=tmp_path / "out/catalog.json",
                catalog_sha256="b" * 64,
                promoted_count=72,
                mapped_content_count=72,
                authorization_set_digest="c" * 64,
                already_published=False,
            )

        monkeypatch.setattr(
            governance_cli,
            "republish_catalog_v2",
            fake_republish_catalog_v2,
            raising=False,
        )
        parser = build_parser()
        args = parser.parse_args(self._valid_republish_v2_argv(tmp_path))

        assert args.func(args) == 0
        assert captured["campaign_relative_path"] == (
            "governance/corpus-campaigns/campaign-v2/campaign.json"
        )
        assert captured["authorization_set_relative_path"] == (
            "governance/authorization-sets/release-v1.json"
        )
        assert captured["release_scope_git_inputs"] == ReleaseScopePlacementGitInputs(
            repository_root=tmp_path / "repo",
            source_tree_sha="a" * 40,
            profile_proposal_matrix_path="docs/reports/profile-matrix.json",
            accepted_placements_path="governance/release-scope/accepted.json",
            release_registry_path="governance/releases/release.json",
            expected_contents_path="docs/reports/final-set.txt",
            verified_profiles_path="governance/profiles/verified.json",
            profile_manifest_path=(
                "services/rag-engine/configs/ingestion_profiles/manifest.yml"
            ),
        )

    def test_promotion_v2_consumes_the_exact_h2_bundle(self) -> None:
        parser = build_parser()
        promotion = parser._subparsers._group_actions[0].choices["promotion-evidence-v2"]  # type: ignore[union-attr]
        flags = {
            option
            for action in promotion._actions
            for option in action.option_strings
        }
        assert {"--h2-evidence", "--promotion-time", "--json-output"} <= flags
        for forbidden in ("--authorization", "--authority", "--review-binding"):
            assert forbidden not in flags

    def test_h2_evidence_v2_requires_set_and_json_output_without_singular_fallback(
        self,
    ) -> None:
        parser = build_parser()
        evidence = parser._subparsers._group_actions[0].choices["h2-evidence-v2"]  # type: ignore[union-attr]
        flags = {
            option
            for action in evidence._actions
            for option in action.option_strings
        }
        assert "--authorization-set" in flags
        assert "--h2-coverage-evidence" in flags
        assert "--json-output" in flags
        for forbidden in (
            "--authorization-file",
            "--authorization-sha256",
            "--authority",
            "--authority-review-binding",
        ):
            assert forbidden not in flags
        optional = [
            action.option_strings[0]
            for action in evidence._actions
            if action.option_strings
            and action.option_strings[0] != "-h"
            and not action.required
        ]
        assert optional == []

    def test_resolve_corpus_takes_no_reference_argument(self) -> None:
        """La référence est dérivée du descripteur ; aucun argument ne peut
        la remplacer."""
        parser = build_parser()
        resolve = parser._subparsers._group_actions[0].choices["resolve-corpus"]  # type: ignore[union-attr]
        flags = {option for action in resolve._actions for option in action.option_strings}
        for forbidden in ("--reference", "--registry", "--tag", "--digest", "--url"):
            assert forbidden not in flags

    def test_h2_evidence_requires_every_binding(self) -> None:
        """Un champ optionnel serait un champ qu'un producteur peut omettre
        en silence."""
        parser = build_parser()
        evidence = parser._subparsers._group_actions[0].choices["h2-evidence"]  # type: ignore[union-attr]
        optional = [
            action.option_strings[0]
            for action in evidence._actions
            if action.option_strings and action.option_strings[0] != "-h" and not action.required
        ]
        assert optional == []


class TestCompilerCliModes:
    """La voie sûre doit être demandée, jamais supposée — mais elle doit
    exister."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "rag_pedago.imports.corpus_catalog_compiler", *args],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT / "services" / "rag-pedago",
        )

    def test_neither_mode_is_refused(self) -> None:
        result = self._run("--config", "configs/corpus_zone_routing.yml")
        assert result.returncode != 0
        assert "exactly one of" in result.stderr

    def test_both_modes_at_once_are_refused(self) -> None:
        """Deux identités sans que rien ne dise laquelle prévaut."""
        result = self._run(
            "--manifest",
            "a.tsv",
            "--sealed-manifest",
            "b.txt",
            "--config",
            "configs/corpus_zone_routing.yml",
        )
        assert result.returncode != 0
        assert "exactly one of" in result.stderr

    def test_the_sealed_mode_requires_a_placement_catalog(self) -> None:
        result = self._run(
            "--sealed-manifest",
            "b.txt",
            "--config",
            "configs/corpus_zone_routing.yml",
        )
        assert result.returncode != 0
        assert "--placement-catalog is required" in result.stderr

    def test_the_help_marks_the_legacy_path_as_non_authoritative(self) -> None:
        result = self._run("--help")
        assert "NOT a sealed manifest" in result.stdout
