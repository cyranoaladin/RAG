"""Le préparateur ne ré-extrait plus le PDF (§ 6, § 7).

Le défaut que ces épreuves interdisent : un paquet de revue dont le texte
provient d'une extraction faite par le préparateur lui-même. Ce texte peut
différer de celui qui a alimenté le scanner PII et le découpage — c'est
exactement ainsi que l'extraction partielle V1 a traversé toute la chaîne
sans que rien ne le montre. Le reviewer statuerait alors sur autre chose que
ce qui a été mesuré.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SERVICE_ROOT / "scripts"
POLICY = SERVICE_ROOT / "configs" / "pii_gate_policy.yml"
SCHEMA = "NEXUS-CANONICAL-REVIEW-INPUT-V1"


def _module():
    spec = importlib.util.spec_from_file_location(
        "preparer_paquets_revue_pii", SCRIPT_DIR / "preparer_paquets_revue_pii.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(texte: str | bytes) -> str:
    if isinstance(texte, str):
        texte = texte.encode("utf-8")
    return hashlib.sha256(texte).hexdigest()


def _canonique(document: object) -> bytes:
    return json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


#: Deux pages : la seconde est OCÉRISÉE. Elle porte la PII, pour que le paquet
#: doive nommer la provenance OCR d'un finding réel (§ 10).
#: La seconde page porte un vrai retour chariot : le texte canonique du corpus
#: gouverné en contient, et une relecture en mode texte les traduirait —
#: présentant au reviewer un texte différent de celui qui a été scanné.
PAGES = ["Page une, sans rien.", "Contact :\r\nm.durand@courrier-prive.org"]
OCR_ID = "a" * 64


def _entree_canonique(racine: Path, sha: str) -> dict[str, object]:
    """Sème un NEXUS-CANONICAL-REVIEW-INPUT-V1 d'épreuve."""
    dossier = racine / sha
    fichiers: dict[str, str] = {}
    for numero, texte in enumerate(PAGES, start=1):
        nom = f"pages/page-{numero:04d}.txt"
        (dossier / "pages").mkdir(parents=True, exist_ok=True)
        (dossier / nom).write_bytes(texte.encode("utf-8"))
        fichiers[nom] = _sha(texte)
    canonique = "\n".join(PAGES)
    (dossier / "canonical_text.txt").write_bytes(canonique.encode("utf-8"))
    fichiers["canonical_text.txt"] = _sha(canonique)
    provenance = [
        {
            "page_number": 1,
            "extraction_path": "NATIVE_TEXT",
            "native_text_sha256": _sha(PAGES[0]),
            "page_policy_verdict": None,
            "canonical_page_text_sha256": _sha(PAGES[0]),
            "ocr_runtime_identity_sha256": None,
        },
        {
            "page_number": 2,
            "extraction_path": "OCR_FALLBACK",
            "native_text_sha256": _sha(""),
            "page_policy_verdict": "PAGE_IMAGE_NON_LISIBLE",
            "canonical_page_text_sha256": _sha(PAGES[1]),
            "ocr_runtime_identity_sha256": OCR_ID,
        },
    ]
    document = {
        "schema": SCHEMA,
        "content_sha256": sha,
        "source_pdf_sha256": sha,
        "canonical_text_sha256": _sha(canonique),
        "page_count": len(PAGES),
        "page_provenance_digest": _sha(_canonique(provenance)),
        "page_provenance": provenance,
        "extraction_policy_id": "NEXUS-DRIVE-PDF-EXTRACTION-V2",
        "extraction_identity_sha256": "b" * 64,
        "files": dict(sorted(fichiers.items())),
    }
    (dossier / "document.json").write_bytes(_canonique(document))
    manifeste = {
        "schema": SCHEMA,
        "FULL_DRIVE_PROCESSING_RUN_ID": "c" * 64,
        "EXTRACTION_POLICY_ID": "NEXUS-DRIVE-PDF-EXTRACTION-V2",
        "OCR_RUNTIME_IDENTITY": OCR_ID,
        "content_count": 1,
        "content_set_sha256": _sha(sha + "\n"),
        "entries": [{"content_sha256": sha, "canonical_text_sha256": _sha(canonique)}],
    }
    (racine / "manifest.json").write_bytes(_canonique(manifeste))
    return document


@pytest.fixture
def atelier(tmp_path: Path):
    """Rend (module, arguments) prêts à préparer un paquet d'épreuve.

    Le PDF du miroir porte des octets ARBITRAIRES : s'il était ré-extrait, le
    texte du paquet ne pourrait pas être celui de l'entrée canonique."""
    preparer = _module()
    pdf = b"%PDF-1.4 des octets qui ne sont pas le texte de revue"
    sha = _sha(pdf)
    miroir = tmp_path / "miroir"
    miroir.mkdir()
    (miroir / f"{sha}.pdf").write_bytes(pdf)
    entree = tmp_path / "entree"
    entree.mkdir()
    _entree_canonique(entree, sha)
    placements = tmp_path / "placements.json"
    placements.write_text(
        json.dumps({sha: {"title": "T", "source_path": "x/y.pdf", "placements": ["z"]}}),
        encoding="utf-8",
    )
    registre = {
        sha: {
            "canonical_text_sha256": _sha("\n".join(PAGES)),
            "pattern_ids": ["email_address"],
            "pages": [2],
            "match_count": 1,
        }
    }
    return preparer, {
        "canonical_input_root": entree,
        "pdf_root": miroir,
        "placements_path": placements,
        "policy_path": POLICY,
        "output_root": tmp_path / "paquets",
        "index_path": tmp_path / "index.json",
        "campaign_id": "epreuve",
        "run_pii_ledger": registre,
        "require_frozen": False,
    }, sha


# --- le texte de revue vient du run, pas du PDF -----------------------


def test_le_texte_du_paquet_est_celui_du_run_pas_une_extraction_du_pdf(atelier) -> None:
    """LE point du lot.

    Le PDF du miroir ne contient pas ce texte : si le préparateur l'extrayait,
    il ne pourrait pas produire la page de revue attendue."""
    preparer, args, sha = atelier
    index = preparer.preparer_depuis_entree_canonique(**args)
    page = (args["output_root"] / sha / "pages/page-0002.txt").read_bytes().decode("utf-8")
    assert page == PAGES[1]
    assert "\r\n" in page, "un retour chariot traduit serait un autre texte"
    assert index["protocol_version"] == "NEXUS-PII-REVIEW-INDEX-V1"
    assert "bundles" in index, "l'index garde les clés du protocole existant"
    assert index["bundles"][0]["canonical_text_sha256"] == _sha("\n".join(PAGES))


def test_un_texte_de_revue_qui_n_est_pas_celui_scanne_est_refuse(atelier) -> None:
    """Si l'entrée canonique et le registre du run divergent, le paquet ferait
    statuer sur un texte que le scanner n'a jamais lu."""
    preparer, args, sha = atelier
    args["run_pii_ledger"][sha]["canonical_text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="n'est pas celui que le run a scanné"):
        preparer.preparer_depuis_entree_canonique(**args)


def test_une_page_alteree_dans_l_entree_canonique_est_refusee(atelier) -> None:
    """L'entrée canonique s'épingle elle-même : une page modifiée après export
    ne doit pas pouvoir entrer dans un paquet."""
    preparer, args, sha = atelier
    (args["canonical_input_root"] / sha / "pages/page-0002.txt").write_bytes(
        b"autre chose"
    )
    with pytest.raises(ValueError, match="ne correspond pas à son empreinte déclarée"):
        preparer.preparer_depuis_entree_canonique(**args)


def test_un_agregat_qui_diverge_du_registre_du_run_est_refuse(atelier) -> None:
    """Si le scan du texte canonique ne retombe pas sur ce que le run a
    enregistré, ce n'est pas le paquet qui est faux : c'est que le scanner ou
    la politique ont bougé sous une lignée qui prétend ne pas avoir bougé."""
    preparer, args, sha = atelier
    args["run_pii_ledger"][sha]["match_count"] = 7
    with pytest.raises(ValueError, match="correspondance"):
        preparer.preparer_depuis_entree_canonique(**args)


def test_un_contenu_absent_du_registre_du_run_est_refuse(atelier) -> None:
    preparer, args, sha = atelier
    args["run_pii_ledger"] = {}
    with pytest.raises(ValueError, match="absent du registre PII du run"):
        preparer.preparer_depuis_entree_canonique(**args)


# --- § 10 : la provenance OCR est visible du reviewer -----------------


def test_un_finding_sur_page_ocerisee_nomme_sa_provenance(atelier) -> None:
    """Sans cela, le reviewer ne peut pas savoir que la page qu'on lui montre
    a été reconstituée par le repli OCR canonique."""
    preparer, args, sha = atelier
    preparer.preparer_depuis_entree_canonique(**args)
    manifeste = json.loads(
        (args["output_root"] / sha / "manifest.json").read_text(encoding="utf-8")
    )
    (signal,) = manifeste["signals"]
    assert signal["page_number"] == 2
    assert signal["extraction_path"] == "OCR_FALLBACK"
    assert signal["page_policy_verdict"] == "PAGE_IMAGE_NON_LISIBLE"
    assert signal["ocr_runtime_identity_sha256"] == OCR_ID
    assert signal["canonical_page_text_sha256"] == _sha(PAGES[1])


def test_le_paquet_nomme_la_lignee_du_traitement(atelier) -> None:
    """Un paquet qui ne dit pas de quel run son texte vient ne se requalifie
    pas le jour où le run est supersédé."""
    preparer, args, sha = atelier
    preparer.preparer_depuis_entree_canonique(**args)
    manifeste = json.loads(
        (args["output_root"] / sha / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifeste["FULL_DRIVE_PROCESSING_RUN_ID"] == "c" * 64
    assert manifeste["EXTRACTION_POLICY_ID"] == "NEXUS-DRIVE-PDF-EXTRACTION-V2"
    assert manifeste["review_input_schema"] == SCHEMA


# --- § 8 : le PDF reste dans le paquet --------------------------------


def test_le_pdf_source_reste_dans_le_paquet(atelier) -> None:
    """Le reviewer doit pouvoir confronter le finding au document source."""
    preparer, args, sha = atelier
    preparer.preparer_depuis_entree_canonique(**args)
    pdf = args["output_root"] / sha / "document.pdf"
    assert pdf.is_file()
    assert _sha(pdf.read_bytes()) == sha


def test_un_pdf_du_miroir_qui_ne_hache_pas_juste_est_refuse(atelier) -> None:
    preparer, args, sha = atelier
    (args["pdf_root"] / f"{sha}.pdf").write_bytes(b"substitue")
    with pytest.raises(ValueError, match="does not match its content SHA-256"):
        preparer.preparer_depuis_entree_canonique(**args)


# --- § 13 : la matière brute n'est jamais lisible par un tiers --------


def test_la_matiere_brute_du_paquet_est_en_0600(atelier) -> None:
    preparer, args, sha = atelier
    preparer.preparer_depuis_entree_canonique(**args)
    for nom in ("document.pdf", "manifest.json", "pages/page-0002.txt"):
        mode = os.stat(args["output_root"] / sha / nom).st_mode & 0o777
        assert mode == 0o600, nom
