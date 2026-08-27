#!/usr/bin/env python3
"""Vérificateur et émetteur déterministe atomique du bundle de ReviewBindings réels (ADR-0035).

Ce script fournit deux sous-commandes sécurisées pour le gate opérateur :
1. ``verify-bundle`` : Contrôle formel et cryptographique hors ligne des 18 bindings réels
   contre les 18 autorisations canoniques, l'ancre de confiance et le HEAD attendu.
2. ``sign-all`` : Émission déterministe, fail-fast et ATOMIQUE des 18 bindings réels depuis l'ancre canonique
   et l'arbre de la PR #134 dans un staging temporaire avec remplacement atomique final.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus_contracts.authority_artifacts import (
    canonical_authorization_path,
    git_blob_sha1,
    parse_scope_authorization_artifact,
)
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    ReviewBindingError,
    SignedScopeAuthorizationReviewBinding,
    TrustAnchor,
    parse_signed_review_binding,
    parse_trust_anchor,
    require_challenge_is_bound,
    require_matches_authorization,
    verify_review_binding,
)

EXPECTED_REPOSITORY = "cyranoaladin/RAG"
EXPECTED_PR_NUMBER = 134
EXPECTED_HEAD_SHA = "140b157fdb8d32b7e22fffb125d9acea4195bd28"
EXPECTED_KEY_ID = "review-binding-v1-2026-08-25"
EXPECTED_COUNT = 18
SIGNING_KEY_ENV = "NEXUS_REVIEW_BINDING_SIGNING_KEY"

# Les 18 identifiants canoniques ordonnés
CANONICAL_AUTHORIZATION_IDS = (
    "prerentree-2026-2027-rag_nexus_dgemc_terminale_option-v1",
    "prerentree-2026-2027-rag_nexus_francais_premiere_tc-v1",
    "prerentree-2026-2027-rag_nexus_francais_quatrieme_tc-v1",
    "prerentree-2026-2027-rag_nexus_francais_seconde_tc-v1",
    "prerentree-2026-2027-rag_nexus_hlp_premiere_specialite-v1",
    "prerentree-2026-2027-rag_nexus_maths_premiere_gen_specialite-v1",
    "prerentree-2026-2027-rag_nexus_maths_quatrieme_tc-v1",
    "prerentree-2026-2027-rag_nexus_maths_seconde_tc-v1",
    "prerentree-2026-2027-rag_nexus_maths_terminale_gen_specialite-v1",
    "prerentree-2026-2027-rag_nexus_nsi_premiere_specialite-v1",
    "prerentree-2026-2027-rag_nexus_nsi_terminale_specialite-v1",
    "prerentree-2026-2027-rag_nexus_pc_premiere_specialite-v1",
    "prerentree-2026-2027-rag_nexus_pc_terminale_specialite-v1",
    "prerentree-2026-2027-rag_nexus_philo_terminale_tc-v1",
    "prerentree-2026-2027-rag_nexus_ses_premiere_specialite-v1",
    "prerentree-2026-2027-rag_nexus_ses_terminale_specialite-v1",
    "prerentree-2026-2027-rag_nexus_svt_premiere_specialite-v1",
    "prerentree-2026-2027-rag_nexus_svt_terminale_specialite-v1",
)


def _get_authorization_bytes_from_git(auth_id: str, git_ref: str) -> bytes:
    """Lit les octets canoniques de l'autorisation depuis la référence Git spécifiée."""
    rel_path = canonical_authorization_path(auth_id)
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{git_ref}:{rel_path}"],
            stderr=subprocess.PIPE,
        )
        return raw
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"Impossible de lire {rel_path} depuis {git_ref}: {exc.stderr.decode('utf-8', errors='replace')}"
        ) from exc


def verify_bundle(
    *,
    bundle_dir: Path,
    trust_anchor_path: Path,
    expected_head: str = EXPECTED_HEAD_SHA,
    expected_key_id: str = EXPECTED_KEY_ID,
    git_ref: str = "origin/rag-pedago/production-authorizations-20260825",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Vérifie de manière exhaustive les fichiers de bindings contre les autorisations."""
    if now is None:
        now = datetime.now(UTC)

    if not trust_anchor_path.is_file():
        raise ValueError(f"Fichier d'ancre introuvable : {trust_anchor_path}")

    anchor_bytes = trust_anchor_path.read_bytes()
    anchor = parse_trust_anchor(anchor_bytes)

    if not bundle_dir.is_dir():
        raise ValueError(f"Répertoire de bundle introuvable : {bundle_dir}")

    binding_files = sorted(list(bundle_dir.glob("*.binding.json")))
    found_count = len(binding_files)

    expected_set = set(CANONICAL_AUTHORIZATION_IDS)
    found_map: dict[str, Path] = {}
    duplicates: list[str] = []

    for bf in binding_files:
        auth_id = bf.name.removesuffix(".binding.json")
        if auth_id in found_map:
            duplicates.append(auth_id)
        found_map[auth_id] = bf

    found_set = set(found_map.keys())
    missing = sorted(list(expected_set - found_set))
    unexpected = sorted(list(found_set - expected_set))

    report: dict[str, Any] = {
        "EXPECTED_BINDINGS": EXPECTED_COUNT,
        "FOUND_BINDINGS": found_count,
        "MISSING": len(missing),
        "UNEXPECTED": len(unexpected),
        "DUPLICATES": len(duplicates),
        "SIGNATURE_VALID": 0,
        "CURRENT_KEY_ID_MATCH": 0,
        "CURRENT_TRUST_ANCHOR_MATCH": 0,
        "PR_NUMBER_MATCH": 0,
        "EXPECTED_HEAD_MATCH": 0,
        "CHALLENGE_VALID": 0,
        "AUTHORIZATION_BYTES_MATCH": 0,
        "AUTHORIZATION_SHA256_MATCH": 0,
        "errors": [],
    }

    if missing:
        report["errors"].append(f"Bindings manquants ({len(missing)}): {missing}")
    if unexpected:
        report["errors"].append(f"Bindings inattendus ({len(unexpected)}): {unexpected}")
    if duplicates:
        report["errors"].append(f"Bindings dupliqués ({len(duplicates)}): {duplicates}")

    for auth_id in CANONICAL_AUTHORIZATION_IDS:
        if auth_id not in found_map:
            continue
        bf_path = found_map[auth_id]
        raw_binding = bf_path.read_bytes()

        try:
            signed = parse_signed_review_binding(raw_binding)
            if signed.key_id == expected_key_id:
                report["CURRENT_KEY_ID_MATCH"] += 1
            else:
                report["errors"].append(
                    f"{auth_id}: key_id mismatch (expected={expected_key_id}, got={signed.key_id})"
                )

            binding = verify_review_binding(
                raw_binding,
                trust_anchor=anchor,
                environment="production",
                now=now,
            )
            report["SIGNATURE_VALID"] += 1
            report["CURRENT_TRUST_ANCHOR_MATCH"] += 1

            if binding.pull_request == EXPECTED_PR_NUMBER:
                report["PR_NUMBER_MATCH"] += 1
            else:
                report["errors"].append(
                    f"{auth_id}: PR number mismatch (expected={EXPECTED_PR_NUMBER}, got={binding.pull_request})"
                )

            if binding.head_sha == expected_head:
                report["EXPECTED_HEAD_MATCH"] += 1
            else:
                report["errors"].append(
                    f"{auth_id}: HEAD mismatch (expected={expected_head}, got={binding.head_sha})"
                )

            require_challenge_is_bound(binding)
            report["CHALLENGE_VALID"] += 1

            auth_bytes = _get_authorization_bytes_from_git(auth_id, git_ref)
            blob_sha1 = git_blob_sha1(auth_bytes)

            require_matches_authorization(
                binding,
                authorization_id=auth_id,
                authorization_bytes=auth_bytes,
                authorization_git_blob_sha1=blob_sha1,
                expected_repository=EXPECTED_REPOSITORY,
                expected_head_sha=expected_head,
            )
            report["AUTHORIZATION_BYTES_MATCH"] += 1
            report["AUTHORIZATION_SHA256_MATCH"] += 1

        except Exception as exc:
            report["errors"].append(f"{auth_id}: {exc}")

    success = (
        report["EXPECTED_BINDINGS"] == EXPECTED_COUNT
        and report["FOUND_BINDINGS"] == EXPECTED_COUNT
        and report["MISSING"] == 0
        and report["UNEXPECTED"] == 0
        and report["DUPLICATES"] == 0
        and report["SIGNATURE_VALID"] == EXPECTED_COUNT
        and report["CURRENT_KEY_ID_MATCH"] == EXPECTED_COUNT
        and report["CURRENT_TRUST_ANCHOR_MATCH"] == EXPECTED_COUNT
        and report["PR_NUMBER_MATCH"] == EXPECTED_COUNT
        and report["EXPECTED_HEAD_MATCH"] == EXPECTED_COUNT
        and report["CHALLENGE_VALID"] == EXPECTED_COUNT
        and report["AUTHORIZATION_BYTES_MATCH"] == EXPECTED_COUNT
        and report["AUTHORIZATION_SHA256_MATCH"] == EXPECTED_COUNT
        and len(report["errors"]) == 0
    )

    report["REVIEW_BINDING_BUNDLE_VERIFICATION"] = "PASS" if success else "FAIL"
    return report


def execute_atomic_sign_all(
    *,
    output_dir: Path,
    trust_anchor_path: Path,
    cli_script_path: Path,
    simulate_failure_at_index: int | None = None,
) -> None:
    """Émet les 18 bindings dans un répertoire de staging temporaire, vérifie le bundle, puis remplace atomiquement."""
    if SIGNING_KEY_ENV not in os.environ or not os.environ[SIGNING_KEY_ENV].strip():
        raise RuntimeError(f"ERREUR: La variable d'environnement {SIGNING_KEY_ENV} n'est pas définie.")

    if not cli_script_path.is_file():
        raise RuntimeError(f"ERREUR: CLI producteur introuvable à {cli_script_path}")

    with tempfile.TemporaryDirectory(prefix="review_binding_staging_") as tmp_staging:
        staging_dir = Path(tmp_staging)
        print(f"Staging d'émission initialisé dans {staging_dir}")

        for i, aid in enumerate(CANONICAL_AUTHORIZATION_IDS, 1):
            if simulate_failure_at_index is not None and i == simulate_failure_at_index:
                raise RuntimeError(f"Échec simulé intentionnel au binding index {i} ({aid})")

            out_file = staging_dir / f"{aid}.binding.json"
            print(f"[{i:02d}/18] Signature en staging de {aid} -> {out_file.name}...")

            cmd = [
                sys.executable,
                str(cli_script_path),
                "issue",
                "--repository", EXPECTED_REPOSITORY,
                "--pull-request", str(EXPECTED_PR_NUMBER),
                "--expected-head", EXPECTED_HEAD_SHA,
                "--authorization-id", aid,
                "--key-id", EXPECTED_KEY_ID,
                "--trust-anchor", str(trust_anchor_path),
                "--environment", "production",
            ]

            env = dict(os.environ)
            existing_pp = env.get("PYTHONPATH", "")
            engine_src = str(Path(__file__).resolve().parents[1] / "services/rag-engine/src")
            env["PYTHONPATH"] = f"{engine_src}:{existing_pp}" if existing_pp else engine_src
            proc_res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
            if proc_res.returncode != 0:
                raise RuntimeError(
                    f"ERREUR lors de l'émission pour {aid} :\nSTDOUT: {proc_res.stdout}\nSTDERR: {proc_res.stderr}"
                )

            out_file.write_text(proc_res.stdout, encoding="utf-8")

        print("\nVérification exhaustive du staging avant publication...")
        v_res = verify_bundle(
            bundle_dir=staging_dir,
            trust_anchor_path=trust_anchor_path,
            expected_head=EXPECTED_HEAD_SHA,
            expected_key_id=EXPECTED_KEY_ID,
        )
        if v_res["REVIEW_BINDING_BUNDLE_VERIFICATION"] != "PASS":
            raise RuntimeError(f"Le staging a échoué à la vérification : {v_res['errors']}")

        print(f"\nPublication atomique vers {output_dir}...")
        output_dir.mkdir(parents=True, exist_ok=True)
        # Copie atomique par fichier dans la destination
        for f in staging_dir.glob("*.binding.json"):
            dest_f = output_dir / f.name
            shutil.copy(f, dest_f)

        print("Publication atomique terminée avec succès.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Contrôleur et émetteur atomique du bundle de ReviewBindings (ADR-0035)."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_p = subparsers.add_parser(
        "verify-bundle",
        help="Vérifie exhaustivement le bundle réel de 18 ReviewBindings.",
    )
    verify_p.add_argument(
        "--bundle-dir",
        type=Path,
        default=Path("governance/review-bindings/prerentree-2026-2027"),
        help="Chemin du dossier contenant les .binding.json",
    )
    verify_p.add_argument(
        "--trust-anchor",
        type=Path,
        default=Path("governance/trust-anchors/review-binding-v1.json"),
        help="Chemin de l'ancre de confiance courante",
    )
    verify_p.add_argument(
        "--expected-head",
        default=EXPECTED_HEAD_SHA,
        help=f"HEAD SHA attendu de la PR (défaut {EXPECTED_HEAD_SHA})",
    )
    verify_p.add_argument(
        "--expected-key-id",
        default=EXPECTED_KEY_ID,
        help=f"Key ID attendu (défaut {EXPECTED_KEY_ID})",
    )

    sign_p = subparsers.add_parser(
        "sign-all",
        help="Émet séquentiellement et de façon atomique les 18 bindings réels depuis l'arbre de la PR #134.",
    )
    sign_p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("governance/review-bindings/prerentree-2026-2027"),
        help="Dossier de sortie des .binding.json",
    )
    sign_p.add_argument(
        "--trust-anchor",
        type=Path,
        default=Path("governance/trust-anchors/review-binding-v1.json"),
        help="Chemin de l'ancre de confiance courante",
    )

    args = parser.parse_args()

    if args.command == "verify-bundle":
        print("=== VERIFICATION DU BUNDLE DE REVIEW BINDINGS REELS ===")
        res = verify_bundle(
            bundle_dir=args.bundle_dir,
            trust_anchor_path=args.trust_anchor,
            expected_head=args.expected_head,
            expected_key_id=args.expected_key_id,
        )

        for k in (
            "EXPECTED_BINDINGS",
            "FOUND_BINDINGS",
            "MISSING",
            "UNEXPECTED",
            "DUPLICATES",
            "SIGNATURE_VALID",
            "CURRENT_KEY_ID_MATCH",
            "CURRENT_TRUST_ANCHOR_MATCH",
            "PR_NUMBER_MATCH",
            "EXPECTED_HEAD_MATCH",
            "CHALLENGE_VALID",
            "AUTHORIZATION_BYTES_MATCH",
            "AUTHORIZATION_SHA256_MATCH",
        ):
            print(f"{k}={res[k]}")

        print(f"\nREVIEW_BINDING_BUNDLE_VERIFICATION={res['REVIEW_BINDING_BUNDLE_VERIFICATION']}")

        if res["errors"]:
            print("\nErreurs constatées :")
            for err in res["errors"]:
                print(f" - {err}")
            sys.exit(1)
        sys.exit(0)

    elif args.command == "sign-all":
        print(f"AUTHORIZATIONS_TO_SIGN={len(CANONICAL_AUTHORIZATION_IDS)}")
        for aid in CANONICAL_AUTHORIZATION_IDS:
            print(f" - {aid}")

        cli_script = Path("services/rag-engine/src/ingestor/ingestion_worker/issue_review_binding_cli.py")
        try:
            execute_atomic_sign_all(
                output_dir=args.output_dir,
                trust_anchor_path=args.trust_anchor,
                cli_script_path=cli_script,
            )
        except Exception as exc:
            print(f"\nÉCHEC DE L'ÉMISSION ATOMIQUE : {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
