#!/usr/bin/env python3
"""Compare hors réseau deux captures explicites de retrieval A/B."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
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


def _rollback_matching_link(path: Path, temporary_descriptor: int) -> None:
    rescue_directory: Path | None = None
    rescue_path: Path | None = None
    try:
        rescue_name = tempfile.mkdtemp(
            prefix=".nexus-rollback.", dir=path.parent
        )
        rescue_directory = Path(rescue_name)
        rescue_path = rescue_directory / "captured"
        os.replace(path, rescue_path)
    except OSError:
        return
    finally:
        if rescue_path is not None:
            try:
                captured_status = os.stat(rescue_path, follow_symlinks=False)
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
                                rescue_path,
                                path,
                                follow_symlinks=False,
                            )
                        except OSError:
                            pass
        if rescue_directory is not None:
            try:
                os.rmdir(rescue_directory)
            except OSError:
                pass


def _exclusive_write(path: Path, raw: bytes) -> None:
    if not path.parent.is_dir():
        raise ParityCliError("output directory is unavailable")
    parent_descriptor = -1
    staging_descriptor = -1
    staging_directory: Path | None = None
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
        staging_directory = Path(
            tempfile.mkdtemp(prefix=".nexus-staging.", dir=path.parent)
        )
        staging_descriptor = os.open(
            staging_directory,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        os.fchmod(staging_descriptor, 0o700)
        staging_status = os.fstat(staging_descriptor)
        staging_parent_status = os.stat(
            "..", dir_fd=staging_descriptor, follow_symlinks=False
        )
        if (
            not stat.S_ISDIR(staging_status.st_mode)
            or stat.S_IMODE(staging_status.st_mode) != 0o700
            or staging_status.st_uid != os.geteuid()
            or (staging_parent_status.st_dev, staging_parent_status.st_ino)
            != (parent_status.st_dev, parent_status.st_ino)
        ):
            raise ParityCliError("output staging is unavailable")
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
            _rollback_matching_link(path, payload_descriptor)
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
            and staging_directory is not None
            and parent_descriptor >= 0
        ):
            try:
                os.rmdir(staging_directory.name, dir_fd=parent_descriptor)
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
