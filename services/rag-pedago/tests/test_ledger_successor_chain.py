"""La chaîne qui protège le registre successeur, éprouvée sous sabotage (§10).

Le registre du 14/08 reste à ses octets attestés ; le successeur du 02/09 est
dérivé par exécution, et sa provenance épingle sa source (`supersedes`), ses
rectifications, ses preuves et sa sortie. Ce test rehache les fichiers RÉELS
du dépôt contre la provenance, puis prouve que chaque sabotage est détecté.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = REPO / "docs/reports/evidence-index"
SOURCE = EVIDENCE / "content_ledger_20260814.jsonl"
SUCCESSOR = EVIDENCE / "content_ledger_20260902.jsonl"
PROVENANCE = EVIDENCE / "content_ledger_20260902.provenance.json"
RECTIFICATIONS = EVIDENCE / "rectifications_ledger_20260902.json"
ATTESTED_SOURCE_SHA256 = "c61dc102988bf122964b1fbab64fc2ebc76ea073b74cdec2c94a5ebcdc1ecc41"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


EVIDENCE_REL = "docs/reports/evidence-index"


def verifier_chaine(root: Path) -> None:
    """Rejoue la chaîne provenance → source → rectifications → preuves → sortie,
    tous les chemins étant relatifs à la racine du dépôt (ou de sa copie)."""
    base = root / EVIDENCE_REL
    provenance = json.loads((base / "content_ledger_20260902.provenance.json").read_text())
    if provenance["schema_version"] != "NEXUS-DERIVED-LEDGER-PROVENANCE-V1":
        raise ValueError("provenance schema")
    supersedes = provenance["supersedes"]
    source = root / supersedes["path"]
    if _sha(source) != supersedes["sha256"]:
        raise ValueError("supersedes digest differs from the attested source")
    rectifications = base / "rectifications_ledger_20260902.json"
    if _sha(rectifications) != provenance["entrees"][rectifications.name]:
        raise ValueError("rectifications digest differs from the provenance")
    declaration = json.loads(rectifications.read_text())
    if declaration["source_ledger"]["sha256"] != supersedes["sha256"]:
        raise ValueError("rectifications name another source ledger")
    for name, evidence in declaration["evidences"].items():
        path = root / evidence["path"]
        if not path.is_file() or _sha(path) != evidence["sha256"]:
            raise ValueError(f"evidence {name} digest differs")
        if provenance["entrees"].get(evidence["path"]) != evidence["sha256"]:
            raise ValueError(f"evidence {name} not pinned by the provenance")
    successor = base / "content_ledger_20260902.jsonl"
    if _sha(successor) != provenance["sortie"][successor.name]:
        raise ValueError("successor digest differs from the provenance")


def test_the_attested_source_is_untouched() -> None:
    assert _sha(SOURCE) == ATTESTED_SOURCE_SHA256


def test_the_real_chain_holds() -> None:
    verifier_chaine(REPO)


def test_the_successor_is_a_faithful_derivation(tmp_path: Path) -> None:
    """Rederiver depuis la source attestée et les rectifications rend exactement
    les octets du successeur commité."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "deriver_content_ledger", REPO / "services/rag-pedago/scripts/deriver_content_ledger.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sortie = tmp_path / "content_ledger_20260902.jsonl"
    module.deriver(source=SOURCE, rectifications=RECTIFICATIONS, sortie=sortie, base_dir=REPO)
    assert sortie.read_bytes() == SUCCESSOR.read_bytes()


def _copie(tmp_path: Path) -> Path:
    """Copie de la chaîne sous une racine jetable, aux mêmes chemins relatifs."""
    root = tmp_path / "depot"
    declaration = json.loads(RECTIFICATIONS.read_text())
    relatifs = [f"{EVIDENCE_REL}/{p.name}" for p in (SOURCE, SUCCESSOR, PROVENANCE, RECTIFICATIONS)]
    relatifs += [evidence["path"] for evidence in declaration["evidences"].values()]
    for relatif in relatifs:
        destination = root / relatif
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relatif, destination)
    return root


@pytest.mark.parametrize(
    ("sabotage", "message"),
    [
        (lambda r: (r / EVIDENCE_REL / "content_ledger_20260902.jsonl").write_bytes(
            (r / EVIDENCE_REL / "content_ledger_20260902.jsonl").read_bytes().replace(b'"PII": "QUARANTINED"', b'"PII": "CLEARED"', 1)),
         "successor"),
        (lambda r: (r / EVIDENCE_REL / "content_ledger_20260902.provenance.json").write_text(
            (r / EVIDENCE_REL / "content_ledger_20260902.provenance.json").read_text().replace(ATTESTED_SOURCE_SHA256, "0" * 64)),
         "supersedes"),
        (lambda r: (r / EVIDENCE_REL / "pii_rescan_policy_v5_20260902.json").write_bytes(
            (r / EVIDENCE_REL / "pii_rescan_policy_v5_20260902.json").read_bytes().replace(b'"detected": 23', b'"detected": 0', 1)),
         "evidence"),
        (lambda r: (r / EVIDENCE_REL / "rectifications_ledger_20260902.json").write_text(
            (r / EVIDENCE_REL / "rectifications_ledger_20260902.json").read_text().replace('"apres": "CLEARED"', '"apres": "REVIEW_REQUIRED"', 1)),
         "rectifications"),
    ],
)
def test_every_sabotage_of_the_chain_is_detected(tmp_path: Path, sabotage, message: str) -> None:
    root = _copie(tmp_path)
    verifier_chaine(root)
    sabotage(root)
    with pytest.raises(ValueError, match=message):
        verifier_chaine(root)
