"""L'attestation de provenance de la lignée régénérée, et l'ancienne, intacte.

Ce que ces épreuves refusent :

1. qu'une attestation soit émise sans nommer d'où elle vient — code
   producteur, entrées, préflight, release, scopes liés, runtime
   d'extraction, découpeur, version de contrats ;
2. qu'elle recopie une valeur au lieu de la mesurer : chaque empreinte est
   relue du fichier réel, et les scopes liés sont obtenus en **rejouant** la
   sélection du runtime, pas en les nommant de mémoire ;
3. que l'attestation du 2026-08-25, qui atteste une autre lignée, soit
   étendue, réécrite ou touchée d'un octet.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

PEDAGO_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PEDAGO_ROOT.parents[1]
PRODUCER = PEDAGO_ROOT / "scripts" / "build_multilevel_producer_provenance.py"
ATTESTATION = (
    REPOSITORY_ROOT / "docs" / "reports" / "multilevel_producer_provenance_20260906.json"
)

#: L'attestation de la lignée PRÉCÉDENTE. Elle atteste d'autres releases par
#: collection, d'autres empreintes : la recycler ferait dire à une preuve
#: datée ce qu'elle n'a jamais constaté.
ANCIENNE_ATTESTATION = (
    REPOSITORY_ROOT / "docs" / "reports" / "release_scope_placement_provenance_20260825.json"
)
#: Gelé le 2026-09-06 sur les octets du dépôt. Un rescellement de l'ancienne
#: attestation devient visible ici, et nulle part ailleurs.
ANCIENNE_ATTESTATION_SHA256 = (
    "65c12236b494dd4c59376d70d21bb1dc92d341f5aeec5152017fa5cff6cda1ce"
)


def _module() -> ModuleType:
    specification = importlib.util.spec_from_file_location("provenance_cli", PRODUCER)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def attestation() -> dict:
    return json.loads(ATTESTATION.read_text(encoding="utf-8"))


def test_l_attestation_publiee_est_celle_que_le_producteur_rend() -> None:
    """`PROVENANCE_ATTESTATION_DRIFT=0` — sinon elle a été écrite à la main.

    Elle est une fonction pure du contenu attesté : aucun commit, aucune
    horloge. Un checkout qui porte ces octets la reproduit à l'identique, ici
    comme en CI.
    """
    module = _module()
    assert ATTESTATION.read_bytes() == module.serialize(module.build_attestation())


def test_l_attestation_lie_toute_la_chaine(attestation: dict) -> None:
    """Chaque maillon exigé est nommé — un manquant rendrait l'artefact irrefaisable."""
    assert attestation["attestation_kind"] == "MULTILEVEL_PRODUCER_PROVENANCE_V1"
    # Ni commit ni horodatage : une attestation qui en porterait ne serait pas
    # reproductible, et son contrôle de dérive ne prouverait rien.
    assert "source_commit_sha" not in attestation
    assert not any("date" in champ or "time" in champ for champ in attestation)
    for champ in (
        "producer_code_sha256",
        "input_manifest_sha256",
        "preflight_sha256",
        "multilevel_release_sha256",
        "scope_registry_sha256",
        "contracts_version",
        "page_policy_sha256",
        "extractor_identity",
        "chunker_identity",
        "bound_scope_ids",
    ):
        assert attestation.get(champ), champ


def test_chaque_empreinte_est_celle_du_fichier_reel(attestation: dict) -> None:
    """Une attestation qui recopie n'atteste rien : elle est relue, ou fausse."""
    for chemin, digest in attestation["producer_code_sha256"].items():
        octets = (REPOSITORY_ROOT / chemin).read_bytes()
        assert hashlib.sha256(octets).hexdigest() == digest, chemin

    release_root = (
        PEDAGO_ROOT / "data" / "releases" / "prerentree_2026_2027" / "multilevel"
    )
    for nom, chemin in (
        ("preflight_sha256", release_root / "multilevel_preflight.json"),
        ("multilevel_release_sha256", release_root / "multilevel.release.json"),
        (
            "scope_registry_sha256",
            REPOSITORY_ROOT / "packages/contracts/src/nexus_contracts/scope.py",
        ),
    ):
        assert (
            hashlib.sha256(chemin.read_bytes()).hexdigest() == attestation[nom]
        ), nom


def test_les_scopes_lies_sont_ceux_que_le_runtime_selectionnerait(
    attestation: dict,
) -> None:
    """Rejouée, pas recopiée : la sélection est exacte par couple, ou l'émission échoue."""
    import sys

    sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "contracts" / "src"))
    from nexus_contracts import (
        RetrievalScopeArtifactV2,
        load_retrieval_scope_registry,
    )

    registre = load_retrieval_scope_registry()
    attendus = attestation["subject_manifest_sha256_by_collection"]
    assert len(attendus) == attestation["subject_count"] == 10

    lies = []
    for collection, source_sha256 in attendus.items():
        correspondances = [
            scope_id
            for scope_id, artefact in registre.items()
            if isinstance(artefact, RetrievalScopeArtifactV2)
            and str(artefact.evidence_subject.collection) == collection
            and artefact.source_sha256 == source_sha256
        ]
        assert len(correspondances) == 1, (collection, correspondances)
        lies.append(correspondances[0])
    assert sorted(lies) == attestation["bound_scope_ids"]


def test_le_producteur_refuse_un_preflight_sans_runtime_d_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans identité d'extracteur, l'artefact n'est pas refaisable : on refuse."""
    module = _module()
    ampute = json.loads(module.PREFLIGHT_PATH.read_text(encoding="utf-8"))
    ampute.pop("extraction_runtime")
    chemin = tmp_path / "multilevel_preflight.json"
    chemin.write_text(json.dumps(ampute), encoding="utf-8")
    monkeypatch.setattr(module, "PREFLIGHT_PATH", chemin)

    with pytest.raises(module.ProvenanceError):
        module.build_attestation()


def test_le_producteur_refuse_une_entree_que_le_preflight_ne_nomme_pas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    ampute = json.loads(module.PREFLIGHT_PATH.read_text(encoding="utf-8"))
    ampute.pop("pii_evidence_sha256")
    chemin = tmp_path / "multilevel_preflight.json"
    chemin.write_text(json.dumps(ampute), encoding="utf-8")
    monkeypatch.setattr(module, "PREFLIGHT_PATH", chemin)

    with pytest.raises(module.ProvenanceError):
        module.build_attestation()


def test_l_ancienne_attestation_reste_octet_identique() -> None:
    """DO_NOT_EXTEND_PROVENANCE_EXEMPTION — l'ancienne preuve n'est pas rejouée.

    Elle atteste la lignée du 2026-08-25 : d'autres releases par collection,
    d'autres empreintes. L'étendre à la lignée régénérée lui ferait dire ce
    qu'elle n'a jamais constaté. Elle est donc laissée intacte, et la lignée
    neuve reçoit une attestation neuve.
    """
    assert ANCIENNE_ATTESTATION.is_file()
    assert (
        hashlib.sha256(ANCIENNE_ATTESTATION.read_bytes()).hexdigest()
        == ANCIENNE_ATTESTATION_SHA256
    )

    ancienne = json.loads(ANCIENNE_ATTESTATION.read_text(encoding="utf-8"))
    nouvelle = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    # Deux lignées distinctes : aucune release par collection de l'ancienne ne
    # figure dans la nouvelle. Sans ce contrôle, « attestation neuve » pourrait
    # n'être qu'une copie renommée.
    anciens_digests = set(ancienne["input_blob_sha256"].values())
    nouveaux_digests = set(nouvelle["subject_manifest_sha256_by_collection"].values())
    assert anciens_digests.isdisjoint(nouveaux_digests)
