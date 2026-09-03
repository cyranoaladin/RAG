"""Dérivation d'un registre de contenus successeur, sans réécriture historique.

Un artefact historique ne change pas de sens sous le même nom : le registre du
14/08 reste à son état attesté, et un successeur daté est DÉRIVÉ par exécution
depuis ce registre et des rectifications déclarées, chacune adossée à une
preuve nommée par son empreinte. La provenance est écrite à côté de la sortie.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "deriver_content_ledger", SCRIPT_DIR / "deriver_content_ledger.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(sha: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "content_sha256": sha,
        "PII": "CLEARED",
        "CURRENTNESS": "unclassified",
        "RIGHTS": "CLEARED_BY_HUMAN_DECISION",
        "EXTRACTABILITY": "EXTRACTABLE",
        "ROUTING_BASELINE": "REVIEW_REQUIRED",
        "FINAL_DISPOSITION": "REVIEW_REQUIRED",
        "REASON_CODES": ["ROUTING_EDUSCOL_A_VERIFIER"],
        "EVIDENCE_SOURCES": ["corpus_zone_routing.yml"],
        "PLACEMENT_COUNT": 1,
        "PLACEMENT_PATHS": [f"01_EDUSCOL_OFFICIEL/x/{sha[:10]}.pdf"],
    }
    row.update(overrides)
    return row


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "content_ledger_20260814.jsonl"
    rows = [
        _row("a" * 64),
        _row("b" * 64, PII="REVIEW_REQUIRED", EXTRACTABILITY="EXTRACTION_FAILED",
             REASON_CODES=["PII_EXTRACTION_FAILED:PDF_PAGE_TEXT_EXTRACTION_EMPTY", "ROUTING_EDUSCOL_A_VERIFIER"]),
        _row("c" * 64),
    ]
    source.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    evidence = tmp_path / "pii_rescan.json"
    evidence.write_text('{"protocol_version": "NEXUS-PII-RESCAN-V1"}\n', encoding="utf-8")
    rectifications = tmp_path / "rectifications.json"
    rectifications.write_text(
        json.dumps(
            {
                "schema_version": "NEXUS-LEDGER-RECTIFICATIONS-V1",
                "date": "2026-09-02",
                "source_ledger": {"path": source.name, "sha256": _sha(source)},
                "evidences": {"rescan": {"path": evidence.name, "sha256": _sha(evidence)}},
                "rectifications": [
                    {
                        "content_sha256": "b" * 64,
                        "champs": {
                            "EXTRACTABILITY": {"avant": "EXTRACTION_FAILED", "apres": "EXTRACTABLE"},
                            "PII": {"avant": "REVIEW_REQUIRED", "apres": "CLEARED"},
                        },
                        "reason_codes_retires": ["PII_EXTRACTION_FAILED:PDF_PAGE_TEXT_EXTRACTION_EMPTY"],
                        "reason_codes_ajoutes": ["PII_RESCAN_POLICY_V5_CLEAR:pii_rescan"],
                        "evidence_sources_ajoutes": ["pii_rescan.json"],
                        "evidences": ["rescan"],
                        "motif": "Pages 2 et 54 structurellement vides ; 0 detection sous v5.",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return source, rectifications, evidence


def test_derivation_applies_exactly_the_declared_rectifications_and_writes_provenance(
    tmp_path: Path,
) -> None:
    deriver = _module()
    source, rectifications, evidence = _fixture(tmp_path)
    sortie = tmp_path / "content_ledger_20260902.jsonl"

    provenance = deriver.deriver(
        source=source, rectifications=rectifications, sortie=sortie, base_dir=tmp_path
    )

    rows = [json.loads(line) for line in sortie.read_text(encoding="utf-8").splitlines()]
    assert [r["content_sha256"] for r in rows] == ["a" * 64, "b" * 64, "c" * 64]
    assert rows[0] == _row("a" * 64)
    assert rows[1]["EXTRACTABILITY"] == "EXTRACTABLE"
    assert rows[1]["PII"] == "CLEARED"
    assert rows[1]["REASON_CODES"] == ["PII_RESCAN_POLICY_V5_CLEAR:pii_rescan", "ROUTING_EDUSCOL_A_VERIFIER"]
    assert rows[1]["EVIDENCE_SOURCES"] == ["corpus_zone_routing.yml", "pii_rescan.json"]
    assert "RECTIFICATION" not in rows[1]
    assert set(rows[1]) == set(_row("x" * 64))
    sidecar = json.loads((tmp_path / "content_ledger_20260902.provenance.json").read_text())
    assert sidecar == provenance
    assert sidecar["schema_version"] == "NEXUS-DERIVED-LEDGER-PROVENANCE-V1"
    assert sidecar["supersedes"] == {"path": source.name, "sha256": _sha(source)}
    assert sidecar["entrees"][rectifications.name] == _sha(rectifications)
    assert sidecar["entrees"][evidence.name] == _sha(evidence)
    assert sidecar["sortie"] == {sortie.name: _sha(sortie)}
    assert sidecar["lignes_avant"] == 3 and sidecar["lignes_apres"] == 3
    assert sidecar["rectifications_appliquees"] == 1
    assert sidecar["contenus_rectifies"] == ["b" * 64]


def test_derivation_refuses_a_source_whose_digest_differs_from_the_declaration(
    tmp_path: Path,
) -> None:
    deriver = _module()
    source, rectifications, _evidence = _fixture(tmp_path)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source ledger digest"):
        deriver.deriver(
            source=source, rectifications=rectifications, sortie=tmp_path / "out.jsonl", base_dir=tmp_path
        )


def test_derivation_refuses_a_rectification_whose_before_value_is_not_observed(
    tmp_path: Path,
) -> None:
    deriver = _module()
    source, rectifications, _evidence = _fixture(tmp_path)
    document = json.loads(rectifications.read_text(encoding="utf-8"))
    document["rectifications"][0]["champs"]["PII"]["avant"] = "CLEARED"
    rectifications.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="avant"):
        deriver.deriver(
            source=source, rectifications=rectifications, sortie=tmp_path / "out.jsonl", base_dir=tmp_path
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda d: d["rectifications"][0].__setitem__("content_sha256", "f" * 64), "unknown content"),
        (lambda d: d["evidences"]["rescan"].__setitem__("sha256", "0" * 64), "evidence digest"),
        (lambda d: d["rectifications"][0]["reason_codes_retires"].append("ABSENT"), "reason code"),
        (lambda d: d["rectifications"][0]["champs"].__setitem__("PLACEMENT_COUNT", {"avant": 1, "apres": 2}), "not rectifiable"),
        (lambda d: d["rectifications"][0].__setitem__("evidences", []), "evidence"),
    ],
)
def test_derivation_refuses_incoherent_rectifications(tmp_path: Path, mutation, message: str) -> None:
    deriver = _module()
    source, rectifications, _evidence = _fixture(tmp_path)
    document = json.loads(rectifications.read_text(encoding="utf-8"))
    mutation(document)
    rectifications.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        deriver.deriver(
            source=source, rectifications=rectifications, sortie=tmp_path / "out.jsonl", base_dir=tmp_path
        )


def test_derivation_is_idempotent(tmp_path: Path) -> None:
    deriver = _module()
    source, rectifications, _evidence = _fixture(tmp_path)
    sortie = tmp_path / "content_ledger_20260902.jsonl"
    first = deriver.deriver(source=source, rectifications=rectifications, sortie=sortie, base_dir=tmp_path)
    digest = _sha(sortie)
    second = deriver.deriver(source=source, rectifications=rectifications, sortie=sortie, base_dir=tmp_path)
    assert _sha(sortie) == digest
    assert {k: v for k, v in first.items() if k != "derive_le"} == {
        k: v for k, v in second.items() if k != "derive_le"
    }
