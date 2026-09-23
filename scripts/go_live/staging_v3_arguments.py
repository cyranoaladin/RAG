#!/usr/bin/env python3
"""Arguments des commandes canoniques de la publication V3 (lot CY).

Rien n'est ressaisi : chaque empreinte est recalculée depuis le fichier du
dépôt et confrontée à ce que le manifeste de la release DÉCLARE. Un écart
refuse. Les chemins sont ceux du conteneur worker, où le dépôt est monté en
lecture seule sous ``/repo``.

    python3 scripts/go_live/staging_v3_arguments.py worker-b \\
        --transfer-path /run-cy/transfer_manifest_v3.json --transfer-sha256 <sha> \\
        --embedding-root /models/e5-large
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MONTAGE = "/repo"
MANIFESTE = "production-profile-gate.release.json"
V3_ID = "production-profile-gate-2026-2027-v3"
V3_DIR = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v3/"
    "release-f8fb983d04f4b7c1/profile_gate"
)
V3_MANIFEST_SHA256 = "c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16"
V2_ID = "production-profile-gate-2026-2027-v2"
V2_DIR = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate"
)
V2_MANIFEST_SHA256 = "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
TRANSFERT_V2 = "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
PROFILS = "services/rag-engine/configs/ingestion_profiles/v2_livraison_319"
CONFIG_COLLECTIONS = "services/rag-engine/configs/rag_collections.yml"
RELEVEURS = "scripts/github/trusted-reviewers.json"
PROFILE_MANIFEST = "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml"
AUTORISATIONS = "governance/authorizations"

#: option du CLI → (clé d'autorité du manifeste, chemin dans le dépôt ou None
#: pour un fichier de la release elle-même).
AUTORITES_WORKER_B = (
    ("--candidate-inventory", "candidate_inventory_sha256", None, "candidate_inventory.json"),
    ("--currentness-evidence", "currentness_evidence_sha256", None, "currentness_evidence.json"),
    ("--programme-registry", "programme_registry_sha256", None, "programme_registry.json"),
    ("--pii-evidence", "pii_evidence_sha256", None, "pii_evidence.json"),
    ("--levels-mapping", "level_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_multilevel_levels.yml", None),
    ("--subjects-mapping", "subject_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml", None),
    ("--document-types-mapping", "document_type_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_multilevel_document_types.yml", None),
    ("--rights-evidence", "rights_registry_sha256", "services/rag-pedago/configs/rights_evidence_registry.yml", None),
    ("--pii-decision-set", "pii_decision_set_sha256", "governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json", None),
    ("--pii-review-receipt", "pii_review_receipt_sha256", "governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json", None),
    ("--review-trust-anchor", "pii_review_trust_anchor_sha256", "governance/trust-anchors/review-binding-v1.json", None),
    ("--pii-review-index", "pii_review_index_sha256", "docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json", None),
)


class ArgumentsRefuses(RuntimeError):
    """Un fait dérivé ne correspond pas à ce que la release déclare."""


def _sha_fichier(racine: Path, chemin: str) -> str:
    return hashlib.sha256((racine / chemin).read_bytes()).hexdigest()


def _dans(chemin: str) -> str:
    return f"{MONTAGE}/{chemin}"


def _release(racine: Path, dossier: str, attendu: str) -> dict:
    reel = _sha_fichier(racine, f"{dossier}/{MANIFESTE}")
    if reel != attendu:
        raise ArgumentsRefuses(f"manifeste de {dossier} : {reel} ≠ {attendu}")
    return json.loads((racine / dossier / MANIFESTE).read_text(encoding="utf-8"))


def _identites(racine: Path, dossier: str, manifeste: dict) -> list[str]:
    registre = manifeste["artifact_registry"]
    if _sha_fichier(racine, f"{dossier}/{registre['path']}") != registre["sha256"]:
        raise ArgumentsRefuses(f"artifacts.release.json de {dossier} diverge du manifeste")
    inventaire = manifeste["authorities"]["candidate_inventory_sha256"]
    if _sha_fichier(racine, f"{dossier}/candidate_inventory.json") != inventaire:
        raise ArgumentsRefuses(f"candidate_inventory.json de {dossier} diverge du manifeste")
    return [
        "--artifacts-release-sha256", registre["sha256"],
        "--candidate-inventory-sha256", inventaire,
    ]


def _scopes(racine: Path) -> list[str]:
    args: list[str] = []
    for fichier in sorted((racine / AUTORISATIONS).glob("lot41a-staging-v2-*-r2.json")):
        document = json.loads(fichier.read_text(encoding="utf-8"))
        args += ["--scope-authorization", document["authorization_id"]]
    if len(args) != 22:
        raise ArgumentsRefuses(f"onze autorisations LOT41A r2 attendues, {len(args) // 2} trouvées")
    return args


def _worker_a(racine: Path, dossier: str, attendu: str, transfert: dict, owner: str) -> list[str]:
    manifeste = _release(racine, dossier, attendu)
    return [
        "--release-dir", _dans(dossier),
        "--release-manifest-sha256", attendu,
        *_identites(racine, dossier, manifeste),
        "--artifact-transfer-manifest-path", transfert["path"],
        "--artifact-transfer-manifest-sha256", transfert["sha256"],
        "--artifact-store-dir", "/store",
        "--profiles-dir", _dans(PROFILS),
        "--owner", owner,
        "--expected-role", "ingestion_control_app",
        *_scopes(racine),
    ]


def ingestion_v3(racine: Path, *, transfert: dict, owner: str = "staging-v3-cy") -> list[str]:
    return _worker_a(racine, V3_DIR, V3_MANIFEST_SHA256, transfert, owner)


def rattrapage_v2(racine: Path, *, owner: str = "staging-v3-cy") -> list[str]:
    transfert = {"path": _dans(TRANSFERT_V2), "sha256": _sha_fichier(racine, TRANSFERT_V2)}
    return [
        *_worker_a(racine, V2_DIR, V2_MANIFEST_SHA256, transfert, owner),
        "--only-attributions", "--report-path", "/run-cy/backfill-v2.json",
    ]


def adoption_v3(racine: Path, *, transfert: dict, adopted_by: str) -> list[str]:
    manifeste = _release(racine, V3_DIR, V3_MANIFEST_SHA256)
    return [
        "adopt-predecessor-release",
        "--release-id", V3_ID,
        "--release-dir", _dans(V3_DIR),
        "--release-manifest-sha256", V3_MANIFEST_SHA256,
        *_identites(racine, V3_DIR, manifeste),
        "--transfer-manifest-path", transfert["path"],
        "--transfer-manifest-sha256", transfert["sha256"],
        "--predecessor-release-id", V2_ID,
        "--predecessor-release-manifest-sha256", V2_MANIFEST_SHA256,
        "--adopted-by", adopted_by,
    ]


def worker_b(
    racine: Path, *, transfert: dict, embedding_root: str, owner: str = "staging-v3-cy-worker-b"
) -> list[str]:
    manifeste = _release(racine, V3_DIR, V3_MANIFEST_SHA256)
    autorites = manifeste["authorities"]
    args = [
        "--profiles-dir", _dans(PROFILS),
        "--artifact-store-dir", "/store",
        "--owner", owner,
        "--expected-role", "ingestion_control_app",
        "--expected-product-role", "rag_publisher",
        "--release-manifest-path", _dans(f"{V3_DIR}/{MANIFESTE}"),
        "--release-manifest-sha256", V3_MANIFEST_SHA256,
        "--collection-config-path", _dans(CONFIG_COLLECTIONS),
        "--collection-config-sha256", _sha_fichier(racine, CONFIG_COLLECTIONS),
        "--corpus-manifest-sha256", autorites["corpus_manifest_sha256"],
        "--repository-root", MONTAGE,
        "--pii-review-reviewers-sha256", _sha_fichier(racine, RELEVEURS),
        "--artifact-transfer-manifest-path", transfert["path"],
        "--artifact-transfer-manifest-sha256", transfert["sha256"],
        "--embedding-artifact-root", embedding_root,
        "--embedding-inventory-sha256", manifeste["models"]["embedding"]["inventory_sha256"],
    ]
    # Le manifeste de profils : la release DÉCLARE son empreinte canonique
    # (`profile_manifest_sha256` = `profile_manifest_fingerprint`), Worker B
    # vérifie celle des OCTETS. Deux grandeurs, toutes deux liées par
    # authority_bindings.json ; on transmet celle que le worker contrôle.
    liaisons = json.loads((racine / V3_DIR / "authority_bindings.json").read_text(encoding="utf-8"))
    if liaisons.get("profile_manifest_fingerprint") != autorites["profile_manifest_sha256"]:
        raise ArgumentsRefuses("profile_manifest : empreinte canonique non liée à la release")
    octets = _sha_fichier(racine, PROFILE_MANIFEST)
    if octets != liaisons.get("profile_manifest_file_sha256"):
        raise ArgumentsRefuses(f"{PROFILE_MANIFEST} : {octets} ≠ octets liés par la release")
    args += ["--profile-manifest-path", _dans(PROFILE_MANIFEST), "--profile-manifest-sha256", octets]
    for option, cle, chemin_depot, nom_release in AUTORITES_WORKER_B:
        chemin = chemin_depot or f"{V3_DIR}/{nom_release}"
        reel = _sha_fichier(racine, chemin)
        if reel != autorites[cle]:
            raise ArgumentsRefuses(f"{chemin} : {reel} ≠ {cle} déclarée {autorites[cle]}")
        args += [f"{option}-path", _dans(chemin), f"{option}-sha256", reel]
    return args


def rendre(args: list[str]) -> str:
    """Une ligne par argument : lu par ``mapfile``, aucune interprétation shell."""
    return "".join(f"{a}\n" for a in args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("commande", choices=("ingestion-v3", "rattrapage-v2", "adoption-v3", "worker-b"))
    parser.add_argument("--transfer-path", default="/run-cy/transfer_manifest_v3.json")
    parser.add_argument("--transfer-sha256", default=None)
    parser.add_argument("--embedding-root", default="/models/e5-large")
    parser.add_argument("--adopted-by", default=None)
    args = parser.parse_args(argv)
    racine = Path(__file__).resolve().parents[2]
    transfert = {"path": args.transfer_path, "sha256": args.transfer_sha256}
    try:
        if args.commande == "rattrapage-v2":
            sortie = rattrapage_v2(racine)
        elif not args.transfer_sha256:
            raise ArgumentsRefuses("--transfer-sha256 requis : le manifeste de transfert V3 est mesuré")
        elif args.commande == "ingestion-v3":
            sortie = ingestion_v3(racine, transfert=transfert)
        elif args.commande == "adoption-v3":
            if not args.adopted_by:
                raise ArgumentsRefuses("--adopted-by requis : identité réelle de l'opérateur")
            sortie = adoption_v3(racine, transfert=transfert, adopted_by=args.adopted_by)
        else:
            sortie = worker_b(racine, transfert=transfert, embedding_root=args.embedding_root)
    except ArgumentsRefuses as exc:
        print(f"ARGUMENTS_REFUSES: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(rendre(sortie))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
