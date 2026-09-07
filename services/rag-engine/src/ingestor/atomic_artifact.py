"""Atomic, no-clobber publication for one-time governed operator artifacts.

Neither the R1 bootstrap (``resource_registry_bootstrap_cli.py``) nor its
evidence report (``r1_evidence_verifier_cli.py``) may ever be silently
overwritten: each is the sole record of one governed export event. A
same-directory temporary file plus ``os.link`` (which fails with
``FileExistsError`` if the target already exists, unlike ``os.replace``,
which would silently overwrite it) gives that guarantee atomically on
Linux, without a separate existence-check-then-write race.

An existing atomic-write helper (``scripts/sign_production_readiness_manifest_cli.py``
``_atomic_private_write``) was found and inspected before writing this one.
It shares this module's fsync/0600/symlink-guard discipline but its final
publication step is ``os.replace``, which *overwrites* an existing target
by design -- the opposite of what a one-time immutable artifact needs. It
is intentionally not reused for that reason; this module exists so the two
publication semantics (mutable-replace vs. immutable-no-clobber) are never
confused by sharing one function.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

PRIVATE_FILE_MODE = 0o600


class AtomicArtifactError(RuntimeError):
    """The artifact cannot be published safely."""


def assert_publishable(path: Path) -> None:
    """Fail fast, before any database connection is opened, if ``path``
    cannot possibly be published: already exists, is a directory, or its
    parent cannot be created/written to. This is a pre-flight convenience,
    never load-bearing on its own -- :func:`publish_atomic_no_clobber` is
    the actual authoritative no-clobber guard, evaluated again at
    publication time to close the gap between this check and the write."""
    if path.is_dir():
        raise AtomicArtifactError(f"output path is a directory, not a file: {path}")
    if path.exists() or path.is_symlink():
        raise AtomicArtifactError(
            f"output already exists; refusing to overwrite a governed artifact: {path}"
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AtomicArtifactError(f"output directory is not usable: {path.parent} ({exc})") from exc
    if not os.access(path.parent, os.W_OK):
        raise AtomicArtifactError(f"output directory is not writable: {path.parent}")


def publish_atomic_no_clobber(path: Path, raw: bytes, *, mode: int = PRIVATE_FILE_MODE) -> None:
    """Publish ``raw`` to ``path`` atomically; refuses outright if ``path``
    already exists. No partial file is ever visible at ``path``: bytes are
    written to a same-directory temporary file, fsynced, then published
    with ``os.link`` (atomic, and fails closed with ``FileExistsError`` if
    the target exists -- never ``os.replace``, which would overwrite it).
    The temporary name is removed only after the publication attempt, in
    either outcome, so nothing sits around as a partially-written orphan;
    the invariant this function actually guarantees is that ``path`` itself
    is either absent or complete, never partial or overwritten."""
    if path.is_dir():
        raise AtomicArtifactError(f"output path is a directory, not a file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise AtomicArtifactError(
            f"output already exists; refusing to overwrite a governed artifact: {path}"
        )

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1

        if path.is_symlink():
            raise AtomicArtifactError(f"output {path} became a symlink and is never followed")
        try:
            os.link(temp_path, path)
        except FileExistsError:
            raise AtomicArtifactError(
                f"output already exists; refusing to overwrite a governed artifact: {path}"
            ) from None

        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)


__all__ = [
    "PRIVATE_FILE_MODE",
    "AtomicArtifactError",
    "assert_publishable",
    "publish_atomic_no_clobber",
]
