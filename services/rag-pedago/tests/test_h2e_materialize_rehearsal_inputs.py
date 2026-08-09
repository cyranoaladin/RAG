"""Le matérialiseur H2-E ne dispose que d'un transport Drive en lecture."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "services" / "rag-pedago" / "scripts" / "h2e_materialize_rehearsal_inputs.py"
REMOTE_ROOT = "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY"
PDF_REMOTE_PATH = (
    "01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/10_ACTUEL_CONFIRME/"
    "_MULTI_DISCIPLINES/01_PROGRAMMES_OFFICIELS/2019/fixture--371d0c82ed.pdf"
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("h2e_materialize_rehearsal_inputs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _placement_row(content_sha256: str) -> str:
    headings = (
        "sha256\tscope\tfamille\tmatiere_ou_rubrique\tniveau\ttype_document\tannee\t"
        "statut\ttitre\turl_source\tobjet_source\tchemin_technique_existant\t"
        "chemin_par_niveau\tchemin_par_scope\ttaille_octets\tpages\tstatut_telechargement\n"
    )
    row = "\t".join(
        (
            content_sha256,
            "lycee/arts/theatre",
            "lycee-arts",
            "theatre",
            "multi-niveaux",
            "programme-officiel",
            "2019",
            "actuel",
            "Programme arts",
            "https://eduscol.education.gouv.fr/arts",
            f"objects/sha256/{content_sha256[:2]}/{content_sha256}.pdf",
            PDF_REMOTE_PATH,
            "par-niveau/multi-niveaux/arts.pdf",
            "par-scope/lycee/arts/theatre/arts.pdf",
            "24",
            "1",
            "ok",
        )
    )
    return headings + row + "\n"


def _fixture_inputs(tmp_path: Path) -> dict[str, Any]:
    remote = tmp_path / "remote"
    (remote / "00_ADMIN").mkdir(parents=True)
    catalog_remote = remote / "00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES"
    catalog_remote.mkdir(parents=True)
    pdf_remote = remote / PDF_REMOTE_PATH
    pdf_remote.parent.mkdir(parents=True)
    pdf = b"%PDF-1.7\nH2E bounded fixture\n%%EOF\n"
    pdf_sha = _sha256(pdf)
    pdf_remote.write_bytes(pdf)
    manifest = f"{pdf_sha}  {PDF_REMOTE_PATH}\n".encode()
    manifest_sha = _sha256(manifest)
    (remote / "00_ADMIN/SHA256SUMS.txt").write_bytes(manifest)
    (catalog_remote / "catalogue-complet.tsv").write_text(
        _placement_row(pdf_sha), encoding="utf-8"
    )

    routing = tmp_path / "corpus_zone_routing.yml"
    routing.write_text(
        yaml.safe_dump(
            {
                "config_id": "h2e-materializer-test-v1",
                "manifest_sha256": manifest_sha,
                "zone_rules": [
                    {
                        "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                        "sub_zone_routing": [
                            {
                                "sub_zone_suffix": "/10_ACTUEL_CONFIRME/",
                                "disposition": "INGEST",
                                "currentness": "actuel",
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rights = tmp_path / "rights_evidence_registry.yml"
    rights.write_text(
        yaml.safe_dump(
            {
                "registry_id": "h2e-rights-test-v1",
                "status": "HUMAN_ORGANIZATIONAL_DECISIONS_RECORDED",
                "human_rights_decisions": {
                    "eduscol": {
                        "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                        "decision_maker": "Nexus Réussite",
                        "decision_date": "2026-08-09",
                        "scope_manifest_sha256": manifest_sha,
                        "scope_zone": "01_EDUSCOL_OFFICIEL/",
                        "approved_for_production_rag": True,
                        "generic_rights_blocker": False,
                    }
                },
                "source_evidence": {
                    "eduscol": {
                        "zone": "01_EDUSCOL_OFFICIEL/",
                        "rights_status": "CLEARED_BY_HUMAN_DECISION",
                        "rights_decision_ref": "eduscol",
                    }
                },
                "summary": {"unresolved_ingest_capable": 0},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    required_path_digest = _sha256((PDF_REMOTE_PATH + "\n").encode())
    evidence = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": manifest_sha,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "scanner_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
        "required_pdf_path_count": 1,
        "required_pdf_path_set_digest": required_path_digest,
        "summary": {
            "pdf_total": 1,
            "pii_scan_scope": "INITIAL_PRODUCTION_ELIGIBLE_PDFS",
            "pii_scan_required": 1,
            "pii_scan_exempt": 0,
            "sha256_mismatches": 0,
        },
        "results": [
            {
                "content_sha256": pdf_sha,
                "physical_object_count": 1,
                "status": "CLEARED",
                "pii_detected": False,
            }
        ],
    }
    pii = tmp_path / "pii-evidence.json"
    pii.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "remote": remote,
        "routing": routing,
        "rights": rights,
        "pii": pii,
        "pii_sha": _sha256(pii.read_bytes()),
        "pdf_sha": pdf_sha,
        "manifest_sha": manifest_sha,
    }


def _fake_rclone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path) -> Path:
    binary = tmp_path / "bin/rclone"
    binary.parent.mkdir()
    binary.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import shutil
import sys

args = sys.argv[1:]
with pathlib.Path(os.environ["H2E_RCLONE_LOG"]).open("a", encoding="utf-8") as out:
    out.write(json.dumps(args) + "\\n")
if len(args) != 4 or args[0] != "copyto" or args[3] != "--immutable":
    raise SystemExit(97)
prefix = "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY/"
if not args[1].startswith(prefix):
    raise SystemExit(98)
relative = args[1][len(prefix):]
origin = pathlib.Path(os.environ["H2E_FAKE_REMOTE"]) / relative
target = pathlib.Path(args[2])
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(origin, target)
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    log = tmp_path / "rclone.jsonl"
    monkeypatch.setenv("PATH", f"{binary.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("H2E_FAKE_REMOTE", str(source))
    monkeypatch.setenv("H2E_RCLONE_LOG", str(log))
    return log


def _run_materializer(
    module: ModuleType,
    fixture: dict[str, Any],
    scratch: Path,
    output: Path,
) -> dict[str, Any]:
    module.REAL_SHA256 = fixture["pdf_sha"]
    module.EXPECTED_MANIFEST_SHA256 = fixture["manifest_sha"]
    module.EXPECTED_PII_EVIDENCE_SHA256 = fixture["pii_sha"]
    module.EXPECTED_REAL_PLACEMENTS = 1
    return module.materialize_rehearsal_inputs(
        scratch_dir=scratch,
        pii_evidence_path=fixture["pii"],
        output_manifest_path=output,
        routing_config_path=fixture["routing"],
        rights_registry_path=fixture["rights"],
    )


def test_materializes_exactly_three_read_only_objects_and_compiles_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    fixture = _fixture_inputs(tmp_path)
    scratch = Path("/tmp") / f"nexus-h2e.pytest-{os.getpid()}-{tmp_path.name}"
    scratch.mkdir(mode=0o700)
    try:
        log = _fake_rclone(tmp_path, monkeypatch, fixture["remote"])
        output = scratch / "inputs.json"
        document = _run_materializer(module, fixture, scratch, output)

        commands = [json.loads(line) for line in log.read_text().splitlines()]
        assert len(commands) == 3
        assert [command[0] for command in commands] == ["copyto"] * 3
        assert all(command[1].startswith(REMOTE_ROOT + "/") for command in commands)
        assert [command[1].removeprefix(REMOTE_ROOT + "/") for command in commands] == [
            "00_ADMIN/SHA256SUMS.txt",
            "00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES/catalogue-complet.tsv",
            PDF_REMOTE_PATH,
        ]
        flattened = " ".join(part for command in commands for part in command)
        assert all(verb not in flattened.split() for verb in ("sync", "delete", "move", "copy"))
        assert all(not command[2].startswith("gdrive_ert:") for command in commands)

        assert document == json.loads(output.read_text(encoding="utf-8"))
        assert document["pdf_sha256"] == fixture["pdf_sha"]
        assert document["catalog_sha256"] == _sha256(
            Path(document["catalog_path"]).read_bytes()
        )
        assert document["pii_evidence_sha256"] == fixture["pii_sha"]
        assert document["manifest_sha256"] == fixture["manifest_sha"]
        assert document["remote_write_operations"] == 0
        catalog = json.loads(Path(document["catalog_path"]).read_text(encoding="utf-8"))
        assert document["placement_catalog_sha256"] == catalog["placement_catalog_sha256"]
        assert catalog["catalog_kind"] == "REAL_SEALED_CORPUS"
        assert catalog["artifacts"][fixture["pdf_sha"]]["pedagogical_placement_count"] == 1
        assert catalog["artifacts"][fixture["pdf_sha"]]["physical_objects"][0][
            "gate_statuses"
        ]["authority"] == "BLOCKED_NOT_CLEARED"
    finally:
        if scratch.is_dir():
            for child in sorted(scratch.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            scratch.rmdir()


def test_rejects_unbounded_scratch_before_rclone(tmp_path: Path) -> None:
    module = _module()
    fixture = _fixture_inputs(tmp_path)
    with pytest.raises(ValueError, match="bounded /tmp/nexus-h2e"):
        _run_materializer(module, fixture, tmp_path / "scratch", tmp_path / "inputs.json")


@pytest.mark.parametrize("drift", ["manifest", "pii", "pdf"])
def test_rejects_every_sealed_input_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    module = _module()
    fixture = _fixture_inputs(tmp_path)
    scratch = Path("/tmp") / f"nexus-h2e.pytest-{os.getpid()}-{tmp_path.name}-{drift}"
    scratch.mkdir(mode=0o700)
    try:
        _fake_rclone(tmp_path, monkeypatch, fixture["remote"])
        if drift == "manifest":
            (fixture["remote"] / "00_ADMIN/SHA256SUMS.txt").write_bytes(b"drift")
        elif drift == "pii":
            fixture["pii"].write_bytes(fixture["pii"].read_bytes() + b" ")
        else:
            (fixture["remote"] / PDF_REMOTE_PATH).write_bytes(b"different bytes")
        with pytest.raises(RuntimeError, match=f"{drift.upper()}_SHA256_MISMATCH"):
            _run_materializer(module, fixture, scratch, scratch / "inputs.json")
    finally:
        if scratch.is_dir():
            for child in sorted(scratch.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            scratch.rmdir()


def test_rejects_scratch_with_group_or_other_permissions(tmp_path: Path) -> None:
    module = _module()
    fixture = _fixture_inputs(tmp_path)
    scratch = Path("/tmp") / f"nexus-h2e.pytest-{os.getpid()}-{tmp_path.name}-mode"
    scratch.mkdir(mode=0o755)
    try:
        with pytest.raises(ValueError, match="mode 0700"):
            _run_materializer(module, fixture, scratch, scratch / "inputs.json")
        assert scratch.stat().st_mode & 0o777 == 0o755
    finally:
        scratch.rmdir()


@pytest.mark.parametrize(
    "planted_name",
    [
        "SHA256SUMS.txt",
        "catalogue-complet.tsv",
        "371d0c82ed.pdf",
        "h2e_governed_catalog.json",
        "inputs.json",
    ],
)
def test_rejects_every_planted_final_target_before_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    planted_name: str,
) -> None:
    module = _module()
    fixture = _fixture_inputs(tmp_path)
    scratch = Path("/tmp") / (
        f"nexus-h2e.pytest-{os.getpid()}-{tmp_path.name}-{planted_name.replace('.', '-')}"
    )
    scratch.mkdir(mode=0o700)
    planted = scratch / planted_name
    planted.write_text("keep", encoding="utf-8")
    try:
        _fake_rclone(tmp_path, monkeypatch, fixture["remote"])
        with pytest.raises(RuntimeError, match="LOCAL_MATERIALIZATION_TARGET_EXISTS"):
            _run_materializer(module, fixture, scratch, scratch / "inputs.json")
        assert planted.read_text(encoding="utf-8") == "keep"
    finally:
        for child in scratch.iterdir():
            child.unlink()
        scratch.rmdir()


def test_rejects_broken_destination_symlink_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    fixture = _fixture_inputs(tmp_path)
    scratch = Path("/tmp") / f"nexus-h2e.pytest-{os.getpid()}-{tmp_path.name}-broken"
    scratch.mkdir(mode=0o700)
    missing = tmp_path / "outside-missing"
    (scratch / "SHA256SUMS.txt").symlink_to(missing)
    try:
        _fake_rclone(tmp_path, monkeypatch, fixture["remote"])
        with pytest.raises(RuntimeError, match="LOCAL_MATERIALIZATION_TARGET_EXISTS"):
            _run_materializer(module, fixture, scratch, scratch / "inputs.json")
        assert not missing.exists()
    finally:
        (scratch / "SHA256SUMS.txt").unlink()
        scratch.rmdir()


def test_rejects_json_temp_symlink_escape_and_preserves_outside_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    fixture = _fixture_inputs(tmp_path)
    scratch = Path("/tmp") / f"nexus-h2e.pytest-{os.getpid()}-{tmp_path.name}-temp"
    scratch.mkdir(mode=0o700)
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    planted = scratch / "h2e_governed_catalog.json.tmp"
    planted.symlink_to(outside)
    try:
        _fake_rclone(tmp_path, monkeypatch, fixture["remote"])
        with pytest.raises(RuntimeError, match="LOCAL_MATERIALIZATION_TARGET_EXISTS"):
            _run_materializer(module, fixture, scratch, scratch / "inputs.json")
        assert outside.read_text(encoding="utf-8") == "keep"
    finally:
        for child in scratch.iterdir():
            child.unlink()
        scratch.rmdir()
