#!/usr/bin/env python3
"""Inventaire SSH en lecture seule d'une cible GPU distincte de la production.

Ce contrôle qualifie l'identité et la disponibilité apparente du GPU, pas le
chargement des modèles, la connectivité DB, la performance ni la charge C0.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

REMOTE_PROBE = r"""
import csv
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""

try:
    machine_id_bytes = Path("/etc/machine-id").read_bytes()
except OSError:
    machine_id_bytes = b""
try:
    memory_kib = int(next(line.split()[1] for line in
        Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal:")))
except (OSError, ValueError, StopIteration):
    memory_kib = 0
gpu_status, gpu_csv = run([
    "nvidia-smi", "--query-gpu=name,memory.total,driver_version",
    "--format=csv,noheader,nounits",
])
gpus = []
if gpu_status == 0:
    for row in csv.reader(gpu_csv.splitlines()):
        if len(row) == 3:
            try:
                vram_mib = int(row[1].strip())
            except ValueError:
                vram_mib = 0
            gpus.append({"name": row[0].strip(), "vram_mib": vram_mib,
                         "driver": row[2].strip()})
toolkit_status, _ = run(["nvidia-container-cli", "--version"])
docker_status, runtime_names = run([
    "docker", "info", "--format",
    "{{range $name, $runtime := .Runtimes}}{{$name}} {{end}}",
])
print(json.dumps({
    "hostname": socket.gethostname().split(".")[0],
    "machine_id_sha256": hashlib.sha256(machine_id_bytes).hexdigest() if machine_id_bytes else "",
    "cpu_count": os.cpu_count(),
    "memory_kib": memory_kib,
    "gpu": gpus,
    "nvidia_container_cli": toolkit_status == 0,
    "docker_runtimes": runtime_names.split() if docker_status == 0 else [],
}, sort_keys=True))
"""


def evaluate_inventory(
    observed: dict[str, Any],
    *,
    expected_hostname: str,
    expected_machine_id_sha256: str,
    production_hostname: str,
) -> list[str]:
    """Rendre les motifs de refus sans supposer qu'un champ manquant est sûr."""
    reasons: list[str] = []
    hostname = observed.get("hostname")
    if not hostname or hostname != expected_hostname:
        reasons.append("host_identity_mismatch")
    if hostname == production_hostname or expected_hostname == production_hostname:
        reasons.append("not_dedicated_from_production")
    machine_id = observed.get("machine_id_sha256")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_machine_id_sha256)
        or machine_id != expected_machine_id_sha256
    ):
        reasons.append("machine_identity_mismatch")
    if not isinstance(observed.get("cpu_count"), int) or observed["cpu_count"] <= 0:
        reasons.append("cpu_inventory_invalid")
    if not isinstance(observed.get("memory_kib"), int) or observed["memory_kib"] <= 0:
        reasons.append("memory_inventory_invalid")
    gpus = observed.get("gpu")
    if not isinstance(gpus, list) or not any(
        isinstance(gpu, dict)
        and isinstance(gpu.get("name"), str)
        and gpu["name"]
        and isinstance(gpu.get("driver"), str)
        and gpu["driver"]
        and isinstance(gpu.get("vram_mib"), int)
        and gpu["vram_mib"] > 0
        for gpu in gpus
    ):
        reasons.append("nvidia_gpu_unavailable")
    runtimes = observed.get("docker_runtimes")
    if (
        observed.get("nvidia_container_cli") is not True
        or not isinstance(runtimes, list)
        or "nvidia" not in runtimes
    ):
        reasons.append("nvidia_container_runtime_unavailable")
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ssh-alias", required=True, help="alias SSH déjà configuré ; aucun secret"
    )
    parser.add_argument("--expected-hostname", required=True)
    parser.add_argument("--expected-machine-id-sha256", required=True)
    parser.add_argument("--production-hostname", required=True)
    args = parser.parse_args(argv)
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=8",
                args.ssh_alias,
                "python3",
                "-",
            ],
            input=REMOTE_PROBE,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        observed = json.loads(result.stdout) if result.returncode == 0 else {}
        if not isinstance(observed, dict):
            observed = {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        observed = {}
    reasons = evaluate_inventory(
        observed,
        expected_hostname=args.expected_hostname,
        expected_machine_id_sha256=args.expected_machine_id_sha256,
        production_hostname=args.production_hostname,
    )
    if not observed:
        reasons.insert(0, "ssh_probe_unavailable")
    report = {
        "kind": "NEXUS-DEDICATED-INFERENCE-HOST-PREFLIGHT-V1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "ssh_alias": args.ssh_alias,
        "expected_hostname": args.expected_hostname,
        "production_hostname": args.production_hostname,
        "observed": observed,
        "HOST_GPU_PREFLIGHT_PASS": not reasons,
        "reasons": reasons,
        "LOAD_PASS": False,
    }
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
