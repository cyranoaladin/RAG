"""Rescan PII d'un ensemble de contenus, sous une politique et un scanner nommés.

Le rescan est une MESURE datée, jamais une correction rétroactive d'une preuve
antérieure : il nomme la politique, le scanner, le foyer de pages et le runtime
qui l'ont rendue, et ne transporte aucune correspondance brute.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rag_pedago.imports import pii_scanner
from tests.test_pii_scanner_pages_sans_texte import _PAGE_AVEC_TEXTE, _pdf

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"

_PAGE_AVEC_COURRIEL = b"BT /F1 12 Tf 72 720 Td (Contact : m.durand@courrier-prive.org) Tj ET"


def _module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rescan_pii_corpus", SCRIPT_DIR / "rescan_pii_corpus.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _mirror(tmp_path: Path, documents: dict[str, bytes]) -> tuple[Path, list[str]]:
    root = tmp_path / "miroir"
    root.mkdir()
    shas = []
    for content in documents.values():
        sha = hashlib.sha256(content).hexdigest()
        (root / f"{sha}.pdf").write_bytes(content)
        shas.append(sha)
    return root, sorted(shas)


def test_rescan_names_its_instruments_and_never_carries_raw_matches(
    tmp_path: Path,
) -> None:
    rescan = _module()
    root, shas = _mirror(
        tmp_path,
        {"clair": _pdf([_PAGE_AVEC_TEXTE]), "detecte": _pdf([_PAGE_AVEC_TEXTE, _PAGE_AVEC_COURRIEL])},
    )
    policy = SCRIPT_DIR.parent / "configs" / "pii_gate_policy.yml"

    document = rescan.rescan(pdf_root=root, content_sha256=shas, policy_path=policy)

    assert document["protocol_version"] == "NEXUS-PII-RESCAN-V1"
    assert document["policy_sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    assert document["scanner_sha256"] == hashlib.sha256(
        Path(pii_scanner.__file__).read_bytes()
    ).hexdigest()
    assert document["page_policy_id"] == "NEXUS-PDF-PAGE-POLICY-V1"
    assert len(document["page_policy_sha256"]) == 64
    assert document["runtime"]["pypdf"]
    assert document["content_set_sha256"] == hashlib.sha256(
        ("\n".join(shas) + "\n").encode()
    ).hexdigest()
    assert document["counts"] == {"scanned": 2, "detected": 1, "clear": 1, "extraction_failed": 0}
    by_sha = {row["content_sha256"]: row for row in document["results"]}
    assert set(by_sha) == set(shas)
    detected = [row for row in by_sha.values() if row["pii_detected"]]
    assert len(detected) == 1
    assert detected[0]["signal_classes"] == ["email_address"]
    assert detected[0]["pages_per_class"] == {"email_address": [2]}
    assert detected[0]["signal_count"] == 1
    serialised = json.dumps(document, ensure_ascii=False)
    assert "durand" not in serialised
    assert "courrier-prive" not in serialised
    assert "raw_pii_in_output" in document and document["raw_pii_in_output"] is False


def test_rescan_refuses_a_mirror_file_whose_bytes_do_not_match_their_name(
    tmp_path: Path,
) -> None:
    rescan = _module()
    root, shas = _mirror(tmp_path, {"clair": _pdf([_PAGE_AVEC_TEXTE])})
    (root / f"{shas[0]}.pdf").write_bytes(_pdf([_PAGE_AVEC_COURRIEL]))
    policy = SCRIPT_DIR.parent / "configs" / "pii_gate_policy.yml"

    with pytest.raises(ValueError, match="does not match"):
        rescan.rescan(pdf_root=root, content_sha256=shas, policy_path=policy)


def test_rescan_refuses_a_missing_content(tmp_path: Path) -> None:
    rescan = _module()
    root, shas = _mirror(tmp_path, {"clair": _pdf([_PAGE_AVEC_TEXTE])})
    policy = SCRIPT_DIR.parent / "configs" / "pii_gate_policy.yml"

    with pytest.raises(FileNotFoundError):
        rescan.rescan(pdf_root=root, content_sha256=[*shas, "f" * 64], policy_path=policy)
