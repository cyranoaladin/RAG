"""Injection de l'autorité de revue PII par le mécanisme canonique (ADR-0047).

Le worker ne connaît aucune campagne. Il reçoit, comme toutes ses autres
autorités, des couples `--<nom>-path` / `--<nom>-sha256` et une allowlist de
reviewers ; il les vérifie ; il refuse si la chaîne ne tient pas. Faire tourner
un autre ensemble de décisions demain ne doit toucher aucun fichier Python.

Ces tests portent sur le *mécanisme*, pas sur son contenu : ils ne nomment
jamais un identifiant de campagne réel.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ingestor.ingestion_worker.multilevel_runtime_authority import (
    add_multilevel_runtime_authority_arguments,
    multilevel_runtime_authority_inputs_from_args,
)
from ingestor.ingestion_worker.runtime_authority import (
    add_runtime_authority_arguments,
    runtime_authority_inputs_from_args,
)

REVIEW_ARGUMENTS = (
    "pii-decision-set",
    "pii-review-receipt",
    "review-trust-anchor",
)


def _parser(add: object) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    add(parser)  # type: ignore[operator]
    return parser


def _wave0_parser() -> argparse.ArgumentParser:
    """Le parseur tel que les CLI le composent : autorités + preuves scellées.

    `add_runtime_authority_arguments` ne déclare pas les preuves PII/droits ni
    le manifeste de corpus — les CLI les ajoutent. On reproduit cet assemblage
    plutôt que d'en supposer un autre."""
    parser = _parser(add_runtime_authority_arguments)
    parser.add_argument("--pii-evidence-path", required=True, type=Path)
    parser.add_argument("--pii-evidence-sha256", required=True)
    parser.add_argument("--rights-evidence-path", required=True, type=Path)
    parser.add_argument("--rights-evidence-sha256", required=True)
    parser.add_argument("--corpus-manifest-sha256", required=True)
    return parser


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


class TestArgumentsAreDeclared:
    def test_wave0_parser_declares_the_review_authority_couples(self) -> None:
        options = _option_strings(_parser(add_runtime_authority_arguments))
        for name in REVIEW_ARGUMENTS:
            assert f"--{name}-path" in options
            assert f"--{name}-sha256" in options
        assert "--pii-review-reviewer" in options

    def test_multilevel_parser_declares_the_review_authority_couples(self) -> None:
        options = _option_strings(_parser(add_multilevel_runtime_authority_arguments))
        for name in REVIEW_ARGUMENTS:
            assert f"--{name}-path" in options
            assert f"--{name}-sha256" in options
        assert "--pii-review-reviewer" in options

    def test_review_authority_is_optional(self) -> None:
        """Une release sans aucun contenu détecté n'a pas de décisions à joindre.

        L'absence n'ouvre rien : le registre refuse toute entrée qui se
        déclare admise sans ensemble scellé. C'est là qu'est la garde, pas
        dans l'obligation de passer un fichier vide."""
        parser = _parser(add_runtime_authority_arguments)
        for action in parser._actions:
            if any(opt.startswith(f"--{n}") for n in REVIEW_ARGUMENTS for opt in action.option_strings):
                assert action.required is False


class TestInputsCarryTheInjectedAuthority:
    def _base(self) -> list[str]:
        args: list[str] = []
        for name in (
            "catalog", "candidate-inventory", "currentness-evidence", "mapping",
            "release-manifest", "programme-index", "collection-config",
            "pii-evidence", "rights-evidence",
        ):
            args += [f"--{name}-path", f"/tmp/{name}.json", f"--{name}-sha256", "0" * 64]
        args += ["--corpus-manifest-sha256", "1" * 64]
        return args

    def test_absent_review_authority_yields_none_not_a_guess(self) -> None:
        parser = _wave0_parser()
        inputs = runtime_authority_inputs_from_args(parser.parse_args(self._base()))
        assert inputs.pii_decision_set_path is None
        assert inputs.pii_review_receipt_path is None
        assert inputs.review_trust_anchor_path is None
        assert inputs.pii_review_reviewers == ()

    def test_injected_review_authority_reaches_the_inputs(self) -> None:
        parser = _wave0_parser()
        extra = [
            "--pii-decision-set-path", "/tmp/ds.json",
            "--pii-decision-set-sha256", "2" * 64,
            "--pii-review-receipt-path", "/tmp/receipt.json",
            "--pii-review-receipt-sha256", "3" * 64,
            "--review-trust-anchor-path", "/tmp/anchor.json",
            "--review-trust-anchor-sha256", "4" * 64,
            "--pii-review-reviewer", "reviewer-one",
            "--pii-review-reviewer", "reviewer-two",
        ]
        inputs = runtime_authority_inputs_from_args(parser.parse_args(self._base() + extra))
        assert inputs.pii_decision_set_path == Path("/tmp/ds.json")
        assert inputs.pii_decision_set_sha256 == "2" * 64
        assert inputs.pii_review_receipt_path == Path("/tmp/receipt.json")
        assert inputs.review_trust_anchor_path == Path("/tmp/anchor.json")
        assert inputs.review_trust_anchor_sha256 == "4" * 64
        assert inputs.pii_review_reviewers == ("reviewer-one", "reviewer-two")

    def test_multilevel_inputs_carry_the_injected_authority(self) -> None:
        parser = _parser(add_multilevel_runtime_authority_arguments)
        args: list[str] = []
        for name in (
            "candidate-inventory", "currentness-evidence", "levels-mapping",
            "subjects-mapping", "document-types-mapping", "release-manifest",
            "programme-registry", "profile-manifest", "collection-config",
            "pii-evidence", "rights-evidence",
        ):
            args += [f"--{name}-path", f"/tmp/{name}.json", f"--{name}-sha256", "0" * 64]
        args += [
            "--corpus-manifest-sha256", "1" * 64,
            "--repository-root", "/tmp/repo",
            "--pii-decision-set-path", "/tmp/ds.json",
            "--pii-decision-set-sha256", "2" * 64,
            "--pii-review-receipt-path", "/tmp/receipt.json",
            "--pii-review-receipt-sha256", "3" * 64,
            "--review-trust-anchor-path", "/tmp/anchor.json",
            "--review-trust-anchor-sha256", "4" * 64,
            "--pii-review-reviewer", "reviewer-one",
        ]
        inputs = multilevel_runtime_authority_inputs_from_args(parser.parse_args(args))
        assert inputs.pii_decision_set_path == Path("/tmp/ds.json")
        assert inputs.pii_review_reviewers == ("reviewer-one",)
