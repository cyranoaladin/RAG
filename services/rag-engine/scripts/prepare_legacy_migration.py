#!/usr/bin/env python3
"""Prépare hors ligne un manifeste de réingestion legacy gouvernée."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Never

from src.ingestor.engine_convergence_policy import load_engine_convergence_policy
from src.ingestor.legacy_convergence import LegacyCaptureError, prepare_legacy_capture

_SUMMARY_PROTOCOL = "NEXUS-LEGACY-MIGRATION-SUMMARY-V1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class PreparationCliError(ValueError):
    """Erreur opérateur assainie du CLI de préparation."""


class _SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        del message
        raise PreparationCliError("arguments are invalid")


def _canonical_json(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _open_private_directory(
    parent_descriptor: int, *, prefix: str
) -> tuple[str, int]:
    for _ in range(64):
        directory_name = f"{prefix}{secrets.token_hex(12)}"
        try:
            os.mkdir(directory_name, 0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        directory_descriptor = -1
        try:
            directory_descriptor = os.open(
                directory_name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_descriptor,
            )
            os.fchmod(directory_descriptor, 0o700)
            directory_status = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(directory_status.st_mode)
                or stat.S_IMODE(directory_status.st_mode) != 0o700
                or directory_status.st_uid != os.geteuid()
            ):
                raise OSError("private directory validation failed")
            return directory_name, directory_descriptor
        except BaseException:
            if directory_descriptor >= 0:
                try:
                    os.close(directory_descriptor)
                except OSError:
                    pass
            try:
                os.rmdir(directory_name, dir_fd=parent_descriptor)
            except OSError:
                pass
            raise
    raise OSError("private directory allocation failed")


def _rollback_matching_link(
    parent_descriptor: int,
    staging_descriptor: int,
    output_name: str,
    temporary_descriptor: int,
) -> None:
    try:
        os.replace(
            output_name,
            "captured",
            src_dir_fd=parent_descriptor,
            dst_dir_fd=staging_descriptor,
        )
    except OSError:
        return
    finally:
        try:
            captured_status = os.stat(
                "captured",
                dir_fd=staging_descriptor,
                follow_symlinks=False,
            )
        except OSError:
            pass
        else:
            captured_identity = (
                captured_status.st_dev,
                captured_status.st_ino,
            )
            try:
                temporary_status = os.fstat(temporary_descriptor)
            except OSError:
                pass
            else:
                temporary_identity = (
                    temporary_status.st_dev,
                    temporary_status.st_ino,
                )
                if captured_identity != temporary_identity:
                    try:
                        os.link(
                            "captured",
                            output_name,
                            src_dir_fd=staging_descriptor,
                            dst_dir_fd=parent_descriptor,
                            follow_symlinks=False,
                        )
                    except OSError:
                        pass


def _exclusive_publish(path: Path, raw: bytes) -> None:
    """Publier un nouveau fichier complet sans jamais écraser une cible."""

    if not path.parent.is_dir():
        raise PreparationCliError("output directory is unavailable")
    parent_descriptor = -1
    staging_descriptor = -1
    staging_name: str | None = None
    payload_descriptor = -1
    publication_attempted = False
    rollback_required = False
    try:
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        parent_status = os.fstat(parent_descriptor)
        if not stat.S_ISDIR(parent_status.st_mode) or not (
            parent_status.st_uid == os.geteuid()
            or parent_status.st_mode & stat.S_ISVTX
        ):
            raise PreparationCliError("output directory is unavailable")
        staging_name, staging_descriptor = _open_private_directory(
            parent_descriptor,
            prefix=".nexus-staging.",
        )
        payload_descriptor = os.open(
            "payload",
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=staging_descriptor,
        )
        os.fchmod(payload_descriptor, 0o600)
        remaining = memoryview(raw)
        while remaining:
            written = os.write(payload_descriptor, remaining)
            remaining = remaining[written:]
        os.fsync(payload_descriptor)
        try:
            publication_attempted = True
            os.link(
                "payload",
                path.name,
                src_dir_fd=staging_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise PreparationCliError("output already exists") from exc
        os.fsync(parent_descriptor)
    except PreparationCliError:
        raise
    except OSError as exc:
        rollback_required = publication_attempted
        raise PreparationCliError("output publication failed") from exc
    except BaseException:
        rollback_required = publication_attempted
        raise
    finally:
        if rollback_required and payload_descriptor >= 0:
            _rollback_matching_link(
                parent_descriptor,
                staging_descriptor,
                path.name,
                payload_descriptor,
            )
        if payload_descriptor >= 0:
            descriptor_to_close = payload_descriptor
            payload_descriptor = -1
            try:
                os.close(descriptor_to_close)
            except OSError:
                pass
        if not rollback_required and staging_descriptor >= 0:
            try:
                os.unlink("payload", dir_fd=staging_descriptor)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if staging_descriptor >= 0:
            descriptor_to_close = staging_descriptor
            staging_descriptor = -1
            try:
                os.close(descriptor_to_close)
            except OSError:
                pass
        if (
            not rollback_required
            and staging_name is not None
            and parent_descriptor >= 0
        ):
            try:
                os.rmdir(staging_name, dir_fd=parent_descriptor)
            except OSError:
                pass
        if parent_descriptor >= 0:
            descriptor_to_close = parent_descriptor
            parent_descriptor = -1
            try:
                os.close(descriptor_to_close)
            except OSError:
                pass


def _summary(manifest: Any, *, mode: str) -> dict[str, Any]:
    return {
        "protocol_version": _SUMMARY_PROTOCOL,
        "mode": mode,
        "capture_context": manifest.producer.capture_context,
        "input_digest_sha256": manifest.input_digest_sha256,
        "manifest_sha256": manifest.manifest_sha256,
        "migration_complete": manifest.migration_complete,
        "source_object_count": manifest.source_object_count,
        "prepared_object_count": manifest.prepared_object_count,
        "duplicate_count": manifest.duplicate_count,
        "empty_collection_count": len(manifest.empty_collections),
        "disposition_counts": dict(manifest.disposition_counts),
    }


def _parser() -> argparse.ArgumentParser:
    parser = _SanitizedArgumentParser(
        description="Préparer localement une capture legacy sans accès DB ou réseau."
    )
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--write-manifest", type=Path)
    parser.add_argument("--expected-input-sha256")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        policy = load_engine_convergence_policy(arguments.policy)
        manifest = prepare_legacy_capture(arguments.capture, policy=policy)
        mode = "DRY_RUN"
        if arguments.write_manifest is not None:
            expected_digest = arguments.expected_input_sha256
            if expected_digest is None:
                raise PreparationCliError(
                    "write requires --expected-input-sha256"
                )
            if _SHA256.fullmatch(expected_digest) is None:
                raise PreparationCliError("expected-input-sha256 is invalid")
            if expected_digest != manifest.input_digest_sha256:
                raise PreparationCliError("input digest mismatch")
            _exclusive_publish(
                arguments.write_manifest,
                _canonical_json(asdict(manifest)),
            )
            mode = "WRITE"
        elif arguments.expected_input_sha256 is not None:
            raise PreparationCliError(
                "expected-input-sha256 requires --write-manifest"
            )
        print(_canonical_json(_summary(manifest, mode=mode)).decode("utf-8"), end="")
        return 0
    except (LegacyCaptureError, PreparationCliError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
