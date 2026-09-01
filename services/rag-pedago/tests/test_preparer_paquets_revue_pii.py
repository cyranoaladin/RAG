"""Paquets de revue PII, hors dépôt, figés par empreinte (ADR-0047 § 2).

Un reviewer statue sur un paquet généré depuis les octets exacts du PDF, lié au
scanner et à la politique exacts, paginé, contextualisé, figé par SHA-256 et
invalidé par toute modification. Le dépôt ne garde que l'index, sans matière.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.test_pii_scanner_pages_sans_texte import _PAGE_AVEC_TEXTE, _pdf

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
POLICY = SCRIPT_DIR.parent / "configs" / "pii_gate_policy.yml"
_PAGE_AVEC_COURRIEL = b"BT /F1 12 Tf 72 720 Td (Contact : m.durand@courrier-prive.org) Tj ET"
_PAGE_AVEC_TELEPHONE = b"BT /F1 12 Tf 72 720 Td (Standard : 01 23 45 67 89) Tj ET"


def _module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "preparer_paquets_revue_pii", SCRIPT_DIR / "preparer_paquets_revue_pii.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corpus(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / "miroir"
    root.mkdir()
    documents = {
        "clair": _pdf([_PAGE_AVEC_TEXTE]),
        "detecte": _pdf([_PAGE_AVEC_TEXTE, _PAGE_AVEC_COURRIEL, _PAGE_AVEC_TELEPHONE]),
    }
    shas = {}
    for name, content in documents.items():
        sha = hashlib.sha256(content).hexdigest()
        (root / f"{sha}.pdf").write_bytes(content)
        shas[name] = sha
    placements = tmp_path / "placements.json"
    placements.write_text(
        json.dumps(
            {
                shas["detecte"]: {
                    "title": "Document détecté",
                    "source_path": "01_EDUSCOL_OFFICIEL/x/detecte.pdf",
                    "placements": ["rag_nexus_nsi_premiere_specialite", "rag_nexus_nsi_terminale_specialite"],
                },
                shas["clair"]: {
                    "title": "Document clair",
                    "source_path": "01_EDUSCOL_OFFICIEL/x/clair.pdf",
                    "placements": ["rag_nexus_svt_premiere_specialite"],
                },
            }
        ),
        encoding="utf-8",
    )
    return root, placements, shas


def test_bundles_are_generated_only_for_detected_contents_and_sealed(tmp_path: Path) -> None:
    preparer = _module()
    root, placements, shas = _corpus(tmp_path)
    out = tmp_path / "revue"
    index_path = tmp_path / "index.json"

    index = preparer.preparer(
        pdf_root=root,
        content_sha256=sorted(shas.values()),
        placements_path=placements,
        policy_path=POLICY,
        output_root=out,
        index_path=index_path,
        campaign_id="pii-review-test",
    )

    assert index["protocol_version"] == "NEXUS-PII-REVIEW-INDEX-V1"
    assert index["campaign_id"] == "pii-review-test"
    assert [b["content_sha256"] for b in index["bundles"]] == [shas["detecte"]]
    bundle = index["bundles"][0]
    assert bundle["signal_classes"] == ["email_address", "phone_french"]
    assert bundle["signal_count"] == 2
    assert bundle["pages"] == [2, 3]
    assert bundle["placements"] == ["rag_nexus_nsi_premiere_specialite", "rag_nexus_nsi_terminale_specialite"]
    assert bundle["title"] == "Document détecté"
    bundle_dir = out / shas["detecte"]
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["protocol_version"] == "NEXUS-PII-REVIEW-BUNDLE-V1"
    assert manifest["content_sha256"] == shas["detecte"]
    assert manifest["policy_sha256"] == _sha(POLICY)
    assert len(manifest["scanner_sha256"]) == 64 and len(manifest["page_policy_sha256"]) == 64
    assert bundle["bundle_sha256"] == _sha(bundle_dir / "manifest.json")
    assert manifest["files"]["document.pdf"] == shas["detecte"]
    assert (bundle_dir / "document.pdf").read_bytes() == (root / f"{shas['detecte']}.pdf").read_bytes()
    for page in (2, 3):
        page_file = bundle_dir / "pages" / f"page-{page:04d}.txt"
        assert manifest["files"][f"pages/page-{page:04d}.txt"] == _sha(page_file)
    signals = manifest["signals"]
    assert [s["pattern_id"] for s in signals] == ["email_address", "phone_french"]
    assert signals[0]["page_number"] == 2 and "durand" in signals[0]["match_text"]
    assert "durand" in signals[0]["context"]
    assert "durand" in (bundle_dir / "pages" / "page-0002.txt").read_text(encoding="utf-8")
    # L'index versionné ne porte aucune matière brute.
    serialised = json.dumps(index, ensure_ascii=False) + index_path.read_text(encoding="utf-8")
    assert "durand" not in serialised and "01 23 45" not in serialised
    assert index["index_sha256_excluded"] is True
    assert not (out / shas["clair"]).exists()


def test_verification_detects_any_modification_after_generation(tmp_path: Path) -> None:
    preparer = _module()
    root, placements, shas = _corpus(tmp_path)
    out = tmp_path / "revue"
    index_path = tmp_path / "index.json"
    preparer.preparer(
        pdf_root=root, content_sha256=sorted(shas.values()), placements_path=placements,
        policy_path=POLICY, output_root=out, index_path=index_path, campaign_id="pii-review-test",
    )
    assert preparer.verifier(output_root=out, index_path=index_path) == []
    page = out / shas["detecte"] / "pages" / "page-0002.txt"
    page.write_text(page.read_text(encoding="utf-8") + " ", encoding="utf-8")
    problemes = preparer.verifier(output_root=out, index_path=index_path)
    assert problemes and "page-0002.txt" in problemes[0]
    manifest = out / shas["detecte"] / "manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("\n", "\n", 1) + "\n", encoding="utf-8")
    assert any("manifest" in p for p in preparer.verifier(output_root=out, index_path=index_path))


def test_a_mirror_file_that_does_not_match_its_name_is_refused(tmp_path: Path) -> None:
    preparer = _module()
    root, placements, shas = _corpus(tmp_path)
    (root / f"{shas['detecte']}.pdf").write_bytes(_pdf([_PAGE_AVEC_TELEPHONE]))
    with pytest.raises(ValueError, match="does not match"):
        preparer.preparer(
            pdf_root=root, content_sha256=sorted(shas.values()), placements_path=placements,
            policy_path=POLICY, output_root=tmp_path / "revue", index_path=tmp_path / "index.json",
            campaign_id="pii-review-test",
        )


def test_generation_is_deterministic(tmp_path: Path) -> None:
    preparer = _module()
    root, placements, shas = _corpus(tmp_path)
    first = preparer.preparer(
        pdf_root=root, content_sha256=sorted(shas.values()), placements_path=placements,
        policy_path=POLICY, output_root=tmp_path / "a", index_path=tmp_path / "a.json",
        campaign_id="pii-review-test",
    )
    second = preparer.preparer(
        pdf_root=root, content_sha256=sorted(shas.values()), placements_path=placements,
        policy_path=POLICY, output_root=tmp_path / "b", index_path=tmp_path / "b.json",
        campaign_id="pii-review-test",
    )
    assert first["bundles"][0]["bundle_sha256"] == second["bundles"][0]["bundle_sha256"]
