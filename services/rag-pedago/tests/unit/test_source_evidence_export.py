"""Tests de l'export versionne des preuves de validation des sources
(revue PR #74, round 6 : pas de bascule `verified` sans preuve auditable)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

_SPEC = importlib.util.spec_from_file_location(
    "export_source_validation_evidence",
    Path(__file__).resolve().parents[2] / "scripts"
    / "export_source_validation_evidence.py",
)
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)
export = _mod.export


def _verdict(source_id: str, url: str, verdict: str = "verified_candidate") -> dict:
    return {
        "source_id": source_id,
        "url": url,
        "final_url": url,
        "content_sha256": "ab" * 32,
        "verdict": verdict,
        "reasons": ["ok"],
        "validator": "source_validator_v3",
        "signature": "0123456789abcdef",
        "ts": "2026-07-26T00:00:00+00:00",
    }


def _setup(tmp_path: Path, ledger_lines: list[dict], sources: list[dict]):
    ledger = tmp_path / "data" / "ledger" / "source_validation.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in ledger_lines),
        encoding="utf-8")
    sources_yml = tmp_path / "configs" / "eduscol_sources.yml"
    sources_yml.parent.mkdir(parents=True, exist_ok=True)
    sources_yml.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    evidence = tmp_path / "docs" / "validation" / "source_validation_evidence.json"
    return ledger, sources_yml, evidence


class TestEvidenceExport:
    def test_export_writes_signed_verdicts(self, tmp_path):
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_langues", "https://eduscol.education.gouv.fr/5811"),
             {"run_at": "2026-07-26T00:00:00+00:00", "candidates": 1}],  # resume exclu
            [{"id": "eduscol_langues", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/5811"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 0, msg
        data = json.loads(evidence.read_text(encoding="utf-8"))
        assert data["verdicts_count"] == 1
        v = data["verdicts"][0]
        assert v["source_id"] == "eduscol_langues"
        assert v["content_sha256"] == "ab" * 32
        assert v["signature"] == "0123456789abcdef"
        assert len(data["ledger_sha256"]) == 64

    def test_verified_source_without_verdict_violates(self, tmp_path):
        """Une source `verified` suivie par le ledger avec un verdict
        defavorable ne doit PAS etre activee (fail-closed)."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_pc", "https://eduscol.education.gouv.fr/5829",
                      verdict="stays_to_verify")],
            [{"id": "eduscol_pc", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/5829"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "eduscol_pc" in msg
        assert not evidence.is_file()

    def test_url_divergence_violates(self, tmp_path):
        """L'URL validee doit correspondre a l'URL configuree : une bascule
        sur une URL differente de celle relue est refusee."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536")],
            [{"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/9999"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "url divergente" in msg

    def test_legacy_verified_source_out_of_scope(self, tmp_path):
        """Les sources verifiees avant LOT 31 (absentes du ledger) ne
        bloquent pas l'export."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536")],
            [{"id": "eduscol_maths_old", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/1"},
             {"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 0, msg

    def test_missing_ledger_refused(self, tmp_path):
        sources_yml = tmp_path / "eduscol_sources.yml"
        sources_yml.write_text(yaml.safe_dump({"sources": []}), encoding="utf-8")
        code, msg = export(tmp_path / "absent.jsonl", sources_yml,
                           tmp_path / "evidence.json")
        assert code == 1
        assert "AUCUN verdict" in msg
