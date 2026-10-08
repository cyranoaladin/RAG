#!/usr/bin/env python3
"""Reproduit les deux scopes HGGSP avec le producteur canonique gouverné.

La release scellée reste intacte. Le registre de politique externe lie son
manifeste, ses subjects et le registre mixte ; les politiques reprennent V4.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/contracts/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_retrieval_scope_artifacts import emit_from_policy_registry  # noqa: E402
from nexus_contracts.scope import load_retrieval_scope_artifact  # type: ignore[import-untyped]  # noqa: E402

RELEASE_ID = "production-profile-gate-2026-2027-v5-hggsp"
RELEASE_PATH = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate/"
    "production-profile-gate.release.json"
)
RELEASE_SHA256 = "8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf"
MIXED_PATH = "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
MIXED_SHA256 = "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6"
V4_POLICY_PATH = "docs/governance/retrieval_scope_policy_registry_v4.yml"
V4_POLICY_SHA256 = "83bbabb8f446a34e0745d1cb7a7eabcaae597dbd175d57a0eee99a07d78c630c"
POLICY_PATH = "docs/governance/retrieval_scope_policy_registry_hggsp_v5.yml"
POLICY_SHA256 = "eee2f69e30d32c5c115b9446c1d0a186c7a049a2b132f1f48ba93d761d489eb2"
AUTHORITY_PATH = "packages/contracts/authorities/production-profile-scope-successors-hggsp-v5.yml"
AUTHORITY_SHA256 = "f72935d27e94d67868ab7e5bed604e4c0a2dba1943ab165918d3ced7ba0aeb8d"
ARTIFACT_DIR = "packages/contracts/src/nexus_contracts/artifacts"
SCOPES = {
    "rag_nexus_hggsp_premiere_specialite": (
        "prod_hggsp_premiere_specialite_v2", "prod_hggsp_premiere_specialite_v3"
    ),
    "rag_nexus_hggsp_terminale_specialite": (
        "prod_hggsp_terminale_specialite_v2", "prod_hggsp_terminale_specialite_v3"
    ),
}
RELEASE_FACT_FIELDS = frozenset({
    "subject_manifest_sha256", "admissibility_evidence", "justification",
    "decision_binding",
})


class ScopeDerivationRefused(ValueError):
    """Une liaison ou une politique divergente interdit l'émission."""


def _checked(root: Path, path: str, digest: str) -> bytes:
    raw = (root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ScopeDerivationRefused(f"empreinte divergente : {path}")
    return raw


def validate_inherited_policy(new: dict[str, Any], old: dict[str, Any]) -> None:
    """Le registre V5 ne peut changer aucune décision de politique V4."""
    new_fields = set(new) - RELEASE_FACT_FIELDS
    old_fields = set(old) - RELEASE_FACT_FIELDS
    if new_fields != old_fields:
        raise ScopeDerivationRefused("champs de politique V4 divergents")
    for field in sorted(new_fields):
        if new[field] != old[field]:
            raise ScopeDerivationRefused(f"politique V4 divergente : {field}")


def validate_successor_authority(authority: dict[str, Any]) -> None:
    """Une autorité HGGSP V4 ne vaut jamais pour les subjects successeurs."""
    if (authority.get("release_id") != RELEASE_ID
            or authority.get("release_manifest_sha256") != RELEASE_SHA256
            or authority.get("mixed_registry_sha256") != MIXED_SHA256
            or authority.get("authority_name") != "HGGSP_V5_COMPLEMENTARY"):
        raise ScopeDerivationRefused("autorité de nommage non liée au successeur")


def validate_admissibility_evidence(
    entry: dict[str, Any], specification: dict[str, Any], subject: dict[str, Any]
) -> None:
    """Recompter les preuves d'admissibilité sur chaque placement scellé."""
    collection = specification.get("collection")
    path = specification.get("path")
    digest = specification.get("sha256")
    placements = subject.get("placements")
    if (
        collection not in SCOPES
        or subject.get("collection") != collection
        or not isinstance(path, str)
        or not path.startswith("subjects/")
        or not isinstance(digest, str)
        or not isinstance(placements, list)
        or not placements
        or entry.get("admissibility_status") != "ADMISSIBLE_ON_SEALED_RELEASE_EVIDENCE"
    ):
        raise ScopeDerivationRefused(f"admissibilité scellée invalide : {collection}")
    expected = {
        "placements_total": len(placements),
        "review_status": "reviewed",
        "placement_status": "active",
        "currentness": "official_snapshot",
        "subject_manifest_sha256": digest,
        "subject_path": f"profile_gate/{path}",
    }
    if entry.get("admissibility_evidence") != expected:
        raise ScopeDerivationRefused(f"admissibilité non prouvée : {collection}")
    for placement in placements:
        if not isinstance(placement, dict) or any(
            placement.get(field) != value
            for field, value in (
                ("collection", collection),
                ("review_status", expected["review_status"]),
                ("placement_status", expected["placement_status"]),
                ("currentness", expected["currentness"]),
            )
        ):
            raise ScopeDerivationRefused(f"admissibilité d'un placement refusée : {collection}")


def derive(root: Path) -> tuple[bytes, dict[str, bytes]]:
    """Vérifie les liaisons puis reproduit les octets par l'émetteur canonique."""
    release = json.loads(_checked(root, RELEASE_PATH, RELEASE_SHA256))
    mixed = json.loads(_checked(root, MIXED_PATH, MIXED_SHA256))
    policy = yaml.safe_load(_checked(root, POLICY_PATH, POLICY_SHA256))
    old_policy = yaml.safe_load(_checked(root, V4_POLICY_PATH, V4_POLICY_SHA256))
    authority_raw = _checked(root, AUTHORITY_PATH, AUTHORITY_SHA256)
    authority = yaml.safe_load(authority_raw)
    if release.get("release_id") != RELEASE_ID:
        raise ScopeDerivationRefused("release HGGSP divergente")
    if {s["collection"] for s in release["subjects"]} != set(SCOPES):
        raise ScopeDerivationRefused("release hors des deux collections HGGSP")
    if (policy.get("release_id") != RELEASE_ID
            or policy.get("release_manifest_path") != RELEASE_PATH
            or policy.get("release_manifest_sha256") != RELEASE_SHA256
            or policy.get("mixed_registry_path") != MIXED_PATH
            or policy.get("mixed_registry_sha256") != MIXED_SHA256
            or policy.get("predecessor_registry_path") != V4_POLICY_PATH
            or policy.get("predecessor_registry_sha256") != V4_POLICY_SHA256):
        raise ScopeDerivationRefused("liaisons du registre de politique divergentes")
    validate_successor_authority(authority)
    if (policy["programme_version_authority"]["sha256"]
            != release["authorities"]["programme_registry_sha256"]):
        raise ScopeDerivationRefused("programme non lié au manifeste scellé")
    if mixed.get("registry_version") != "2" or len(mixed.get("releases", [])) != 2:
        raise ScopeDerivationRefused("registre mixte v2 attendu")
    owners: dict[str, str] = {}
    for item in mixed["releases"]:
        for collection in item["collections"]:
            if collection in owners:
                raise ScopeDerivationRefused("collection avec deux propriétaires")
            owners[collection] = item["release_id"]
    if (len(owners) != 11
            or {c for c, owner in owners.items() if owner == RELEASE_ID} != set(SCOPES)):
        raise ScopeDerivationRefused("propriété mixte divergente")
    successor = next((r for r in mixed["releases"] if r["release_id"] == RELEASE_ID), None)
    if successor is None:
        raise ScopeDerivationRefused("release successeur absente du registre mixte")
    if successor.get("expected_manifest_sha256") != RELEASE_SHA256:
        raise ScopeDerivationRefused("manifeste non lié au registre mixte")
    new_entries = {e["collection"]: e for e in policy["collections"]}
    old_entries = {e["collection"]: e for e in old_policy["collections"]}
    bindings = {e["collection"]: e for e in authority["bindings"]}
    subjects = {e["collection"]: e["sha256"] for e in release["subjects"]}
    if set(new_entries) != set(SCOPES) or set(bindings) != set(SCOPES):
        raise ScopeDerivationRefused("registre ou autorité hors des deux scopes")
    total_placements = 0
    for specification in release["subjects"]:
        collection = specification["collection"]
        subject_path = Path(RELEASE_PATH).parent / specification["path"]
        subject = json.loads(_checked(root, str(subject_path), specification["sha256"]))
        validate_admissibility_evidence(new_entries[collection], specification, subject)
        total_placements += len(subject["placements"])
    if total_placements != 74 or release["expected_counts"]["placements"] != 74:
        raise ScopeDerivationRefused("admissibilité : cardinalité de placements divergente")
    for collection, (old_id, new_id) in SCOPES.items():
        validate_inherited_policy(new_entries[collection], old_entries[collection])
        old = load_retrieval_scope_artifact(old_id)
        if (old.scope_id != old_id
                or new_id != old_id.removesuffix("_v2") + "_v3"
                or bindings[collection].get("scope_id") != new_id
                or bindings[collection].get("predecessor_scope_id") != old_id
                or bindings[collection].get("subject_sha256") != subjects[collection]
                or new_entries[collection].get("subject_manifest_sha256") != subjects[collection]):
            raise ScopeDerivationRefused(f"noms ou subjects divergents : {collection}")
    with TemporaryDirectory(prefix="hggsp-scope-") as temp:
        result = emit_from_policy_registry(
            subject_release=root / RELEASE_PATH,
            subject_release_sha256=RELEASE_SHA256,
            policy_registry=root / POLICY_PATH,
            policy_registry_sha256=POLICY_SHA256,
            successor_authority=root / AUTHORITY_PATH,
            successor_authority_sha256=AUTHORITY_SHA256,
            artifacts_dir=Path(temp),
            repo_root=root,
            reproduce_scope_ids=frozenset(new_id for _, new_id in SCOPES.values()),
        )
    if result.reused or {item.scope_id for item in result.emitted} != {
        new_id for _, new_id in SCOPES.values()
    }:
        raise ScopeDerivationRefused("émission canonique incomplète")
    return authority_raw, {item.scope_id: item.canonical_bytes for item in result.emitted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        authority, artifacts = derive(ROOT)
        files = {ROOT / AUTHORITY_PATH: authority}
        files.update({
            ROOT / ARTIFACT_DIR / f"retrieval-scope-{scope_id.replace('_', '-')}.json": raw
            for scope_id, raw in artifacts.items()
        })
        if args.check:
            for path, expected in files.items():
                if path.read_bytes() != expected:
                    raise ScopeDerivationRefused(f"octets divergents : {path.relative_to(ROOT)}")
        else:
            for path, raw in files.items():
                path.write_bytes(raw)
    except (ScopeDerivationRefused, OSError, KeyError, ValueError) as exc:
        print(f"HGGSP_SCOPE_REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
