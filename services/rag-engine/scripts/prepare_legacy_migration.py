#!/usr/bin/env python3
"""Prépare hors ligne un manifeste de réingestion legacy gouvernée."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
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


def _rollback_matching_link(path: Path, temporary_path: Path) -> None:
    rescue_descriptor = -1
    rescue_path: Path | None = None
    placeholder_identity: tuple[int, int] | None = None
    try:
        rescue_descriptor, rescue_name = tempfile.mkstemp(
            prefix=".nexus-rollback.", dir=path.parent
        )
        rescue_path = Path(rescue_name)
        placeholder_status = os.fstat(rescue_descriptor)
        placeholder_identity = (
            placeholder_status.st_dev,
            placeholder_status.st_ino,
        )
        os.replace(path, rescue_path)
    except OSError:
        return
    finally:
        if rescue_path is not None and placeholder_identity is not None:
            try:
                captured_status = os.stat(rescue_path, follow_symlinks=False)
            except OSError:
                pass
            else:
                captured_identity = (
                    captured_status.st_dev,
                    captured_status.st_ino,
                )
                if captured_identity == placeholder_identity:
                    try:
                        rescue_path.unlink()
                    except OSError:
                        pass
                else:
                    try:
                        temporary_status = os.stat(
                            temporary_path, follow_symlinks=False
                        )
                    except OSError:
                        pass
                    else:
                        temporary_identity = (
                            temporary_status.st_dev,
                            temporary_status.st_ino,
                        )
                        if captured_identity == temporary_identity:
                            try:
                                rescue_path.unlink()
                            except OSError:
                                pass
                        else:
                            try:
                                os.link(rescue_path, path, follow_symlinks=False)
                            except OSError:
                                pass
                            else:
                                try:
                                    rescue_path.unlink()
                                except OSError:
                                    pass
        if rescue_descriptor >= 0:
            os.close(rescue_descriptor)


def _exclusive_publish(path: Path, raw: bytes) -> None:
    """Publier un nouveau fichier complet sans jamais écraser une cible."""

    if not path.parent.is_dir():
        raise PreparationCliError("output directory is unavailable")
    file_descriptor = -1
    temporary_path: Path | None = None
    link_started = False
    rollback_required = False
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(file_descriptor, 0o600)
        remaining = memoryview(raw)
        while remaining:
            written = os.write(file_descriptor, remaining)
            remaining = remaining[written:]
        os.fsync(file_descriptor)
        os.close(file_descriptor)
        file_descriptor = -1
        try:
            link_started = True
            os.link(temporary_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise PreparationCliError("output already exists") from exc
        directory_descriptor = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except PreparationCliError:
        raise
    except OSError as exc:
        rollback_required = link_started
        raise PreparationCliError("output publication failed") from exc
    except BaseException:
        rollback_required = link_started
        raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_path is not None:
            if rollback_required:
                _rollback_matching_link(path, temporary_path)
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
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
