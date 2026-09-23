"""`verify-release-sources` rejoue les chargeurs canoniques sur les octets d'une release.

Lecture seule : aucune base, aucune écriture. Le verdict est celui des
chargeurs eux-mêmes — un refus est rendu avec son motif, jamais adouci.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_control.sealed_evidence import PIIClearance  # noqa: E402
from ingestor.ingestion_worker import attest_publication_cli as cli  # noqa: E402

V2 = REPOSITORY_ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate"
)
TRANSFER = REPOSITORY_ROOT / "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
RIGHTS = REPOSITORY_ROOT / "services/rag-pedago/configs/rights_evidence_registry.yml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _args(manifest_sha: str | None = None) -> list[str]:
    return [
        "verify-release-sources",
        "--release-dir", str(V2),
        "--release-manifest-sha256",
        manifest_sha or _sha(V2 / "production-profile-gate.release.json"),
        "--transfer-manifest-path", str(TRANSFER),
        "--transfer-manifest-sha256", _sha(TRANSFER),
        "--rights-registry-path", str(RIGHTS),
        "--repository-root", str(REPOSITORY_ROOT),
    ]


def test_the_v2_release_is_refused_by_its_own_inventory_loader(capsys) -> None:
    """Mesuré au lot CU : l'inventaire de V2 précède la correction de son producteur."""
    assert cli.main(_args()) == 1
    err = capsys.readouterr().err
    assert "SEALED_SOURCES_REFUSED" in err
    assert "unique_artifacts count differs" in err


def test_a_wrong_manifest_digest_is_refused(capsys) -> None:
    assert cli.main(_args(manifest_sha="0" * 64)) == 1
    assert "SEALED_SOURCES_REFUSED" in capsys.readouterr().err


def test_a_verified_release_is_summarised_from_the_loaded_sources(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    a, b, c = "a" * 64, "b" * 64, "c" * 64

    class _Pii:
        def verify_content_clearance(self, sha: str) -> PIIClearance:
            if sha == c:
                raise cli.SealedEvidenceError("no clearance for c")
            status = "DETECTED_REVIEWED_ACCEPTED" if sha == b else "CLEARED"
            return PIIClearance(content_sha256=sha, pages_scanned=1, characters_scanned=1,
                                evidence_sha256="e" * 64, status=status)

        def verified_review_chain(self) -> dict[str, str | None]:
            return {"pii_decision_set_sha256": "d" * 64}

    sources = cli._SourcesScellees(
        catalogue=SimpleNamespace(release_id="r-v3", artifacts={a: {}, b: {}, c: {}}),
        preflight={a: {}, b: {}, c: {}},
        currentness=SimpleNamespace(artifacts={
            a: SimpleNamespace(disposition="OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"),
            b: SimpleNamespace(disposition="OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"),
        }),
        pii=_Pii(),
        droits=SimpleNamespace(),
    )
    monkeypatch.setattr(cli, "_charger_sources_scellees", lambda _args: sources)
    report = tmp_path / "report.json"

    assert cli.main([*_args(), "--output", str(report)]) == 0
    summary = json.loads(report.read_text(encoding="utf-8"))
    assert "SEALED_SOURCES_VERIFIED" in capsys.readouterr().out
    assert summary["release_id"] == "r-v3"
    assert summary["catalog_artifacts"] == 3
    assert summary["pii_clearance"] == {"CLEARED": 1, "DETECTED_REVIEWED_ACCEPTED": 1, "REFUSED": 1}
    assert summary["pii_refused"] == {c: "no clearance for c"}
    assert summary["currentness_dispositions"] == {
        "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": 2, "ABSENT": 1
    }
    assert summary["verified_review_chain"] == {"pii_decision_set_sha256": "d" * 64}
