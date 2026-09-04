"""Paquets de revue PII, hors dépôt, figés par empreinte (ADR-0047 § 2).

Un reviewer statue sur un paquet généré depuis les octets exacts du PDF, lié au
scanner et à la politique exacts, paginé, contextualisé, figé par SHA-256 et
invalidé par toute modification. Le dépôt ne garde que l'index, sans matière.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from tests.test_pii_scanner_pages_sans_texte import _PAGE_AVEC_TEXTE, _pdf

#: Racines dérivées de l'EMPLACEMENT de ce fichier, jamais du répertoire de
#: lancement. Ces tests s'exécutaient depuis `services/rag-pedago` et échouaient
#: partout ailleurs — y compris depuis la racine, où la CI les appelle : un test
#: qui ne peut être lancé que d'un seul dossier ne protège que ce dossier-là.
SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVICE_ROOT.parents[1]
PREPARER_SCRIPT = SERVICE_ROOT / "scripts/preparer_paquets_revue_pii.py"
PROJECTION_HELPER = SERVICE_ROOT / "rag_pedago/imports/pii_review_projection.py"

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
        campaign_id="pii-review-test", require_frozen=False,
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
        policy_path=POLICY, output_root=out, index_path=index_path, campaign_id="pii-review-test", require_frozen=False,
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
            campaign_id="pii-review-test", require_frozen=False,
        )


def test_generation_is_deterministic(tmp_path: Path) -> None:
    preparer = _module()
    root, placements, shas = _corpus(tmp_path)
    first = preparer.preparer(
        pdf_root=root, content_sha256=sorted(shas.values()), placements_path=placements,
        policy_path=POLICY, output_root=tmp_path / "a", index_path=tmp_path / "a.json",
        campaign_id="pii-review-test", require_frozen=False,
    )
    second = preparer.preparer(
        pdf_root=root, content_sha256=sorted(shas.values()), placements_path=placements,
        policy_path=POLICY, output_root=tmp_path / "b", index_path=tmp_path / "b.json",
        campaign_id="pii-review-test", require_frozen=False,
    )
    assert first["bundles"][0]["bundle_sha256"] == second["bundles"][0]["bundle_sha256"]


def test_each_finding_has_an_identity_and_the_producer_is_frozen(tmp_path: Path) -> None:
    """Le reviewer statue sur des findings identifiés — jamais sur un document
    en bloc — produits par UN code et DES autorités nommés (§2, §7, §8, §9)."""
    preparer = _module()
    root, placements, shas = _corpus(tmp_path)
    out = tmp_path / "revue"
    index_path = tmp_path / "index.json"
    index = preparer.preparer(
        pdf_root=root, content_sha256=sorted(shas.values()), placements_path=placements,
        policy_path=POLICY, output_root=out, index_path=index_path, campaign_id="pii-review-test", require_frozen=False,
    )
    for key in ("producer_commit_sha", "producer_tree_sha", "generator_sha256",
                "contracts_version", "runtime"):
        assert key in index and index[key], key
    assert len(index["producer_commit_sha"]) == 40 and len(index["producer_tree_sha"]) == 40
    assert index["generator_sha256"] == _sha(SCRIPT_DIR / "preparer_paquets_revue_pii.py")
    entry = index["bundles"][0]
    assert entry["bundle_id"] == f"pii-review-test:{shas['detecte']}"
    assert entry["pdf_sha256"] == shas["detecte"]
    assert entry["finding_count"] == 2 and entry["pages_with_findings"] == [2, 3]
    findings = entry["findings"]
    assert [f["pattern_id"] for f in findings] == ["email_address", "phone_french"]
    for finding in findings:
        assert set(finding) == {"finding_id", "pattern_id", "page", "match_sha256", "context_sha256", "match_length"}
        assert len(finding["finding_id"]) == 64 and len(finding["match_sha256"]) == 64
    manifest = json.loads((out / shas["detecte"] / "manifest.json").read_text(encoding="utf-8"))
    for key in ("producer_commit_sha", "producer_tree_sha", "generator_sha256", "contracts_version",
                "bundle_id", "pdf_sha256"):
        assert manifest[key] == index.get(key, manifest[key])
    by_id = {s["finding_id"]: s for s in manifest["signals"]}
    assert set(by_id) == {f["finding_id"] for f in findings}
    first = by_id[findings[0]["finding_id"]]
    assert first["match_sha256"] == hashlib.sha256(first["match_text"].encode("utf-8")).hexdigest()
    assert first["context_sha256"] == hashlib.sha256(first["context"].encode("utf-8")).hexdigest()
    serialised = index_path.read_text(encoding="utf-8")
    assert "durand" not in serialised and "01 23 45" not in serialised


def test_a_french_ssn_finding_carries_its_checksum_verdict_without_deciding(tmp_path: Path) -> None:
    preparer = _module()
    root = tmp_path / "miroir"
    root.mkdir()
    invalid = _pdf([_PAGE_AVEC_TEXTE, b"BT /F1 12 Tf 72 720 Td (NIR : 1 23 45 67 890 123 45) Tj ET"])
    sha = hashlib.sha256(invalid).hexdigest()
    (root / f"{sha}.pdf").write_bytes(invalid)
    placements = tmp_path / "placements.json"
    placements.write_text(json.dumps({sha: {"title": "t", "source_path": "x.pdf", "placements": ["c"]}}))
    index = preparer.preparer(
        pdf_root=root, content_sha256=[sha], placements_path=placements, policy_path=POLICY,
        output_root=tmp_path / "revue", index_path=tmp_path / "index.json", campaign_id="pii-review-test", require_frozen=False,
    )
    findings = index["bundles"][0]["findings"]
    ssn = [f for f in findings if f["pattern_id"] == "french_ssn"]
    assert ssn and ssn[0]["checksum_valid"] is False
    assert preparer.nir_checksum_valid("1 23 45 67 890 123 45") is False
    assert preparer.nir_checksum_valid("2 55 08 14 118 200 05") is True  # clé 5, NIR synthétique
    assert "decision" not in ssn[0]


class TestTheBundleProducerIdentityCoversWhatDecides:
    """P2 — un module qui décide des octets scellés doit être dans la provenance.

    `producer_identity` gèle le générateur, le scanner, la politique et le foyer
    de pages, mais pas `pii_review_projection.py` — qui fournit pourtant
    `finding_identity` et `finding_context`, c'est-à-dire l'identité et le
    contexte que les paquets scellent. Une modification locale de ce module
    aurait donc produit des paquets différents sous la MÊME provenance.

    **Le correctif est prospectif.** Les 23 paquets déjà revus restent lus sous
    leur schéma d'origine : leur `generator_sha256` historique ne couvrait pas
    ce module, et prétendre le contraire réécrirait leur provenance au lieu de
    versionner la nouvelle règle."""

    def test_the_projection_helper_is_part_of_the_frozen_surface(self) -> None:
        source = PREPARER_SCRIPT.read_text(encoding="utf-8")
        frozen = source[source.index("porcelain = subprocess.check_output") :]
        frozen = frozen[: frozen.index("cwd=REPOSITORY_ROOT")]
        assert "pii_review_projection.py" in frozen, (
            "le module qui décide de l'identité des findings doit être gelé"
        )

    def test_the_identity_names_the_projection_helper(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_preparer", PREPARER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["_preparer"] = module
        spec.loader.exec_module(module)
        identity = module.producer_identity(require_frozen=False)
        assert "projection_sha256" in identity
        assert len(identity["projection_sha256"]) == 64

    def test_a_change_to_the_helper_changes_the_future_identity(self) -> None:
        """La propriété qui compte : l'empreinte suit le module.

        La version précédente hachait deux chaînes d'octets et constatait
        qu'elles différaient — une propriété de SHA-256, pas du producteur.
        Elle n'appelait jamais `producer_identity` et serait restée verte si
        celui-ci avait cessé de couvrir le module. Ici l'identité est
        réellement calculée, deux fois, autour d'une modification du module."""
        import hashlib
        import importlib.util

        spec = importlib.util.spec_from_file_location("_preparer_id", PREPARER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["_preparer_id"] = module
        spec.loader.exec_module(module)

        before = module.producer_identity(require_frozen=False)
        assert before["projection_sha256"] == hashlib.sha256(
            PROJECTION_HELPER.read_bytes()
        ).hexdigest()

        original = PROJECTION_HELPER.read_bytes()
        try:
            PROJECTION_HELPER.write_bytes(original + b"\n# changement local\n")
            after = module.producer_identity(require_frozen=False)
        finally:
            PROJECTION_HELPER.write_bytes(original)
        assert after["projection_sha256"] != before["projection_sha256"], (
            "l'identité du producteur ne suit pas le module qui décide de "
            "l'identité des findings : des paquets différents porteraient la "
            "même provenance"
        )
        assert module.producer_identity(require_frozen=False) == before

    def test_the_historical_bundles_keep_their_own_provenance(self) -> None:
        """Les 23 paquets scellés ne sont pas réinterprétés rétroactivement.

        Leur index déclare le `generator_sha256` qui valait à leur production ;
        il ne couvrait pas le module de projection, et ce lot ne prétend pas le
        contraire."""
        import json

        index = json.loads(
            (
                REPOSITORY_ROOT
                / "docs/reports/evidence-index/pii_review_index_20260903.json"
            ).read_text(encoding="utf-8")
        )
        assert "generator_sha256" in index
        assert "projection_sha256" not in index
