"""Le worker n'extrait qu'avec le runtime pypdf déclaré par la release.

Une seule autorité : `nexus_pdf_page_policy.CANONICAL_PYPDF_VERSION`, celle du
verrou D-41 du producteur. Mesuré le 2026-09-02 : 4.2.0 et 6.14.2 rendent le même
`page_count` et le même verdict de pages vides, mais un texte différent sur 319
des 320 PDF de la production visée — d'autres chunks que ceux que la release
attend. Le démarrage refuse donc AVANT de lire la moindre preuve.
"""

from __future__ import annotations

from pathlib import Path

import nexus_pdf_page_policy as policy
import pypdf
import pytest

from ingestor.ingestion_worker import multilevel_runtime_authority, runtime_authority
from ingestor.ingestion_worker.runtime_authority import (
    RuntimeAuthorityStartupError,
    require_canonical_worker_runtime,
)


def test_the_worker_guard_is_the_shared_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pypdf, "__version__", policy.CANONICAL_PYPDF_VERSION)
    assert require_canonical_worker_runtime() == policy.CANONICAL_PYPDF_VERSION


def test_another_runtime_is_refused_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pypdf, "__version__", "4.2.0")
    with pytest.raises(RuntimeAuthorityStartupError, match="4.2.0"):
        require_canonical_worker_runtime()


def _inputs(cls: type, path: Path) -> object:
    return cls(**dict.fromkeys(cls.__dataclass_fields__, path))


def test_both_worker_loaders_refuse_before_reading_any_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pypdf, "__version__", "4.2.0")

    def exploding_digest(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("a proof was read before the runtime guard")

    monkeypatch.setattr(runtime_authority, "require_file_digest", exploding_digest)
    monkeypatch.setattr(multilevel_runtime_authority, "require_file_digest", exploding_digest)
    with pytest.raises(RuntimeAuthorityStartupError, match="4.2.0"):
        multilevel_runtime_authority.load_multilevel_runtime_authorities(
            _inputs(multilevel_runtime_authority.MultilevelRuntimeAuthorityInputs, tmp_path),  # type: ignore[arg-type]
            profile_registry=None,  # type: ignore[arg-type]
            environment="rehearsal",
        )
    with pytest.raises(RuntimeAuthorityStartupError, match="4.2.0"):
        runtime_authority.load_governed_runtime_authorities(
            _inputs(runtime_authority.RuntimeAuthorityInputs, tmp_path),  # type: ignore[arg-type]
            profile_registry=None,  # type: ignore[arg-type]
            profile_manifest_digest="0" * 64,
        )
