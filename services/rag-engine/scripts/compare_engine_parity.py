#!/usr/bin/env python3
"""Compare hors réseau deux captures explicites de retrieval A/B."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _rollback_matching_link(path: Path, temporary_path: Path) -> None:
    try:
        target_status = os.stat(path, follow_symlinks=False)
        temporary_status = os.stat(temporary_path, follow_symlinks=False)
    except OSError:
        return
    if (target_status.st_dev, target_status.st_ino) != (
        temporary_status.st_dev,
        temporary_status.st_ino,
    ):
        return
    try:
        path.unlink()
    except OSError:
        pass


def _exclusive_write(path: Path, raw: bytes) -> None:
    if not path.parent.is_dir():
        raise ParityCliError("output directory is unavailable")
    descriptor = -1
    temporary_path: Path | None = None
    publication_confirmed = False
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".parity-report.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short output write")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary_path, path, follow_symlinks=False)
        directory_descriptor = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        publication_confirmed = True
    except FileExistsError as exc:
        raise ParityCliError("output already exists") from exc
    except OSError as exc:
        raise ParityCliError("output publication failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            if not publication_confirmed:
                _rollback_matching_link(path, temporary_path)
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                if not publication_confirmed:
                    raise ParityCliError("temporary output cleanup failed") from None


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
