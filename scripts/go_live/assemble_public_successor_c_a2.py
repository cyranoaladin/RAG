"""Assembler C A2 depuis 26 preuves explicites, sans s'auto-activer.

Le bundle est une copie privée d'octets. Seul le signer PUBLICATION rejoue
ensuite GitHub, les sources, la cible et PostgreSQL pour conclure sur C.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from build_public_successor_content_anchor import (
    build_authority_envelope,
    canonical_bytes,
)
from nexus_release_chain.public_successor_activation import verify_content_anchor
from nexus_release_chain.release_readiness import _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS

COMPANION_FILES = frozenset({
    "observed-transfer-v1.json", "target-pin.json", "scope-policy.yml", "scope-names.yml",
})


class AssemblyRefused(ValueError):
    """Le paquet C ne peut pas être émis avec ces entrées."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssemblyRefused("duplicate evidence map key refused")
        result[key] = value
    return result


def _require_regular(path: Path) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise AssemblyRefused("evidence path must be absolute")
    walked = Path(path.anchor)
    for part in path.parts[1:]:
        walked /= part
        if walked.is_symlink():
            raise AssemblyRefused("evidence symlink refused")
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise AssemblyRefused("evidence file absent or not regular")
    raw = path.read_bytes()
    if not raw:
        raise AssemblyRefused("empty evidence file refused")
    return raw


def _expected_release_files(anchor: dict[str, object]) -> set[str]:
    subjects = anchor.get("subjects")
    if not isinstance(subjects, list) or len(subjects) != 11:
        raise AssemblyRefused("A subject population is not eleven")
    files = {
        "preparation-index.json", "release-registry.json",
        "profile_gate/production-profile-gate.release.json",
        "profile_gate/artifacts.release.json", "profile_gate/candidate_inventory.json",
        "profile_gate/inclusion_attestation.json",
        "profile_gate/private_transfer_allowlist.json",
        "profile_gate/public_currentness_registry.json",
        "profile_gate/public_pii_registry.json", "profile_gate/public_profiles.json",
        "profile_gate/public_rights_registry.json",
        "profile_gate/profiles/public_profile_proposal.json",
    }
    for subject in subjects:
        if not isinstance(subject, dict) or not isinstance(subject.get("collection"), str):
            raise AssemblyRefused("A subject identity malformed")
        collection = subject["collection"]
        if not collection.startswith("rag_nexus_") or "/" in collection or ".." in collection:
            raise AssemblyRefused("A collection path invalid")
        files.add(f"profile_gate/subjects/{collection}.release.json")
        files.add(f"profile_gate/profiles/{collection}.yml")
    if len(files) != 34:
        raise AssemblyRefused("A release file population invalid")
    return files


def _require_release_tree(release_root: Path, anchor: dict[str, object]) -> None:
    if not release_root.is_absolute() or release_root.is_symlink() or not release_root.is_dir():
        raise AssemblyRefused("release root absent or symlink")
    observed: set[str] = set()
    for path in release_root.rglob("*"):
        if path.is_symlink():
            raise AssemblyRefused("release symlink refused")
        if path.is_file():
            _require_regular(path)
            observed.add(path.relative_to(release_root).as_posix())
        elif not path.is_dir():
            raise AssemblyRefused("foreign release entry refused")
    if observed != _expected_release_files(anchor):
        raise AssemblyRefused("foreign or missing release file refused")


def assemble_a2_bundle(
    *, anchor_path: Path, release_root: Path,
    evidence_paths: dict[str, Path], companion_paths: dict[str, Path],
    output_root: Path,
) -> dict[str, object]:
    if set(evidence_paths) != _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS:
        raise AssemblyRefused("A2 C requires exactly 26 authority files")
    if set(companion_paths) != COMPANION_FILES:
        raise AssemblyRefused("A2 C companion file population differs")
    if not output_root.is_absolute() or output_root.exists() or output_root.is_symlink():
        raise AssemblyRefused("output bundle exists or path invalid")
    if output_root.is_relative_to(release_root):
        raise AssemblyRefused("output bundle overlaps immutable release")
    walked = Path(output_root.anchor)
    for part in output_root.parts[1:-1]:
        walked /= part
        if walked.is_symlink():
            raise AssemblyRefused("output parent symlink refused")
    anchor_raw = _require_regular(anchor_path)
    try:
        anchor = json.loads(anchor_raw)
        if not isinstance(anchor, dict) or canonical_bytes(anchor) != anchor_raw:
            raise AssemblyRefused("A is not canonical JSON")
        _require_release_tree(release_root, anchor)
        verify_content_anchor(anchor_path, _sha(anchor_raw), release_root)
    except AssemblyRefused:
        raise
    except (ValueError, KeyError, OSError) as error:
        raise AssemblyRefused("immutable A replay refused") from error
    proof_bytes = {field: _require_regular(path) for field, path in evidence_paths.items()}
    companion_bytes = {name: _require_regular(path) for name, path in companion_paths.items()}
    anchored = {
        "source_preparation_release_manifest_sha256":
            "profile_gate/production-profile-gate.release.json",
        "source_preparation_index_sha256": "preparation-index.json",
        "candidate_inventory_sha256": "profile_gate/candidate_inventory.json",
    }
    if any(proof_bytes[field] != (release_root / relative).read_bytes()
           for field, relative in anchored.items()):
        raise AssemblyRefused("anchored authority bytes differ from A")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent))
    try:
        shutil.copytree(release_root, staged / "release")
        (staged / "content-anchor.json").write_bytes(anchor_raw)
        authorities_root = staged / "authorities"
        authorities_root.mkdir()
        staged_evidence: dict[str, Path] = {}
        for field, raw in sorted(proof_bytes.items()):
            path = authorities_root / f"{field}.bin"
            path.write_bytes(raw)
            staged_evidence[field] = path
        staged_evidence["source_preparation_release_manifest_sha256"] = (
            staged / "release/profile_gate/production-profile-gate.release.json"
        )
        staged_evidence["source_preparation_index_sha256"] = (
            staged / "release/preparation-index.json"
        )
        staged_evidence["candidate_inventory_sha256"] = (
            staged / "release/profile_gate/candidate_inventory.json"
        )
        for name, raw in sorted(companion_bytes.items()):
            (authorities_root / name).write_bytes(raw)
        envelope = build_authority_envelope(
            staged / "content-anchor.json", _sha(anchor_raw), staged_evidence,
            authority_version="A2",
        )
        envelope_raw = canonical_bytes(envelope)
        (staged / "authority-envelope.json").write_bytes(envelope_raw)
        verify_content_anchor(staged / "content-anchor.json", _sha(anchor_raw), staged / "release")
        if output_root.exists() or output_root.is_symlink():
            raise AssemblyRefused("output bundle exists")
        os.rename(staged, output_root)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return {
        "status": "EVIDENCE_BYTES_ONLY_NOT_ACTIVABLE",
        "authority_count": len(envelope["authorities"]),
        "content_anchor_sha256": _sha(anchor_raw),
        "authority_envelope_sha256": _sha(envelope_raw),
        "semantic_verification_complete": False,
        "activation_allowed": False,
        "bundle_root": str(output_root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--evidence-map", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        mapping_raw = _require_regular(args.evidence_map)
        mapping = json.loads(mapping_raw, object_pairs_hook=_unique_object)
        if not isinstance(mapping, dict) or set(mapping) != {"authorities", "companions"}:
            raise AssemblyRefused("evidence map must name authorities and companions")
        authorities = mapping["authorities"]
        companions = mapping["companions"]
        if not isinstance(authorities, dict) or not isinstance(companions, dict):
            raise AssemblyRefused("evidence map sections invalid")
        if not all(isinstance(value, str) for value in (*authorities.values(), *companions.values())):
            raise AssemblyRefused("evidence map paths invalid")
        result = assemble_a2_bundle(
            anchor_path=args.anchor, release_root=args.release_root,
            evidence_paths={key: Path(value) for key, value in authorities.items()},
            companion_paths={key: Path(value) for key, value in companions.items()},
            output_root=args.output_root,
        )
    except (AssemblyRefused, ValueError, OSError) as error:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
