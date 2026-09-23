"""Les arguments des commandes canoniques V3 sont dérivés de la release, jamais ressaisis."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import staging_v3_arguments as arguments  # noqa: E402

TRANSFERT = {"path": "/run-cy/transfer_manifest_v3.json", "sha256": "7" * 64}


def _valeur(args: list[str], option: str) -> str:
    return args[args.index(option) + 1]


def _sha(chemin: str) -> str:
    return hashlib.sha256((RACINE / chemin).read_bytes()).hexdigest()


def test_worker_b_recoit_les_autorites_que_la_release_declare():
    args = arguments.worker_b(RACINE, transfert=TRANSFERT, embedding_root="/models/e5-large")
    manifeste = json.loads((RACINE / arguments.V3_DIR / arguments.MANIFESTE).read_text())
    autorites = manifeste["authorities"]
    assert _valeur(args, "--release-manifest-sha256") == _sha(f"{arguments.V3_DIR}/{arguments.MANIFESTE}")
    for option, cle in (
        ("--candidate-inventory-sha256", "candidate_inventory_sha256"),
        ("--currentness-evidence-sha256", "currentness_evidence_sha256"),
        ("--pii-evidence-sha256", "pii_evidence_sha256"),
        ("--programme-registry-sha256", "programme_registry_sha256"),
        ("--levels-mapping-sha256", "level_mapping_sha256"),
        ("--subjects-mapping-sha256", "subject_mapping_sha256"),
        ("--document-types-mapping-sha256", "document_type_mapping_sha256"),
        ("--rights-evidence-sha256", "rights_registry_sha256"),
        ("--pii-decision-set-sha256", "pii_decision_set_sha256"),
        ("--pii-review-receipt-sha256", "pii_review_receipt_sha256"),
        ("--review-trust-anchor-sha256", "pii_review_trust_anchor_sha256"),
        ("--pii-review-index-sha256", "pii_review_index_sha256"),
    ):
        assert _valeur(args, option) == autorites[cle], option
    liaisons = json.loads((RACINE / arguments.V3_DIR / "authority_bindings.json").read_text())
    assert _valeur(args, "--profile-manifest-sha256") == liaisons["profile_manifest_file_sha256"]
    assert liaisons["profile_manifest_fingerprint"] == autorites["profile_manifest_sha256"]
    assert _valeur(args, "--corpus-manifest-sha256") == autorites["corpus_manifest_sha256"]
    assert _valeur(args, "--embedding-inventory-sha256") == manifeste["models"]["embedding"]["inventory_sha256"]
    assert _valeur(args, "--expected-role") == "ingestion_control_app"
    assert _valeur(args, "--expected-product-role") == "rag_publisher"
    assert _valeur(args, "--artifact-transfer-manifest-sha256") == TRANSFERT["sha256"]
    assert all(a.startswith("/") for a in args if a.endswith((".json", ".yml", ".jsonl")))


def test_un_fichier_d_autorite_divergent_est_refuse(monkeypatch):
    original = arguments._sha_fichier
    monkeypatch.setattr(
        arguments, "_sha_fichier",
        lambda racine, chemin: "0" * 64 if chemin.endswith("programme_registry.json") else original(racine, chemin),
    )
    with pytest.raises(arguments.ArgumentsRefuses, match="programme_registry"):
        arguments.worker_b(RACINE, transfert=TRANSFERT, embedding_root="/models/e5-large")


def test_le_rattrapage_nomme_v2_et_ses_onze_autorisations():
    args = arguments.rattrapage_v2(RACINE)
    assert "--only-attributions" in args
    assert _valeur(args, "--release-manifest-sha256") == arguments.V2_MANIFEST_SHA256
    scopes = [args[i + 1] for i, a in enumerate(args) if a == "--scope-authorization"]
    assert len(scopes) == 11 and all(s.endswith("-r2") for s in scopes)


def test_l_ingestion_v3_et_l_adoption_nomment_v3_et_le_transfert_v3():
    ingestion = arguments.ingestion_v3(RACINE, transfert=TRANSFERT)
    assert _valeur(ingestion, "--release-manifest-sha256") == arguments.V3_MANIFEST_SHA256
    assert _valeur(ingestion, "--artifact-transfer-manifest-sha256") == TRANSFERT["sha256"]
    adoption = arguments.adoption_v3(RACINE, transfert=TRANSFERT, adopted_by="operateur")
    assert adoption[0] == "adopt-predecessor-release"
    assert _valeur(adoption, "--predecessor-release-manifest-sha256") == arguments.V2_MANIFEST_SHA256
    assert _valeur(adoption, "--transfer-manifest-sha256") == TRANSFERT["sha256"]


def test_un_manifeste_de_release_altere_est_refuse(monkeypatch):
    monkeypatch.setattr(arguments, "V3_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(arguments.ArgumentsRefuses, match="manifeste"):
        arguments.ingestion_v3(RACINE, transfert=TRANSFERT)


def test_la_cli_imprime_une_ligne_par_argument():
    sortie = arguments.rendre(["--a", "x y", "--b"])
    assert sortie == "--a\nx y\n--b\n"
