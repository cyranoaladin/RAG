#!/usr/bin/env python3
"""Signer et vérifier localement la readiness distincte du complément HGGSP.

Le premier fichier est le manifeste V1 consommé par les workers existants. Le
second est une liaison Ed25519 au premier, aux deux images et au périmètre
mixte. Les deux sont requis ; aucun fichier V4 ne satisfait cette liaison.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/contracts/src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: E402
from nexus_contracts.staging_readiness import (  # type: ignore[import-untyped]  # noqa: E402
    StagingReadinessManifestV1,
    parse_staging_readiness_trust_anchor,
    sign_staging_readiness_manifest,
    verify_staging_readiness_manifest,
)

RELEASE_ID = "production-profile-gate-2026-2027-v5-hggsp"
MANIFEST_SHA256 = "8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf"
MIXED_REGISTRY_SHA256 = "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6"
WORKER_IMAGE = "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:2228650e2245ea2fdc45d442a78363fd362781c2f80e2270618eedca0abf9bcf"
RETRIEVAL_IMAGE = "ghcr.io/cyranoaladin/rag-ingestor@sha256:11aa98d58ebcd10ee09543d4791f63b67542b764ab0484f004cccc8d43e86caf"
SOURCE_COMMIT = "a9e3701965503d2862a248c46fd7e7e175058c8f"
DATABASE = "ragdb_profile_gate_v4"
COLLECTIONS = (
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hggsp_terminale_specialite",
)
MANIFEST_PATH = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate/production-profile-gate.release.json"
)
REGISTRY_PATH = "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
AUTH_PATH = "docs/reports/go_live/authorizations/staging_hggsp_complementary_authorization.json"
ANCHOR_PATH = "governance/trust-anchors/rehearsal-readiness-v1.json"
KEY_ID = "nexus-rehearsal-readiness-20260920-01"
V1_NAME = "staging-readiness-hggsp-successor.json"
BINDING_NAME = "staging-readiness-hggsp-successor-binding.json"
BINDING_PROTOCOL = "NEXUS-STAGING-HGGSP-SUCCESSOR-READINESS-BINDING-V1"


class ReadinessRefuse(ValueError):
    """Aucune partie de la readiness n'est autoritaire si une liaison échoue."""


def _canonical(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _expected(v1_raw: bytes) -> dict[str, Any]:
    return {
        "protocol": BINDING_PROTOCOL,
        "repository": "cyranoaladin/RAG",
        "source_commit": SOURCE_COMMIT,
        "release_id": RELEASE_ID,
        "manifest_sha256": MANIFEST_SHA256,
        "worker_image": WORKER_IMAGE,
        "retrieval_image": RETRIEVAL_IMAGE,
        "database": DATABASE,
        "collections": list(COLLECTIONS),
        "mixed_registry_sha256": MIXED_REGISTRY_SHA256,
        "staging_readiness_sha256": hashlib.sha256(v1_raw).hexdigest(),
    }


def sign_bundle(*, seed: str, key_id: str, issued_at: datetime) -> tuple[bytes, bytes]:
    """Construit deux fichiers signés, sans lire ni écrire de graine."""
    if key_id != KEY_ID or not re.fullmatch(r"[0-9a-f]{64}", seed):
        raise ReadinessRefuse("clé de readiness HGGSP invalide")
    manifest = StagingReadinessManifestV1(
        protocol_version="NEXUS-STAGING-READINESS-V1",
        environment="rehearsal", repository="cyranoaladin/RAG",
        merge_sha=SOURCE_COMMIT, worker_image=WORKER_IMAGE,
        allowed_release_id=RELEASE_ID, allowed_release_manifest_sha256=MANIFEST_SHA256,
        control_dsn_differs_from_product=True, key_id=key_id,
        issued_at=issued_at, expires_at=issued_at + timedelta(days=30),
    )
    signed_v1 = sign_staging_readiness_manifest(manifest, private_key_hex=seed, key_id=key_id)
    v1_raw = (json.dumps(signed_v1.canonical_document(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    binding = _expected(v1_raw)
    signature = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed)).sign(_canonical(binding)).hex()
    binding_raw = (json.dumps({"binding": binding, "key_id": key_id, "signature_algorithm": "ed25519", "signature": signature}, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    return v1_raw, binding_raw


def verify_bundle(v1_raw: bytes, binding_raw: bytes, *, trust_anchor_raw: bytes, now: datetime) -> dict[str, Any]:
    try:
        anchor = parse_staging_readiness_trust_anchor(trust_anchor_raw)
        manifest = verify_staging_readiness_manifest(v1_raw, trust_anchor=anchor, now=now)
        if (manifest.allowed_release_id != RELEASE_ID or manifest.allowed_release_manifest_sha256 != MANIFEST_SHA256
                or manifest.worker_image != WORKER_IMAGE or manifest.merge_sha != SOURCE_COMMIT):
            raise ReadinessRefuse("readiness V1 non successeur HGGSP")
        signed = json.loads(binding_raw)
        if set(signed) != {"binding", "key_id", "signature_algorithm", "signature"}:
            raise ReadinessRefuse("liaison de readiness mal formée")
        binding = signed["binding"]
        if binding != _expected(v1_raw) or signed["key_id"] != manifest.key_id or signed["signature_algorithm"] != "ed25519":
            raise ReadinessRefuse("liaison HGGSP divergente")
        signature = signed["signature"]
        if not isinstance(signature, str) or re.fullmatch(r"[0-9a-f]{128}", signature) is None:
            raise ReadinessRefuse("signature de liaison invalide")
        key = anchor.key(manifest.key_id)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key.public_key)).verify(bytes.fromhex(signature), _canonical(binding))
        return binding
    except ReadinessRefuse:
        raise
    except Exception as exc:
        raise ReadinessRefuse(f"vérification readiness HGGSP refusée : {type(exc).__name__}") from exc


def _authorization_checker(root: Path) -> Any:
    """Charge le contrôleur gouverné du checkout effectivement signé."""
    path = root / "scripts/go_live/check_staging_authorization.py"
    spec = importlib.util.spec_from_file_location("hggsp_staging_authorization", path)
    if spec is None or spec.loader is None:
        raise ReadinessRefuse("contrôleur d'autorisation HGGSP introuvable")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


def _active_authorization(root: Path) -> dict[str, Any]:
    path = root / AUTH_PATH
    if not path.is_file():
        raise ReadinessRefuse("autorisation HGGSP active absente")
    raw = path.read_bytes()
    result = subprocess.run(["git", "show", f"origin/main:{AUTH_PATH}"], cwd=root, capture_output=True, check=False)
    if result.returncode != 0 or result.stdout != raw:
        raise ReadinessRefuse("autorisation HGGSP absente ou divergente de origin/main")
    auth = json.loads(raw)
    if (auth.get("kind") != "NEXUS-STAGING-HGGSP-COMPLEMENTARY-AUTHORIZATION-V1"
            or auth.get("status") != "ACTIVE_AFTER_MERGE"
            or "successor_readiness_sign" not in auth.get("operations", [])):
        raise ReadinessRefuse("autorisation HGGSP inactive ou non canonique")
    release = auth.get("release", {})
    registry = auth.get("collection_ownership_registry", auth.get("mixed_registry", {}))
    worker = auth.get("runtime_image", {})
    retrieval = auth.get("probe_image", auth.get("retrieval_image", {}))
    if (release.get("release_id") != RELEASE_ID
            or release.get("manifest_sha256", release.get("release_manifest_sha256")) != MANIFEST_SHA256
            or registry.get("sha256") != MIXED_REGISTRY_SHA256
            or worker.get("reference") != WORKER_IMAGE
            or retrieval.get("reference") != RETRIEVAL_IMAGE
            or auth.get("targets", {}).get("database") != DATABASE):
        raise ReadinessRefuse("autorisation HGGSP sans les pins de readiness exacts")
    collections = release.get("collections")
    if (not isinstance(collections, list)
            or not all(isinstance(collection, str) for collection in collections)
            or sorted(collections) != sorted(COLLECTIONS)):
        raise ReadinessRefuse("autorisation HGGSP sans les deux collections exactes")
    checker = _authorization_checker(root)
    operation = "successor_readiness_sign"
    try:
        target = checker.OPERATIONS_HGGSP[operation]["cible"]
        errors = checker.verifier_operation_hggsp(root, operation, target)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReadinessRefuse("vérification complète d'autorisation indisponible") from exc
    if errors:
        raise ReadinessRefuse("autorisation ou revue de l'activation refusée : " + "; ".join(errors))
    return auth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sign = sub.add_parser("sign")
    sign.add_argument("--private-key-file", type=Path, required=True)
    sign.add_argument("--output-dir", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _active_authorization(ROOT)
        if hashlib.sha256((ROOT / MANIFEST_PATH).read_bytes()).hexdigest() != MANIFEST_SHA256:
            raise ReadinessRefuse("manifeste scellé divergent")
        if hashlib.sha256((ROOT / REGISTRY_PATH).read_bytes()).hexdigest() != MIXED_REGISTRY_SHA256:
            raise ReadinessRefuse("registre mixte divergent")
        anchor = (ROOT / ANCHOR_PATH).read_bytes()
        if args.command == "sign":
            key_path = args.private_key_file.resolve()
            if key_path.is_relative_to(ROOT) or key_path.stat().st_mode & 0o077:
                raise ReadinessRefuse("graine hors dépôt en mode 0600 requise")
            seed = key_path.read_text().strip()
            v1, binding = sign_bundle(seed=seed, key_id=KEY_ID, issued_at=datetime.now(UTC))
            verify_bundle(v1, binding, trust_anchor_raw=anchor, now=datetime.now(UTC))
            out = args.output_dir.resolve()
            if out.is_relative_to(ROOT):
                raise ReadinessRefuse("sortie signée hors dépôt requise")
            out.mkdir(mode=0o700, parents=True, exist_ok=True)
            if out.stat().st_mode & 0o077:
                raise ReadinessRefuse("répertoire de sortie en mode 0700 requis")
            if (out / V1_NAME).exists() or (out / BINDING_NAME).exists():
                raise ReadinessRefuse("readiness HGGSP déjà présente ; aucun écrasement")
            for name, raw in ((V1_NAME, v1), (BINDING_NAME, binding)):
                fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
            print("HGGSP_SUCCESSOR_READINESS_SIGNED")
        else:
            bundle = args.bundle_dir
            verify_bundle((bundle / V1_NAME).read_bytes(), (bundle / BINDING_NAME).read_bytes(),
                          trust_anchor_raw=anchor, now=datetime.now(UTC))
            print("HGGSP_SUCCESSOR_READINESS_VERIFIED")
    except (ReadinessRefuse, OSError, ValueError, KeyError) as exc:
        print(f"HGGSP_READINESS_REFUSE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
