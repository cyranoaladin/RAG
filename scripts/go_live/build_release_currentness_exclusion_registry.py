#!/usr/bin/env python3
"""Générateur du registre gouverné d'exclusion d'actualité pour la release promue (Lot CF).

Fondé strictement sur l'ADR-0055 et la matrice de servabilité post-CE.
Ce registre scelle la liste exacte des 4 contenus d'archives déclarées par la source
qui doivent être exclus lors du rescellement de release V2 (Lot CG).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

KIND = "NEXUS-CURRENTNESS-EXCLUSION-REGISTRY-V1"
SCHEMA_VERSION = "1.0.0"

MATRICE_REL = "docs/reports/handoff/servability_matrix_v1.json"
CALCULATEUR_PROMU_REL = "scripts/qualification/compute_promoted_content_set.py"
DECISIONS_PII_REL = "governance/pii-review-decisions/pii-review-2026-09-17-final.json"

TARGET_ARCHIVES = (
    {
        "content_sha256": "157309db13b674ffe4bf1371015bfc7c9c9cf475af75769a6beaf4dade45925f",
        "title": "la définition des épreuves anticipées de français du baccalauréat général et technologique",
        "label": "Archive Eduscol 2024 / EAF",
        "expected_pii": "PII_CLEARED",
    },
    {
        "content_sha256": "174f273ff25818064be60cd4c7cded89ab8f257de484b32a21250578f323149b",
        "title": "glossaire",
        "label": "Archive Eduscol DGEMC",
        "expected_pii": "PII_CLEARED_OR_NOT_SCANNED",
    },
    {
        "content_sha256": "ccffe628bbd64e34a8442a045f95ec2ef65109765c0a0a476c0156aa84a5f9a2",
        "title": "pour la voie technologique",
        "label": "Archive Eduscol SVT voie technologique",
        "expected_pii": "PII_CLEARED_OR_NOT_SCANNED",
    },
    {
        "content_sha256": "dc58fcc42ef9b4e6d15a129124eff54ce5d76e0e16e1e4f62115b64482e94fd2",
        "title": "pour la voie générale",
        "label": "Archive Eduscol SVT voie générale",
        "expected_pii": "PII_CLEARED_OR_NOT_SCANNED",
    },
)


def repo_root() -> Path:
    override = os.environ.get("NEXUS_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def load_promoted_contents(root: Path) -> set[str]:
    calc_path = root / CALCULATEUR_PROMU_REL
    if not calc_path.is_file():
        raise RuntimeError(f"calculateur promu introuvable: {calc_path}")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        res = subprocess.run(
            [sys.executable, str(calc_path), "--output", tmp.name],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(f"échec compute_promoted_content_set: {res.stderr}")
        data = json.loads(Path(tmp.name).read_text(encoding="utf-8"))
        return set(data["content_sha256"])


def build_exclusion_registry(root: Path) -> dict:
    mat_path = root / MATRICE_REL
    if not mat_path.is_file():
        raise RuntimeError(f"matrice introuvable: {mat_path}")
    mat_bytes = mat_path.read_bytes()
    mat_sha = hashlib.sha256(mat_bytes).hexdigest()
    mat = json.loads(mat_bytes.decode("utf-8"))

    pii_path = root / DECISIONS_PII_REL
    if not pii_path.is_file():
        raise RuntimeError(f"décisions PII introuvables: {pii_path}")
    pii_bytes = pii_path.read_bytes()
    pii_sha = hashlib.sha256(pii_bytes).hexdigest()

    promoted_shas = load_promoted_contents(root)
    rows_by_sha = {r["content_sha256"]: r for r in mat["rows"]}

    # Vérification stricte des bloqueurs PII dans la matrice
    pii_undecided = mat.get("by_pii", {}).get("PII_UNDECIDED", 0)
    if pii_undecided != 0:
        raise ValueError(f"PII_UNDECIDED doit être 0, observé: {pii_undecided}")

    excluded_entries = []
    target_shas = {t["content_sha256"] for t in TARGET_ARCHIVES}

    for target in TARGET_ARCHIVES:
        sha = target["content_sha256"]
        row = rows_by_sha.get(sha)
        if not row:
            raise ValueError(f"contenu cible absent de la matrice: {sha}")
        if sha not in promoted_shas:
            raise ValueError(f"contenu cible absent de l'ensemble promu: {sha}")
        if row.get("currentness") != "ARCHIVE_DECLARED":
            raise ValueError(f"currentness invalide pour {sha}: {row.get('currentness')}")
        if row.get("verdict") != "BLOCKED_NOT_CURRENT_BY_SOURCE":
            raise ValueError(f"verdict invalide pour {sha}: {row.get('verdict')}")
        if row.get("pii") != target["expected_pii"]:
            raise ValueError(f"statut PII inattendu pour {sha}: {row.get('pii')} != {target['expected_pii']}")

        excluded_entries.append({
            "content_sha256": sha,
            "short_sha": sha[:12],
            "label": target["label"],
            "title": target["title"],
            "currentness_status": row["currentness"],
            "servability_verdict": row["verdict"],
            "pii_status": row["pii"],
            "is_promoted": True,
            "exclusion_reason": "ARCHIVE_DECLARED_BY_SOURCE_ADR_0055",
        })

    # Vérifier qu'aucun autre contenu de la release promue n'est refusé par currentness
    promoted_currentness_refusals = {
        sha for sha in promoted_shas
        if rows_by_sha.get(sha, {}).get("verdict") == "BLOCKED_NOT_CURRENT_BY_SOURCE"
    }
    if promoted_currentness_refusals != target_shas:
        raise ValueError(
            f"discordance sur les refus d'actualité promus: "
            f"observés {len(promoted_currentness_refusals)} vs cibles {len(target_shas)}"
        )

    registry = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "governance_reference": "ADR-0055",
        "purpose": (
            "Sceller la liste gouvernée des 4 contenus archives Eduscol exclus "
            "de la prochaine release promue (Lot CG), conformément à l'ADR-0055."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "excluded_contents_count": len(excluded_entries),
        "excluded_contents": excluded_entries,
        "proof_guarantees": {
            "all_excluded_contents_promoted": True,
            "all_excluded_contents_blocked_by_currentness": True,
            "canonical_verdict": "BLOCKED_NOT_CURRENT_BY_SOURCE",
            "no_other_contents_excluded": True,
            "no_pii_decisions_reinterpreted": True,
            "pii_undecided_count": 0,
            "governance_basis": "ADR-0055",
            "historical_v1_immutable": True,
        },
        "authorities": {
            "servability_matrix": {
                "path": MATRICE_REL,
                "sha256": mat_sha,
            },
            "pii_decisions": {
                "path": DECISIONS_PII_REL,
                "sha256": pii_sha,
            },
        },
    }
    return registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="docs/reports/evidence/release_currentness_exclusion_registry.json",
        help="Chemin de sortie du registre d'exclusion",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    registry = build_exclusion_registry(root)

    out_path = root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(registry, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    out_path.write_text(serialized, encoding="utf-8")

    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    sha_path = out_path.with_suffix(".sha256")
    sha_path.write_text(f"{digest}  {out_path.name}\n", encoding="utf-8")

    print(f"REGISTRY_WRITTEN={out_path}")
    print(f"REGISTRY_SHA256={digest}")
    print(f"EXCLUDED_COUNT={registry['excluded_contents_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
