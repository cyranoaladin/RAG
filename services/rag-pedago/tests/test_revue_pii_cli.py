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
    preparer.preparer_par_extraction_locale(
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
    preparer.preparer_par_extraction_locale(
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


# ── Le manifeste de corpus : explicite, vérifié, jamais écrasé ─────────────
#
# Mesuré sur la campagne profile-gate V3 : le brouillon créé par
# `sceller_decisions_pii.py brouillon` portait l'empreinte du FICHIER d'autorité
# (`5ce13fac…`) ; l'import par ce CLI l'a réécrite avec sa valeur par défaut,
# l'autorité que ce fichier DÉCLARE (`d7e5…`). Le jeu scellé décrivait alors
# « un autre corpus » pour le producteur.


def _index_vide(tmp_path: Path) -> Path:
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"campaign_id": "pii-review-test", "bundles": []}), encoding="utf-8")
    return index


def _brouillon_existant(tmp_path: Path, manifeste: str) -> Path:
    draft = tmp_path / "decisions.draft.json"
    draft.write_text(
        json.dumps({
            "decision_set_id": "pii-review-test", "corpus_manifest_sha256": manifeste,
            "reviewer_login": "abenrhouma", "decisions": {},
        }),
        encoding="utf-8",
    )
    return draft


def _revoir(revue, tmp_path: Path, draft: Path, manifeste, **kwargs):
    return revue.revoir(
        index_path=_index_vide(tmp_path), bundles_root=tmp_path, draft=draft,
        reviewer_login="abenrhouma", corpus_manifest_sha256=manifeste,
        ask=lambda _p: "", out=lambda _l: None, **kwargs,
    )


def test_the_draft_corpus_manifest_is_never_silently_overwritten(tmp_path: Path) -> None:
    import pytest

    revue = _load("revue_pii_cli")
    draft = _brouillon_existant(tmp_path, "5" * 64)
    avant = draft.read_bytes()
    with pytest.raises(ValueError, match="corpus_manifest_sha256"):
        _revoir(revue, tmp_path, draft, "d" * 64)
    assert draft.read_bytes() == avant


def test_the_draft_corpus_manifest_is_kept_when_none_is_given(tmp_path: Path) -> None:
    revue = _load("revue_pii_cli")
    draft = _brouillon_existant(tmp_path, "5" * 64)
    assert _revoir(revue, tmp_path, draft, None)["corpus_manifest_sha256"] == "5" * 64
    assert _revoir(revue, tmp_path, draft, "5" * 64)["corpus_manifest_sha256"] == "5" * 64


def test_a_new_draft_requires_an_explicit_corpus_manifest(tmp_path: Path) -> None:
    import pytest

    revue = _load("revue_pii_cli")
    with pytest.raises(ValueError, match="corpus_manifest_sha256"):
        _revoir(revue, tmp_path, tmp_path / "neuf.json", None)


def test_the_cli_has_no_default_corpus_manifest(tmp_path: Path) -> None:
    revue = _load("revue_pii_cli")
    code = revue.main([
        "--index", str(_index_vide(tmp_path)), "--bundles", str(tmp_path),
        "--draft", str(tmp_path / "neuf.json"), "--reviewer-login", "abenrhouma",
    ])
    assert code == 1
    assert not (tmp_path / "neuf.json").exists()


def test_the_declared_authority_is_refused_in_place_of_the_file_digest(tmp_path: Path) -> None:
    """La confusion exacte : la valeur DÉCLARÉE par le fichier au lieu de son empreinte."""
    import pytest

    revue = _load("revue_pii_cli")
    autorite = tmp_path / "corpus_manifest_authority.json"
    autorite.write_text(json.dumps({"authority_sha256": "d" * 64}), encoding="utf-8")
    empreinte = hashlib.sha256(autorite.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="corpus manifest authority"):
        _revoir(revue, tmp_path, tmp_path / "a.json", "d" * 64, corpus_manifest_authority=autorite)
    brouillon = _revoir(
        revue, tmp_path, tmp_path / "b.json", empreinte, corpus_manifest_authority=autorite
    )
    assert brouillon["corpus_manifest_sha256"] == empreinte


def test_the_cli_defaults_the_check_to_the_producer_authority_file(tmp_path: Path) -> None:
    """Sans argument, le CLI vérifie contre le fichier que le producteur lie."""
    revue = _load("revue_pii_cli")
    autorite = SCRIPT_DIR.parent / "data/releases/prerentree_2026_2027/profile_gate/corpus_manifest_authority.json"
    assert revue.DEFAULT_CORPUS_MANIFEST_AUTHORITY == autorite
    declaree = json.loads(autorite.read_text(encoding="utf-8"))["authority_sha256"]
    code = revue.main([
        "--index", str(_index_vide(tmp_path)), "--bundles", str(tmp_path),
        "--draft", str(tmp_path / "neuf.json"), "--reviewer-login", "abenrhouma",
        "--corpus-manifest-sha256", declaree,
    ])
    assert code == 1
