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
check = _mod.check
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
        "validator": "source_validator_v5",
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
        assert data["validator_schema"] == "source_validator_v5"
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
        """Les 9 sources legacy GELEES (id + url) sont exemptees de verdict."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")],
            [{"id": "eduscol_maths_voie_gt", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/5817/"
                     "programmes-et-ressources-en-mathematiques-voie-gt"},
             {"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 0, msg

    def test_unknown_verified_without_verdict_violates(self, tmp_path):
        """Round 9 PR #74 : une source `verified` ABSENTE du ledger et HORS
        liste legacy gelee est une violation — elle ne peut pas se faire
        passer pour une source legacy."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")],
            [{"id": "eduscol_maths_voie_gt", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/5817/"
                     "programmes-et-ressources-en-mathematiques-voie-gt"},
             {"id": "source_injectee", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/9999/x"},
             {"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "source_injectee" in msg
        assert "hors liste legacy" in msg
        assert not evidence.is_file()

    def test_legacy_id_with_wrong_url_violates(self, tmp_path):
        """Round 9 : un id legacy avec une URL differente n'est PAS exempte
        (la liste gelee lie id ET url)."""
        ledger, sources_yml, evidence = _setup(
            tmp_path,
            [_verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")],
            [{"id": "eduscol_maths_voie_gt", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/9999/detourne"},
             {"id": "eduscol_dnb", "status": "verified",
              "url": "https://eduscol.education.gouv.fr/4536/x"}],
        )
        code, msg = export(ledger, sources_yml, evidence)
        assert code == 1
        assert "eduscol_maths_voie_gt" in msg


class TestEvidenceCheck:
    """Controle CI --check (round 11 PR #74) : la preuve COMMITEE doit
    couvrir la config courante, sans dependre du ledger (data/)."""

    def _write_evidence(self, tmp_path, verdicts, schema="source_validator_v5"):
        evidence = tmp_path / "docs" / "validation" / "source_validation_evidence.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({
            "exported_at": "2026-07-27T00:00:00+00:00",
            "validator_schema": schema,
            "ledger_sha256": "ab" * 32,
            "verdicts_count": len(verdicts),
            "verdicts": verdicts,
        }, ensure_ascii=False), encoding="utf-8")
        return evidence

    def _write_sources(self, tmp_path, sources):
        sources_yml = tmp_path / "configs" / "eduscol_sources.yml"
        sources_yml.parent.mkdir(parents=True, exist_ok=True)
        sources_yml.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
        return sources_yml

    def test_check_ok(self, tmp_path):
        evidence = self._write_evidence(tmp_path, [
            _verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")])
        sources_yml = self._write_sources(tmp_path, [
            {"id": "eduscol_dnb", "status": "verified",
             "url": "https://eduscol.education.gouv.fr/4536/x"},
            {"id": "eduscol_maths_voie_gt", "status": "verified",
             "url": "https://eduscol.education.gouv.fr/5817/"
                    "programmes-et-ressources-en-mathematiques-voie-gt"}])
        code, msg = check(evidence, sources_yml)
        assert code == 0, msg

    def test_check_refuses_uncovered_verified(self, tmp_path):
        """Une source non-legacy passee en verified SANS reexport = echec CI."""
        evidence = self._write_evidence(tmp_path, [
            _verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")])
        sources_yml = self._write_sources(tmp_path, [
            {"id": "eduscol_dnb", "status": "verified",
             "url": "https://eduscol.education.gouv.fr/4536/x"},
            {"id": "source_activee_sans_preuve", "status": "verified",
             "url": "https://eduscol.education.gouv.fr/9999/x"}])
        code, msg = check(evidence, sources_yml)
        assert code == 1
        assert "source_activee_sans_preuve" in msg

    def test_check_refuses_stale_schema(self, tmp_path):
        evidence = self._write_evidence(tmp_path, [
            _verdict("eduscol_dnb", "https://eduscol.education.gouv.fr/4536/x")],
            schema="source_validator_v4")
        sources_yml = self._write_sources(tmp_path, [])
        code, msg = check(evidence, sources_yml)
        assert code == 1
        assert "schema perime" in msg

    def test_check_refuses_missing_evidence(self, tmp_path):
        sources_yml = self._write_sources(tmp_path, [])
        code, msg = check(tmp_path / "absent.json", sources_yml)
        assert code == 1
        assert "preuve absente" in msg

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
