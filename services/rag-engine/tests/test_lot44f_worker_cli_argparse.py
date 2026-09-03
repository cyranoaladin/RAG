"""Remédiation revue PR#90 (Cubic P2) : validation des paramètres du worker
CLI à l'analyse des arguments — jamais un échec tardif au premier usage.

Périmètre strict : ``ingestion_worker.cli._build_arg_parser()`` et ses
validateurs — aucun PostgreSQL, aucune connexion réelle.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ingestor.ingestion_worker.cli import (
    _build_arg_parser,
    _finite_non_negative_float,
    _non_blank_str,
    _positive_int,
)

_REQUIRED_ARGS = [
    "--profiles-dir", "/tmp/profiles",
    "--manifest-path", "/tmp/manifest.yml",
    "--artifact-store-dir", "/tmp/artifacts",
    "--expected-role", "ingestion_control_app",
    "--owner", "worker-1",
    "--pii-evidence-path", "/tmp/pii.json",
    "--pii-evidence-sha256", "a" * 64,
    "--rights-evidence-path", "/tmp/rights.yml",
    "--rights-evidence-sha256", "b" * 64,
    "--corpus-manifest-sha256", "d" * 64,
    "--catalog-path", "/tmp/catalog.json",
    "--catalog-sha256", "e" * 64,
    "--candidate-inventory-path", "/tmp/inventory.json",
    "--candidate-inventory-sha256", "f" * 64,
    "--currentness-evidence-path", "/tmp/currentness.yml",
    "--currentness-evidence-sha256", "1" * 64,
    "--mapping-path", "/tmp/mapping.yml",
    "--mapping-sha256", "2" * 64,
    "--release-manifest-path", "/tmp/release.json",
    "--release-manifest-sha256", "3" * 64,
    "--programme-index-path", "/tmp/programme.yml",
    "--programme-index-sha256", "4" * 64,
    "--collection-config-path", "/tmp/collections.yml",
    "--collection-config-sha256", "5" * 64,
]


class TestPositiveIntValidator:
    def test_accepts_positive_value(self) -> None:
        assert _positive_int("5") == 5

    @pytest.mark.parametrize("raw", ["0", "-1", "-100"])
    def test_rejects_non_positive_value(self, raw: str) -> None:
        with pytest.raises(Exception, match="positive"):
            _positive_int(raw)


class TestFiniteNonNegativeFloatValidator:
    def test_accepts_zero(self) -> None:
        assert _finite_non_negative_float("0") == 0.0

    def test_accepts_positive_value(self) -> None:
        assert _finite_non_negative_float("5.5") == 5.5

    @pytest.mark.parametrize("raw", ["-1", "-0.001"])
    def test_rejects_negative_value(self, raw: str) -> None:
        with pytest.raises(Exception, match="non-negative"):
            _finite_non_negative_float(raw)

    def test_rejects_infinity(self) -> None:
        with pytest.raises(Exception, match="finite"):
            _finite_non_negative_float("inf")


class TestNonBlankStrValidator:
    def test_accepts_non_blank(self) -> None:
        assert _non_blank_str("worker-1") == "worker-1"

    @pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
    def test_rejects_blank(self, raw: str) -> None:
        with pytest.raises(Exception, match="blank"):
            _non_blank_str(raw)


class TestArgParserIntegration:
    def test_negative_max_iterations_is_rejected_at_parse_time(self) -> None:
        parser = _build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([*_REQUIRED_ARGS, "--max-iterations", "-1"])

    def test_negative_poll_interval_is_rejected_at_parse_time(self) -> None:
        parser = _build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([*_REQUIRED_ARGS, "--poll-interval-s", "-2.0"])

    def test_blank_owner_is_rejected_at_parse_time(self) -> None:
        parser = _build_arg_parser()
        args_without_owner = list(_REQUIRED_ARGS)
        args_without_owner[args_without_owner.index("--owner") + 1] = "   "
        with pytest.raises(SystemExit):
            parser.parse_args(args_without_owner)

    def test_valid_arguments_parse_successfully(self) -> None:
        parser = _build_arg_parser()
        args = parser.parse_args([*_REQUIRED_ARGS, "--max-iterations", "3", "--poll-interval-s", "1.5"])
        assert args.owner == "worker-1"
        assert args.max_iterations == 3
        assert args.poll_interval_s == 1.5
        assert args.profiles_dir == Path("/tmp/profiles")

    def test_resource_registry_cutover_arguments_are_available(self) -> None:
        parser = _build_arg_parser()
        args = parser.parse_args(
            [
                *_REQUIRED_ARGS,
                "--resource-registry-snapshot-path",
                "/proof/resource-registry.json",
                "--resource-registry-snapshot-file-sha256",
                "a" * 64,
            ]
        )

        assert args.resource_registry_snapshot_path == Path(
            "/proof/resource-registry.json"
        )
        assert args.resource_registry_snapshot_file_sha256 == "a" * 64
