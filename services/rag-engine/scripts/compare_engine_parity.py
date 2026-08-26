#!/usr/bin/env python3
"""Compare hors réseau deux captures explicites de retrieval A/B."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Never

from src.ingestor.engine_parity import (
    EngineParityError,
    ParityVerdict,
    compare_engine_parity,
)

_REPORT_PROTOCOL = "NEXUS-ENGINE-PARITY-REPORT-V1"


class ParityCliError(ValueError):
    """Erreur opérateur sans reprise des arguments ou du contenu."""


class _SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        del message
        raise ParityCliError("arguments are invalid")


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


def _exclusive_write(path: Path, raw: bytes) -> None:
    if not path.parent.is_dir():
        raise ParityCliError("output directory is unavailable")
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
            raise ParityCliError("output directory is unavailable")
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
            if written <= 0:
                raise OSError("short output write")
            remaining = remaining[written:]
        os.fsync(payload_descriptor)
        publication_attempted = True
        os.link(
            "payload",
            path.name,
            src_dir_fd=staging_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        os.fsync(parent_descriptor)
    except FileExistsError as exc:
        raise ParityCliError("output already exists") from exc
    except OSError as exc:
        rollback_required = publication_attempted
        raise ParityCliError("output publication failed") from exc
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


def _parser() -> argparse.ArgumentParser:
    parser = _SanitizedArgumentParser(
        description="Comparer trois fichiers locaux scellés sans accès réseau."
    )
    parser.add_argument("--witness", required=True, type=Path)
    parser.add_argument("--engine-a", required=True, type=Path)
    parser.add_argument("--engine-b", required=True, type=Path)
    parser.add_argument("--write-report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        report = compare_engine_parity(
            arguments.witness,
            arguments.engine_a,
            arguments.engine_b,
        )
        unsigned_document = {
            "protocol_version": _REPORT_PROTOCOL,
            **asdict(report),
        }
        full_document = {
            **unsigned_document,
            "report_sha256": hashlib.sha256(
                _canonical_json(unsigned_document)
            ).hexdigest(),
        }
        if arguments.write_report is not None:
            _exclusive_write(
                arguments.write_report,
                _canonical_json(full_document),
            )
        summary = {
            key: full_document[key]
            for key in (
                "protocol_version",
                "verdict",
                "reason_codes",
                "input_digests",
                "metrics",
                "passage_divergence_count",
                "synthetic_evidence",
                "report_sha256",
            )
        }
        print(_canonical_json(summary).decode("utf-8"), end="")
        return 3 if report.verdict is ParityVerdict.FAIL_CLOSED else 0
    except (EngineParityError, ParityCliError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
