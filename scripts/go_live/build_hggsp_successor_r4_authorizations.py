#!/usr/bin/env python3
"""Dérive les deux autorisations r4 HGGSP de la release scellée.

Les dimensions d'accès viennent des politiques HGGSP déjà gouvernées ; les
subjects, contenus et programmes viennent de la release successeur scellée.
Les scopes runtime sont déjà gouvernés par #269 et ne sont pas réécrits ici.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
for package in ("contracts", "release-chain", "pdf-page-policy"):
    sys.path.insert(0, str(ROOT / f"packages/{package}/src"))

from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: E402

RELEASE_ID = "production-profile-gate-2026-2027-v5-hggsp"
RELEASE_DIR = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate"
)
MANIFEST_SHA256 = "8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf"
MIXED_REGISTRY = "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
MIXED_REGISTRY_SHA256 = "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6"
PROFILE_FINGERPRINT = "763c2ad15b935a671725b1a3b829d3326ca65d016129e77cf5a71c5ebbc568b9"
PROFILES = "services/rag-engine/configs/ingestion_profiles/v3_livraison_315"
PROGRAMME_REGISTRY = f"{RELEASE_DIR}/programme_registry.json"
POLICY = "docs/governance/retrieval_scope_policy_registry_v4.yml"
AUTH_DIR = "governance/authorizations"
COLLECTIONS = (
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hggsp_terminale_specialite",
)
VALID_FROM = "2026-09-28T00:00:00.000000Z"


class ScopeRefuse(ValueError):
    """Les entrées scellées ne désignent pas le successeur exact."""


def _sha(root: Path, relative: str) -> str:
    return hashlib.sha256((root / relative).read_bytes()).hexdigest()


def _facts(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if _sha(root, f"{RELEASE_DIR}/production-profile-gate.release.json") != MANIFEST_SHA256:
        raise ScopeRefuse("manifeste HGGSP successeur altéré")
    if _sha(root, MIXED_REGISTRY) != MIXED_REGISTRY_SHA256:
        raise ScopeRefuse("registre mixte altéré")
    release = json.loads((root / RELEASE_DIR / "production-profile-gate.release.json").read_text())
    mixed = json.loads((root / MIXED_REGISTRY).read_text())
    if release["release_id"] != RELEASE_ID or {x["collection"] for x in release["subjects"]} != set(COLLECTIONS):
        raise ScopeRefuse("release HGGSP hors des deux collections")
    owner = next((entry for entry in mixed["releases"] if entry["release_id"] == RELEASE_ID), None)
    if owner is None or set(owner["collections"]) != set(COLLECTIONS) or owner["expected_manifest_sha256"] != MANIFEST_SHA256:
        raise ScopeRefuse("registre mixte sans propriété HGGSP exacte")
    policy = yaml.safe_load((root / POLICY).read_text())
    return release, mixed, policy


def _names(collection: str) -> tuple[str, str, str]:
    if collection not in COLLECTIONS:
        raise ScopeRefuse(f"collection hors successeur : {collection}")
    subject = collection.removeprefix("rag_nexus_").replace("_", "-")
    token = collection.removeprefix("rag_nexus_")
    return (f"lot41a-staging-v5-{subject}-r4", f"prod_{token}_v3", f"prod_{token}_v2")


def registre_scopes(root: Path) -> dict[str, Any]:
    release, _mixed, policy = _facts(root)
    programmes = json.loads((root / PROGRAMME_REGISTRY).read_text())
    programmes_par_collection = {entry["collection"]: entry["programme_version"] for entry in programmes["taxonomies"]}
    policies = {entry["collection"]: entry for entry in policy["collections"]}
    bindings = []
    for subject in sorted(release["subjects"], key=lambda x: x["collection"]):
        collection = subject["collection"]
        _auth_id, scope_id, v4_scope = _names(collection)
        if collection not in policies or collection not in programmes_par_collection:
            raise ScopeRefuse(f"politique ou programme absent : {collection}")
        if policies[collection]["programme_version"] != programmes_par_collection[collection]:
            raise ScopeRefuse(f"programme divergent : {collection}")
        bindings.append({"collection": collection, "scope_id": scope_id,
                         "predecessor_scope_id": v4_scope, "subject_sha256": subject["sha256"]})
    return {"release_id": RELEASE_ID, "bindings": bindings}


def construire(root: Path) -> dict[str, dict[str, Any]]:
    from nexus_release_chain.ingestion_profiles.registry import load_profile_registry, profile_fingerprint

    release, _mixed, policy = _facts(root)
    profiles = {p.scope.collection: p for p in load_profile_registry(root / PROFILES).values()}
    policies = {entry["collection"]: entry for entry in policy["collections"]}
    documents = {}
    for subject in sorted(release["subjects"], key=lambda x: x["collection"]):
        collection = subject["collection"]
        auth_id, _scope_id, _old = _names(collection)
        old_path = root / AUTH_DIR / f"lot41a-staging-v2-{collection.removeprefix('rag_nexus_').replace('_', '-')}-r2.json"
        old = json.loads(old_path.read_text())
        profile = profiles[collection]
        governed = profile.scope.model_dump(mode="json")
        governed["audience"] = sorted(governed["audience"])
        scope = {key: governed[key] for key in old["scope"]}
        expected = policies[collection]
        if scope["programme_version"] != expected["programme_version"] or scope["collection"] != collection:
            raise ScopeRefuse(f"scope non gouverné : {collection}")
        subject_doc = json.loads((root / RELEASE_DIR / subject["path"]).read_text())
        content = sorted({str(p["artifact_id"]) for p in subject_doc["placements"]})
        document = {
            **{key: old[key] for key in ("allowed_domains", "decision", "exclusions", "profile_id", "rights_categories", "valid_until")},
            "authorization_id": auth_id,
            "allowed_content_sha256": content,
            "profile_fingerprint": profile_fingerprint(profile),
            "profile_version": profile.profile_version,
            "scope": scope,
            "manifest_digest": PROFILE_FINGERPRINT,
            "pii_absence_attested": True,
            "pii_absence_evidence": f"{RELEASE_DIR}/pii_evidence.json@sha256:{release['authorities']['pii_evidence_sha256']}",
            "protocol_version": "LOT41A-V2",
            "valid_from": VALID_FROM,
        }
        ScopeAuthorizationArtifactV2.model_validate(document)
        documents[auth_id] = document
    if len(documents) != 2:
        raise ScopeRefuse("deux autorités HGGSP attendues")
    return documents




def verifier_fichiers(root: Path) -> list[str]:
    # Les deux scopes image sont produits et validés par le producteur de #269.
    from nexus_contracts import load_retrieval_scope_registry  # noqa: PLC0415

    derived = construire(root)
    ids = sorted(derived)
    expected_scopes = {binding["scope_id"] for binding in registre_scopes(root)["bindings"]}
    installed_scopes = load_retrieval_scope_registry()
    if len(expected_scopes) != 2 or not expected_scopes.issubset(installed_scopes):
        raise ScopeRefuse("scope runtime #269 divergent")
    for auth_id, document in derived.items():
        path = root / AUTH_DIR / f"{auth_id}.json"
        artifact = ScopeAuthorizationArtifactV2.model_validate(document)
        if not path.is_file() or path.read_bytes() != artifact.canonical_bytes():
            raise ScopeRefuse(f"autorité r4 divergente : {path}")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--ids", action="store_true")
    args = parser.parse_args()
    try:
        if args.check or args.ids:
            ids = verifier_fichiers(ROOT)
            if args.ids:
                print(" ".join(ids))
        else:
            for auth_id, document in construire(ROOT).items():
                artifact = ScopeAuthorizationArtifactV2.model_validate(document)
                (ROOT / AUTH_DIR / f"{auth_id}.json").write_bytes(artifact.canonical_bytes())
    except (ScopeRefuse, KeyError, ValueError, OSError) as exc:
        print(f"HGGSP_R4_REFUSE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
