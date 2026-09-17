#!/usr/bin/env python3
"""Prépare et scelle la preuve STAGING_EXTERNE en mode C (runbook seulement).

Ce script ne déploie rien et ne joint aucun hôte. Il DÉRIVE du Compose réel ce
qu'un opérateur devra fournir (services, ports, variables — noms seuls, jamais de
valeurs —, stockage), vérifie que ce Compose se résout, et scelle une preuve dont
le statut est `RUNBOOK_ONLY_NOT_QUALIFIED`.

Cette preuve NE FERME PAS le blocage : `verifier_staging_externe` refuse
`runbook_only`. Un staging externe se prouve en le démarrant ; les modes A et B
s'ajouteront ici le jour où un hôte sera désigné par l'opérateur.

`--verify-only` revérifie la preuve scellée.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import build_qualification_blockers as blocages  # noqa: E402

COMPOSE = "services/rag-engine/infra/docker-compose.v2.yml"
RUNBOOK = "docs/runbooks/staging_externe.md"
PRODUCTEUR_SECRETS = "services/rag-engine/scripts/prepare_staging_environment.py"
RECETTE = "scripts/staging_external_acceptance.py"
_VARIABLE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(:\?|:-)?")
_FACTICE = "rehearsal-placeholder"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout.strip()


def _variables(texte: str) -> tuple[list[str], list[str]]:
    requises, optionnelles = set(), set()
    for nom, operateur in _VARIABLE.findall(texte):
        (requises if operateur == ":?" else optionnelles).add(nom)
    return sorted(requises), sorted(optionnelles - requises)


def _compose_resolu(requises: list[str]) -> dict:
    """`docker compose config` avec des valeurs factices : prouve que le fichier se
    résout, rien de plus. Les valeurs ne sont ni réelles ni conservées."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    for nom in requises:
        env[nom] = "/tmp" if nom.endswith(("_DIR", "_FILE")) else _FACTICE
    rendu = subprocess.run(
        # `--env-file /dev/null` : un `.env` local du poste ne doit ni être lu ni teinter la preuve.
        ["docker", "compose", "--env-file", "/dev/null", "-f", str(RACINE / COMPOSE),
         "config", "--format", "json"],
        env=env, capture_output=True, text=True, check=False,
    )
    if rendu.returncode != 0:
        return {"resolves": False, "error": rendu.stderr.strip().splitlines()[-1][:200]}
    config = json.loads(rendu.stdout)
    services = config["services"]
    return {
        "resolves": True,
        "services": sorted(services),
        "ports": {
            nom: [f"{p.get('host_ip', '')}:{p.get('published')}->{p.get('target')}" for p in s.get("ports", [])]
            for nom, s in services.items()
        },
        "all_ports_bound_to_loopback": all(
            p.get("host_ip") == "127.0.0.1" for s in services.values() for p in s.get("ports", [])
        ),
        "cpu_limits": {
            nom: ((s.get("deploy") or {}).get("resources") or {}).get("limits", {}).get("cpus")
            for nom, s in services.items()
        },
        "named_volumes": sorted(config.get("volumes", {})),
        "images_pinned_by_digest": {
            nom: "@sha256:" in s["image"] for nom, s in services.items() if "image" in s
        },
        "services_built_not_pinned": sorted(n for n, s in services.items() if "image" not in s or "build" in s),
    }


def sceller_runbook() -> int:
    base_main = _git("merge-base", "HEAD", "origin/main")
    if base_main != blocages.STAGING_MAIN_SHA_ATTENDU:
        print(f"REFUS : base main {base_main} != {blocages.STAGING_MAIN_SHA_ATTENDU}", file=sys.stderr)
        return 2
    for relatif in (COMPOSE, RUNBOOK, PRODUCTEUR_SECRETS, RECETTE):
        if not (RACINE / relatif).is_file():
            print(f"REFUS : pièce du runbook absente : {relatif}", file=sys.stderr)
            return 2
    texte = (RACINE / COMPOSE).read_text(encoding="utf-8")
    requises, optionnelles = _variables(texte)
    resolu = _compose_resolu(requises)
    runbook = (RACINE / RUNBOOK).read_text(encoding="utf-8")

    preuve = {
        "kind": "NEXUS-EXTERNAL-STAGING-PROOF-V1",
        "verification_status": "RUNBOOK_ONLY_NOT_QUALIFIED",
        "closes_blocker": False,
        "observed_at_main_sha": base_main,
        "sealed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "executed_command": "python3 scripts/qualification/verify_external_staging.py --seal-runbook",
        "mode": "C",
        "host_kind": "runbook_only",
        "why_mode_c": (
            "aucun hôte de staging séparé n'est désigné dans le dépôt, et l'accès SSH à nexus-prod "
            "n'est pas autorisé ; aucun corpus servable ni base vectorielle de staging n'existe sur le "
            "poste de travail : démarrer localement aurait exigé de fabriquer ces faits"
        ),
        "environment_started": False,
        "distinct_from_production": None,
        "runbook": {"path": RUNBOOK, "sha256": hashlib.sha256(runbook.encode()).hexdigest()},
        "compose": {"path": COMPOSE, "sha256": hashlib.sha256(texte.encode()).hexdigest(), **resolu},
        "services": resolu.get("services", []),
        "variables_required_names_only": requises,
        "variables_with_default_names_only": optionnelles,
        "secrets_material_producer": PRODUCTEUR_SECRETS,
        "operator_must_provide": [
            "hôte Ubuntu 22.04/24.04 avec Docker, distinct de la production effective",
            "nom DNS de staging et certificat TLS ; reverse proxy devant 127.0.0.1:${INGESTOR_PORT}",
            "Basic Auth ou allowlist IP sur le reverse proxy",
            "image ingestor par digest (le Compose la construit : à figer avant staging)",
            "répertoire de corpus servables et empreinte de son index",
            "empreinte du registre de releases servi",
            "artefacts de modèles vérifiés (E5, reranker) et leurs empreintes d'inventaire",
        ],
        "storage_expected": {
            "named_volumes": resolu.get("named_volumes", []),
            "database": "PostgreSQL + pgvector DISTINCT de la production, sur son propre volume",
            "read_only_mounts": ["configs", "release registry", "servable corpus", "api-clients.json", "models"],
        },
        "exposure": {"public_unauthenticated": None, "access_control": None,
                     "design": "conteneurs liés à 127.0.0.1 ; TLS et contrôle d'accès au reverse proxy"},
        "rollback": {
            "documented": "## 8. Rollback du staging" in runbook,
            "exercised": False,
            "note": "le rollback de RELEASE est éprouvé par ailleurs (blocage ROLLBACK, rehearsal Docker V2)",
        },
        "healthchecks": {
            "pgvector": None, "api": None, "cockpit": None,
            "defined_in_compose": ["pgvector: /docker-entrypoint-healthcheck.sh", "ingestor: GET /health"],
        },
        "ingestion": {"index_present": None, "vectors": None},
        "retrieval_smoke": {"executed": False, "passed": None, "citations": None, "tool": RECETTE},
        "cockpit_smoke": {"executed": False, "passed": None},
        "logs_secret_scan": {"executed": False, "secrets_found": None},
        "local_checks_really_done": {
            "compose_resolves_with_placeholder_values": resolu.get("resolves"),
            "all_ports_bound_to_loopback": resolu.get("all_ports_bound_to_loopback"),
            "containers_started": 0,
        },
        "secret_exposed": False,
        "secret_values_in_proof": 0,
        "production_db_writes": 0,
        "production_deployments": 0,
        "current_switch": 0,
    }
    octets = (json.dumps(preuve, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    (RACINE / blocages.STAGING_PREUVE).write_bytes(octets)
    (RACINE / blocages.STAGING_PREUVE_SHA).write_text(
        f"{hashlib.sha256(octets).hexdigest()}  {blocages.STAGING_PREUVE}\n", encoding="utf-8"
    )
    print(json.dumps({"verification_status": preuve["verification_status"],
                      "compose": {k: resolu.get(k) for k in ("resolves", "services", "ports", "cpu_limits")},
                      "variables_required": len(requises)}, indent=2, ensure_ascii=False))
    return 0 if resolu.get("resolves") else 1


def verifier_seulement() -> int:
    etat = blocages.verifier_staging_externe(RACINE)
    if etat["closed"]:
        print("STAGING_EXTERNE : preuve scellée valide")
        return 0
    print(f"REFUS : {etat['why']}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seal-runbook", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    return sceller_runbook() if args.seal_runbook else verifier_seulement()


if __name__ == "__main__":
    raise SystemExit(main())
