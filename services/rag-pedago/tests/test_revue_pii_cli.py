"""L'outil de revue guidée écrit un brouillon scellable depuis les choix du reviewer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.test_pii_scanner_pages_sans_texte import _PAGE_AVEC_TEXTE, _pdf

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
POLICY = SCRIPT_DIR.parent / "configs" / "pii_gate_policy.yml"


def _load(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guided_review_produces_a_sealable_draft(tmp_path: Path) -> None:
    preparer = _load("preparer_paquets_revue_pii")
    revue = _load("revue_pii_cli")
    sceller = _load("sceller_decisions_pii")
    root = tmp_path / "miroir"
    root.mkdir()
    pdf = _pdf([_PAGE_AVEC_TEXTE, b"BT /F1 12 Tf 72 720 Td (Standard : 01 23 45 67 89) Tj ET"])
    sha = hashlib.sha256(pdf).hexdigest()
    (root / f"{sha}.pdf").write_bytes(pdf)
    placements = tmp_path / "placements.json"
    placements.write_text(json.dumps({sha: {"title": "t", "source_path": "x.pdf", "placements": ["c"]}}))
    index_path = tmp_path / "index.json"
    preparer.preparer(
        pdf_root=root, content_sha256=[sha], placements_path=placements, policy_path=POLICY,
        output_root=tmp_path / "revue", index_path=index_path, campaign_id="pii-review-test",
        require_frozen=False,
    )
    reponses = iter(["2", "1", "1", "Numéro de standard d'un établissement, en-tête de document officiel."])
    lignes: list[str] = []
    draft = tmp_path / "decisions.draft.json"

    brouillon = revue.revoir(
        index_path=index_path, bundles_root=tmp_path / "revue", draft=draft,
        reviewer_login="abenrhouma", corpus_manifest_sha256="7" * 64,
        ask=lambda _p: next(reponses), out=lignes.append,
    )

    assert "01 23 45 67 89" in "\n".join(lignes)  # la matière est montrée localement…
    entry = brouillon["decisions"][sha]
    assert entry["decision"] == "APPROVED"
    assert {d["disposition"] for d in entry["findings"].values()} == {"PUBLIC_INSTITUTIONAL_DATA"}
    sortie = tmp_path / "pii-review-test.json"
    digest = sceller.sceller(draft=draft, index_path=index_path, sortie=sortie)
    assert len(digest) == 64
    assert "01 23 45" not in sortie.read_text(encoding="utf-8")  # …jamais dans l'artefact versionnable


def test_a_personal_finding_forbids_approval_in_the_guided_review(tmp_path: Path) -> None:
    preparer = _load("preparer_paquets_revue_pii")
    revue = _load("revue_pii_cli")
    root = tmp_path / "miroir"
    root.mkdir()
    pdf = _pdf([_PAGE_AVEC_TEXTE, b"BT /F1 12 Tf 72 720 Td (Standard : 01 23 45 67 89) Tj ET"])
    sha = hashlib.sha256(pdf).hexdigest()
    (root / f"{sha}.pdf").write_bytes(pdf)
    placements = tmp_path / "placements.json"
    placements.write_text(json.dumps({sha: {"title": "t", "source_path": "x.pdf", "placements": ["c"]}}))
    index_path = tmp_path / "index.json"
    preparer.preparer(
        pdf_root=root, content_sha256=[sha], placements_path=placements, policy_path=POLICY,
        output_root=tmp_path / "revue", index_path=index_path, campaign_id="pii-review-test",
        require_frozen=False,
    )
    reponses = iter(["4", "1", "6", "Numéro personnel d'un particulier identifiable en page 2."])
    brouillon = revue.revoir(
        index_path=index_path, bundles_root=tmp_path / "revue", draft=tmp_path / "d.json",
        reviewer_login="abenrhouma", corpus_manifest_sha256="7" * 64,
        ask=lambda _p: next(reponses), out=lambda _l: None,
    )
    assert brouillon["decisions"][sha]["decision"] == "REJECTED"
