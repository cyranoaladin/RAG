"""Le préflight d'inférence dédiée refuse les inventaires ambigus."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "preflight_dedicated_inference_target.py"
)
SPEC = importlib.util.spec_from_file_location("inference_target_preflight", MODULE_PATH)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def inventory() -> dict:
    return {
        "hostname": "nexus-gpu-qualification",
        "machine_id_sha256": "a" * 64,
        "cpu_count": 16,
        "memory_kib": 67108864,
        "gpu": [{"name": "NVIDIA L4", "vram_mib": 23034, "driver": "580.0"}],
        "nvidia_container_cli": True,
        "docker_runtimes": ["nvidia", "runc"],
    }


class DedicatedInferencePreflightTests(unittest.TestCase):
    def test_ssh_alias_is_after_option_terminator(self) -> None:
        with patch.object(preflight.subprocess, "run") as runner, redirect_stdout(
            io.StringIO()
        ):
            runner.return_value = SimpleNamespace(returncode=1, stdout="")
            preflight.main(
                [
                    "--ssh-alias",
                    "nexus-gpu",
                    "--expected-hostname",
                    "nexus-gpu-qualification",
                    "--expected-machine-id-sha256",
                    "a" * 64,
                    "--production-hostname",
                    "korrigo",
                ]
            )
        argv = runner.call_args.args[0]
        self.assertEqual(argv[argv.index("--") + 1], "nexus-gpu")

    def test_ssh_alias_that_looks_like_an_option_is_refused(self) -> None:
        with patch.object(preflight.subprocess, "run") as runner, redirect_stderr(
            io.StringIO()
        ):
            with self.assertRaises(SystemExit):
                preflight.main(
                    [
                        "--ssh-alias=-oProxyCommand=ignored",
                        "--expected-hostname",
                        "nexus-gpu-qualification",
                        "--expected-machine-id-sha256",
                        "a" * 64,
                        "--production-hostname",
                        "korrigo",
                    ]
                )
        runner.assert_not_called()

    def test_probe_fingerprints_exact_machine_id_file_bytes(self) -> None:
        machine_id = Path("/etc/machine-id")
        if not machine_id.is_file():
            self.skipTest("machine-id absent de la machine de test")
        result = subprocess.run(
            [sys.executable, "-"],
            input=preflight.REMOTE_PROBE,
            capture_output=True,
            text=True,
            check=True,
        )
        observed = json.loads(result.stdout)
        self.assertEqual(
            observed["machine_id_sha256"],
            hashlib.sha256(machine_id.read_bytes()).hexdigest(),
        )

    def test_accepts_separate_pinned_gpu_host_inventory(self) -> None:
        self.assertEqual(
            preflight.evaluate_inventory(
                inventory(),
                expected_hostname="nexus-gpu-qualification",
                expected_machine_id_sha256="a" * 64,
                production_hostname="korrigo",
            ),
            [],
        )

    def test_refuses_historical_production_host_even_with_gpu(self) -> None:
        observed = inventory()
        observed["hostname"] = "korrigo"
        self.assertIn(
            "not_dedicated_from_production",
            preflight.evaluate_inventory(
                observed,
                expected_hostname="korrigo",
                expected_machine_id_sha256="a" * 64,
                production_hostname="korrigo",
            ),
        )

    def test_refuses_gpu_or_runtime_absence(self) -> None:
        observed = inventory()
        observed["gpu"] = []
        observed["docker_runtimes"] = ["runc"]
        observed["nvidia_container_cli"] = False
        reasons = preflight.evaluate_inventory(
            observed,
            expected_hostname="nexus-gpu-qualification",
            expected_machine_id_sha256="a" * 64,
            production_hostname="korrigo",
        )
        self.assertIn("nvidia_gpu_unavailable", reasons)
        self.assertIn("nvidia_container_runtime_unavailable", reasons)

    def test_refuses_identity_mismatch_and_invalid_resources(self) -> None:
        observed = inventory()
        observed["machine_id_sha256"] = "b" * 64
        observed["cpu_count"] = 0
        observed["gpu"][0]["vram_mib"] = 0
        reasons = preflight.evaluate_inventory(
            observed,
            expected_hostname="nexus-gpu-qualification",
            expected_machine_id_sha256="a" * 64,
            production_hostname="korrigo",
        )
        self.assertIn("machine_identity_mismatch", reasons)
        self.assertIn("cpu_inventory_invalid", reasons)
        self.assertIn("nvidia_gpu_unavailable", reasons)

    def test_missing_identity_never_passes(self) -> None:
        observed = inventory()
        observed.pop("machine_id_sha256")
        self.assertIn(
            "machine_identity_mismatch",
            preflight.evaluate_inventory(
                observed,
                expected_hostname="nexus-gpu-qualification",
                expected_machine_id_sha256="a" * 64,
                production_hostname="korrigo",
            ),
        )

    def test_malformed_runtime_inventory_fails_closed(self) -> None:
        observed = inventory()
        observed["docker_runtimes"] = None
        self.assertIn(
            "nvidia_container_runtime_unavailable",
            preflight.evaluate_inventory(
                observed,
                expected_hostname="nexus-gpu-qualification",
                expected_machine_id_sha256="a" * 64,
                production_hostname="korrigo",
            ),
        )


if __name__ == "__main__":
    unittest.main()
