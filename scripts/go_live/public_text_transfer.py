#!/usr/bin/env python3
"""Préparer puis observer en lecture seule le transfert des dérivés textuels.

Un plan n'atteste aucun transfert. Un reçu ne vaut que pour la cible dont les
octets sont re-hachés par ``verify_observed_destination`` ; il n'autorise pas
la publication à lui seul.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TEXT_MIME = "text/plain; charset=utf-8"
INVENTORY_KIND = "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1"
ALLOWLIST_KIND = "NEXUS_STUDENT_PUBLIC_PRIVATE_TRANSFER_ALLOWLIST_V1"
MANIFEST_KIND = "NEXUS_STUDENT_PUBLIC_TEXT_TRANSFER_MANIFEST_V1"
RECEIPT_KIND = "NEXUS_STUDENT_PUBLIC_TEXT_OBSERVED_TRANSFER_V1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
TEXT_MAGIC = b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n"


class TransferRefused(ValueError):
    """Aucun octet ou reçu n'est considéré transféré après un écart."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TransferRefused(f"clé JSON dupliquée: {key}")
        value[key] = item
    return value


def _document(raw: bytes, label: str, *, canonical_required: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (TypeError, ValueError) as error:
        raise TransferRefused(f"{label}: JSON invalide") from error
    if not isinstance(value, dict) or (canonical_required and raw != canonical(value)):
        raise TransferRefused(f"{label}: JSON invalide ou non canonique")
    return value


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _hash_file(path: Path) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise TransferRefused(f"fichier absent ou lien symbolique: {path.name}")
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
            size += len(block)
    return hasher.hexdigest(), size


def _hash_text_file(path: Path) -> tuple[str, int]:
    observed, size = _hash_file(path)
    raw = path.read_bytes()
    if not raw.startswith(TEXT_MAGIC):
        raise TransferRefused(f"signature du dérivé texte absente: {path.name}")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TransferRefused(f"dérivé non UTF-8: {path.name}") from error
    if digest(raw) != observed or len(raw) != size:
        raise TransferRefused(f"octets du dérivé modifiés pendant le contrôle: {path.name}")
    return observed, size


def verify_successor_inventory(root: Path, private_cas_root: Path,
                               inventory_raw: bytes, allowlist_raw: bytes) -> None:
    """Rejouer le builder #313 et comparer tout son paquet immuable au dépôt."""
    from build_student_public_successor_release import build_documents, load_sources
    from check_student_public_derivative_inclusions import verify_private_cas_evidence

    root = root.resolve()
    try:
        source = load_sources(root)
        inclusion = verify_private_cas_evidence(source, private_cas_root)
        documents = build_documents(source, inclusion=inclusion)
        inventory_matches = [raw == inventory_raw for path, raw in documents.items()
                             if path.name == "candidate_inventory.json"]
        allowlist_matches = [raw == allowlist_raw for path, raw in documents.items()
                             if path.name == "private_transfer_allowlist.json"]
        if inventory_matches != [True] or allowlist_matches != [True]:
            raise TransferRefused("inventaire et allowlist successeurs non concordants")
        for path, raw in documents.items():
            if (root / path).read_bytes() != raw:
                raise TransferRefused(f"paquet successeur divergent: {path.name}")
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        raise TransferRefused("autorité successeur non vérifiée") from error


def plan_text_transfer(inventory_raw: bytes, allowlist_raw: bytes,
                       source_root: Path, evidence_root: Path | None = None) -> dict[str, Any]:
    """Lier le sous-ensemble final aux octets privés ; ne rien copier."""
    inventory = _document(inventory_raw, "inventaire")
    allowlist = _document(allowlist_raw, "allowlist")
    release_id = inventory.get("release_id")
    if (inventory.get("inventory_kind") != INVENTORY_KIND
            or not isinstance(release_id, str) or not release_id.startswith("student-public-")
            or allowlist.get("kind") != ALLOWLIST_KIND
            or allowlist.get("release_id") != release_id
            or allowlist.get("candidate_inventory_sha256") != digest(inventory_raw)
            or allowlist.get("transfer_status") != "NOT_TRANSFERRED"):
        raise TransferRefused("inventaire et allowlist non liés")
    allowed = allowlist.get("expected_files")
    if (not isinstance(allowed, list) or not allowed
            or allowlist.get("allowed_file_count") != len(allowed)):
        raise TransferRefused("population allowlist invalide")
    allowed_by_sha: dict[str, dict[str, Any]] = {}
    for row in allowed:
        if (not isinstance(row, dict) or set(row) != {
                "file", "media_type", "sha256_expected", "source_private_relpath"}
                or not _sha(row.get("sha256_expected"))
                or row.get("media_type") != TEXT_MIME
                or row.get("file") != f"{row['sha256_expected']}.txt"
                or row.get("source_private_relpath") != f"candidates/{row['file']}"
                or row["sha256_expected"] in allowed_by_sha):
            raise TransferRefused("allowlist hors périmètre texte")
        allowed_by_sha[row["sha256_expected"]] = row
    collections = inventory.get("collections")
    if not isinstance(collections, list) or not collections:
        raise TransferRefused("collections absentes")
    selected: dict[str, dict[str, Any]] = {}
    names: set[str] = set()
    placement_count = 0
    for collection in collections:
        if not isinstance(collection, dict) or set(collection) != {"collection", "candidates"}:
            raise TransferRefused("collection malformée")
        name, candidates = collection["collection"], collection["candidates"]
        if not isinstance(name, str) or not name or name in names or not isinstance(candidates, list) or not candidates:
            raise TransferRefused("collection vide ou dupliquée")
        names.add(name)
        seen_in_collection: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise TransferRefused("artefact malformé")
            sha = candidate.get("content_sha256")
            placements = candidate.get("placements")
            if (not _sha(sha) or candidate.get("physical_path") != f"{sha}.txt"
                    or candidate.get("media_type") != TEXT_MIME
                    or not _sha(candidate.get("source_pdf_sha256"))
                    or candidate["source_pdf_sha256"] == sha
                    or not isinstance(placements, list) or not placements
                    or any(not isinstance(p, dict) or not _sha(p.get("source_placement_id"))
                           for p in placements)
                    or sha not in allowed_by_sha or sha in seen_in_collection):
                raise TransferRefused("artefact hors allowlist textuelle")
            seen_in_collection.add(sha)
            previous = selected.setdefault(sha, candidate)
            if previous.get("source_pdf_sha256") != candidate.get("source_pdf_sha256"):
                raise TransferRefused("identité source PDF contradictoire")
            placement_count += len(placements)
    counts = inventory.get("counts")
    if (not isinstance(counts, dict) or counts.get("collections") != len(names)
            or counts.get("unique_artifacts") != len(selected)
            or counts.get("placements") != placement_count):
        raise TransferRefused("comptes inventaire divergents")
    if set(allowed_by_sha) != set(selected):
        raise TransferRefused("allowlist et inventaire de populations différentes")
    source_root = source_root.resolve()
    evidence_root = (evidence_root or source_root).resolve()
    files = []
    receipt_shas: set[str] = set()
    for sha in sorted(selected):
        row = allowed_by_sha[sha]
        source = source_root / row["source_private_relpath"]
        if not source.resolve().is_relative_to(source_root):
            raise TransferRefused("source hors magasin privé")
        observed, _ = _hash_text_file(source)
        if observed != sha:
            raise TransferRefused("octets source substitués")
        receipt_sha = selected[sha].get("derivative_receipt_sha256")
        if not _sha(receipt_sha):
            raise TransferRefused("reçu CAS source absent")
        receipt_shas.add(receipt_sha)
        files.append({"file": row["file"], "media_type": TEXT_MIME,
                      "sha256_expected": sha})
    receipt_files = []
    for receipt_sha in sorted(receipt_shas):
        source = evidence_root / "derivative_receipts" / f"{receipt_sha}.json"
        if not source.resolve().is_relative_to(evidence_root):
            raise TransferRefused("reçu CAS hors magasin privé")
        observed, _ = _hash_file(source)
        if observed != receipt_sha:
            raise TransferRefused("reçu CAS source substitué")
        receipt_files.append({"file": f"derivative_receipts/{receipt_sha}.json",
                              "sha256_expected": receipt_sha})
    return {
        "kind": MANIFEST_KIND,
        "status": "PLANNED_NOT_TRANSFERRED",
        "release_id": release_id,
        "inventory_sha256": digest(inventory_raw),
        "allowlist_sha256": digest(allowlist_raw),
        "file_count": len(files),
        "derivative_receipt_count": len(receipt_files),
        "placement_count": placement_count,
        "files": files,
        "derivative_receipts": receipt_files,
    }


def _manifest(raw: bytes) -> dict[str, Any]:
    manifest = _document(raw, "manifeste de transfert", canonical_required=True)
    files = manifest.get("files")
    receipts = manifest.get("derivative_receipts")
    if (set(manifest) != {"kind", "status", "release_id", "inventory_sha256",
                          "allowlist_sha256", "file_count", "derivative_receipt_count",
                          "placement_count", "files", "derivative_receipts"}
            or manifest.get("kind") != MANIFEST_KIND
            or manifest.get("status") != "PLANNED_NOT_TRANSFERRED"
            or not isinstance(manifest.get("release_id"), str)
            or not manifest["release_id"].startswith("student-public-")
            or not _sha(manifest.get("inventory_sha256"))
            or not _sha(manifest.get("allowlist_sha256"))
            or not isinstance(files, list) or not files
            or manifest.get("file_count") != len(files)
            or not isinstance(receipts, list) or not receipts
            or manifest.get("derivative_receipt_count") != len(receipts)
            or not isinstance(manifest.get("placement_count"), int)
            or manifest["placement_count"] < len(files)):
        raise TransferRefused("manifeste non admissible")
    shas = []
    for row in files:
        if (not isinstance(row, dict) or set(row) != {"file", "media_type", "sha256_expected"}
                or not _sha(row.get("sha256_expected"))
                or row.get("file") != f"{row['sha256_expected']}.txt"
                or row.get("media_type") != TEXT_MIME):
            raise TransferRefused("entrée transfert non textuelle")
        shas.append(row["sha256_expected"])
    if shas != sorted(set(shas)):
        raise TransferRefused("population transfert non triée ou dupliquée")
    receipt_shas = []
    for row in receipts:
        if (not isinstance(row, dict) or set(row) != {"file", "sha256_expected"}
                or not _sha(row.get("sha256_expected"))
                or row.get("file") != f"derivative_receipts/{row['sha256_expected']}.json"):
            raise TransferRefused("reçu CAS déclaré invalide")
        receipt_shas.append(row["sha256_expected"])
    if receipt_shas != sorted(set(receipt_shas)):
        raise TransferRefused("reçus CAS non triés ou dupliqués")
    return manifest


def observe_destination(manifest_raw: bytes, destination_root: Path,
                        target_identity: str, observed_at_utc: str) -> dict[str, Any]:
    """Re-hacher toute la destination et refuser tout fichier supplémentaire."""
    manifest = _manifest(manifest_raw)
    if not isinstance(target_identity, str) or not target_identity.strip():
        raise TransferRefused("identité runtime de destination absente")
    if not isinstance(observed_at_utc, str) or not observed_at_utc.endswith("Z"):
        raise TransferRefused("heure UTC d'observation absente")
    try:
        datetime.fromisoformat(observed_at_utc)
    except ValueError as error:
        raise TransferRefused("heure UTC d'observation invalide") from error
    if destination_root.is_symlink() or not destination_root.is_dir():
        raise TransferRefused("répertoire de destination absent")
    children = list(destination_root.rglob("*"))
    if any(path.is_symlink() for path in children):
        raise TransferRefused("destination contient un lien symbolique")
    dirs = {path.relative_to(destination_root).as_posix() for path in children if path.is_dir()}
    if dirs != {"derivative_receipts"} or any(not path.is_file() and not path.is_dir()
                                                for path in children):
        raise TransferRefused("structure du store de destination inattendue")
    expected_names = {row["file"] for row in manifest["files"] + manifest["derivative_receipts"]}
    observed_names = {path.relative_to(destination_root).as_posix()
                      for path in children if path.is_file()}
    if observed_names != expected_names or len(children) != len(expected_names) + 1:
        raise TransferRefused("destination incomplète ou contient un intrus")
    observed_rows = []
    total_size = 0
    for row in manifest["files"]:
        observed, size = _hash_text_file(destination_root / row["file"])
        if observed != row["sha256_expected"]:
            raise TransferRefused("octets destination divergents")
        observed_rows.append({"file": row["file"], "sha256_observed": observed,
                              "size_bytes": size})
        total_size += size
    observed_receipts = []
    for row in manifest["derivative_receipts"]:
        observed, size = _hash_file(destination_root / row["file"])
        if observed != row["sha256_expected"]:
            raise TransferRefused("reçu CAS destination divergent")
        observed_receipts.append({"file": row["file"], "sha256_observed": observed,
                                  "size_bytes": size})
        total_size += size
    return {
        "kind": RECEIPT_KIND,
        "status": "OBSERVED_NOT_PUBLICATION_AUTHORITY",
        "release_id": manifest["release_id"],
        "transfer_manifest_sha256": digest(manifest_raw),
        "target_identity": target_identity,
        "target_identity_status": "CLAIMED_UNQUALIFIED",
        "observed_host": socket.gethostname(),
        "destination_realpath": str(destination_root.resolve(strict=True)),
        "observed_at_utc": observed_at_utc,
        "file_count": len(observed_rows),
        "derivative_receipt_count": len(observed_receipts),
        "total_bytes": total_size,
        "files": observed_rows,
        "derivative_receipts": observed_receipts,
    }


def verify_observed_destination(manifest_raw: bytes, receipt_raw: bytes,
                                destination_root: Path, target_identity: str) -> None:
    """Contrôle indépendant du reçu contre la cible encore accessible."""
    receipt = _document(receipt_raw, "reçu de transfert", canonical_required=True)
    if set(receipt) != {"kind", "status", "release_id", "transfer_manifest_sha256",
                        "target_identity", "target_identity_status", "observed_host",
                        "destination_realpath", "observed_at_utc", "file_count",
                        "derivative_receipt_count", "total_bytes", "files",
                        "derivative_receipts"}:
        raise TransferRefused("reçu de transfert malformé")
    observed = observe_destination(manifest_raw, destination_root,
                                   target_identity, receipt.get("observed_at_utc"))
    if receipt != observed:
        raise TransferRefused("reçu non concordant avec les octets de destination")


def build_worker_transfer_manifest(plan_raw: bytes, receipt_raw: bytes,
                                   destination_root: Path,
                                   target_identity: str) -> dict[str, Any]:
    """Émettre le format lu par Worker A seulement après relecture du reçu."""
    verify_observed_destination(plan_raw, receipt_raw, destination_root, target_identity)
    plan = _manifest(plan_raw)
    receipt = _document(receipt_raw, "reçu de transfert", canonical_required=True)
    observed = {row["file"]: row["sha256_observed"] for row in receipt["files"]}
    return {
        "manifest_kind": "NEXUS-STAGING-ARTIFACT-TRANSFER-V1",
        "release_id": plan["release_id"],
        "transfer_method": "octets textuels observes et re-haches sur la destination",
        "destination_target_identity": target_identity,
        "destination_identity_status": "CLAIMED_UNQUALIFIED",
        "observed_host": receipt["observed_host"],
        "destination_realpath": receipt["destination_realpath"],
        "source_plan_sha256": digest(plan_raw),
        "observed_transfer_receipt_sha256": digest(receipt_raw),
        "file_count": plan["file_count"],
        "derivative_receipt_count": plan["derivative_receipt_count"],
        "digest_missing": 0,
        "digest_mismatches": 0,
        "files": [
            {"file": row["file"], "sha256_expected": row["sha256_expected"],
             "sha256_observed": observed[row["file"]]}
            for row in plan["files"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--observe", action="store_true")
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--worker-manifest", action="store_true")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--private-cas-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--destination-root", type=Path)
    parser.add_argument("--target-identity")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.plan:
            if not all((args.inventory, args.allowlist, args.source_root,
                        args.evidence_root, args.repository_root,
                        args.private_cas_root, args.output)):
                parser.error("--plan exige inventaire, allowlist, source, preuves, CAS, dépôt et sortie")
            inventory_raw = args.inventory.read_bytes()
            allowlist_raw = args.allowlist.read_bytes()
            verify_successor_inventory(args.repository_root, args.private_cas_root,
                                       inventory_raw, allowlist_raw)
            result = plan_text_transfer(inventory_raw, allowlist_raw,
                                        args.source_root, args.evidence_root)
            args.output.write_bytes(canonical(result))
        elif args.observe:
            if not all((args.manifest, args.destination_root, args.target_identity, args.output)):
                parser.error("--observe exige manifeste, destination, identité et sortie")
            observed_at_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            result = observe_destination(args.manifest.read_bytes(), args.destination_root,
                                         args.target_identity, observed_at_utc)
            args.output.write_bytes(canonical(result))
        elif args.verify:
            if not all((args.manifest, args.receipt, args.destination_root, args.target_identity)):
                parser.error("--verify exige manifeste, reçu, destination et identité")
            verify_observed_destination(args.manifest.read_bytes(), args.receipt.read_bytes(),
                                        args.destination_root, args.target_identity)
            print("OBSERVED_TEXT_TRANSFER_VERIFIED=true")
        else:
            if not all((args.manifest, args.receipt, args.destination_root,
                        args.target_identity, args.output)):
                parser.error("--worker-manifest exige plan, reçu, destination, identité et sortie")
            result = build_worker_transfer_manifest(
                args.manifest.read_bytes(), args.receipt.read_bytes(),
                args.destination_root, args.target_identity,
            )
            args.output.write_bytes(canonical(result))
    except (OSError, TransferRefused) as error:
        parser.exit(1, f"TRANSFERT_REFUSE={error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
