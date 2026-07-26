"""Tests de l'export versionne des preuves de validation des sources
(revue PR #74, rounds 6-7 : pas de bascule `verified` sans preuve
auditable, integree et recalculable cryptographiquement)."""
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
recompute_signature = _mod.recompute_signature


def _verdict(source_id: str, url: str,
             verdict: str = "verified_candidate",
             sign: bool = True) -> dict:
    """Verdict au schema v3, signe correctement (sauf sign=False)."""
    v = {
        "source_id": source_id,
        "url": url,
        "final_url": url,
        "content_sha256": "ab" * 32,
        "final_rights": "official_public_administrative",
        "verdict": verdict,
        "http_status": 200,
        "words": 1500,
        "rules_fired": ["subject_expert:approved"],
        "reasons": ["ok"],
        "validated_at": "2026-07-27T00:00:00+00:00",
        "validator": "source_validator_v3",
    }
    v["signature"] = recompute_signature(v) if sign else "0" * 16
    return v


def _setup(tmp_path: Path, ledger_lines: list, sources: list[dict]):
    ledger = tmp_path / "data" / "ledger" / "source_validation.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "".join((json.dumps(e, ensure_ascii=False) if isinstance(e, dict) else e)
                + "\n" for e in ledger_lines),
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
            [_verdict("eduscol_langues_voie_gt",
                      "https://eduscol.education.gouv.fr/5811/x"),
             {"run_at": "2026-07-27T00:00:00+00:00", "candidates": 1}],
            [{"id": "eduscol_langues_voie_gt", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/5811/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 0, msg
        data = json.loads(evidence.read_text(encoding="utf-8"))
        assert data["verdicts_count"] == 1
        assert data["validator_schema"] == "source_validator_v3"
        v = data["verdicts"][0]
        assert v["content_sha256"] == "ab" * 32
        assert len(v["signature"]) == 16
        assert len(data["ledger_sha256"]) == 64

    def test_verified_source_without_verdict_violates(self, tmp_path):
        """Une source `verified` suivie par le ledger avec un verdict
        defavorable ne doit PAS etre activee (fail-closed)."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_pc", "https://eduscol.education.gouv.fr/5829/x",
                      verdict="stays_to_verify")],
            [{"id": "eduscol_pc", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/5829/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "eduscol_pc" in msg
        assert not evidence.is_file()

    def test_url_divergence_violates(self, tmp_path):
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")],
            [{"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/9999/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "url divergente" in msg

    def test_legacy_verified_source_out_of_scope(self, tmp_path):
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")],
            [{"id": "eduscol_maths_old", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/1"},
             {"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 0, msg

    def test_missing_ledger_refused(self, tmp_path):
        sources_yml = tmp_path / "eduscol_sources.yml"
        sources_yml.write_text(yaml.safe_dump({"sources": []}), encoding="utf-8")
        code, msg = export(tmp_path / "absent.jsonl", sources_yml,
                           tmp_path / "evidence.json")
        assert code == 1

    def test_malformed_ledger_line_refused(self, tmp_path):
        """Round 7 : une ligne corrompue (append interrompu) refuse l'export —
        un vieux verdict ne doit pas paraitre courant."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x"),
             '{"source_id": "eduscol_dnb", "verdict": "verified_cand'],  # tronque
            [{"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "LEDGER INVALIDE" in msg
        assert "ligne 2" in msg
        assert not evidence.is_file()

    def test_forged_signature_refused(self, tmp_path):
        """Round 7 : une entree fabriquee (signature non recalculable) est
        rejetee — elle ne peut pas autoriser l'ingestion."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x",
                      sign=False)],
            [{"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "signature non recalculable" in msg

    def test_v2_schema_verdict_refused(self, tmp_path):
        """Round 7 : un verdict v2 (sans content_sha256/final_url) est
        perime — l'activation exige le schema courant lie au contenu."""
        v2 = {
            "source_id": "eduscol_dnb",
            "url": "https://eduscol.education.gouv.fr/4536/x",
            "verdict": "verified_candidate",
            "reasons": ["ok"],
            "validator": "source_validator_v2",
            "signature": "ab" * 8,
        }
        ledger, sources_yml, evidence = _setup(
            tmp_path, [v2],
            [{"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "VERDICTS NON CONFORMES" in msg
        assert not evidence.is_file()
