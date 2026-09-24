#!/usr/bin/env python3
"""Arguments des commandes canoniques de la publication V4 (lot DB).

Rien n'est ressaisi : chaque empreinte est recalculée depuis le fichier du
dépôt et confrontée à ce que le manifeste de la release DÉCLARE ; les onze
autorisations r4 sont celles que le générateur dérive de la release. Un écart
refuse. Les chemins sont ceux du conteneur worker, où le dépôt est monté en
lecture seule sous ``/repo``.

    python3 scripts/go_live/staging_v4_arguments.py worker-b \\
        --transfer-sha256 <sha> --embedding-root /models/e5-large
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

MONTAGE = "/repo"
MANIFESTE = "production-profile-gate.release.json"
V4_ID = "production-profile-gate-2026-2027-v4"
V4_DIR = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/"
    "release-024f8625ebfeb7ce/profile_gate"
)
V4_MANIFEST_SHA256 = "bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be"
TRANSFERT_V4 = "/run-db/transfer_manifest_v4.json"
PROFILS = "services/rag-engine/configs/ingestion_profiles/v3_livraison_315"
PROFILE_MANIFEST = "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v3_livraison_315.yml"
CONFIG_COLLECTIONS = "services/rag-engine/configs/rag_collections.yml"
RELEVEURS = "scripts/github/trusted-reviewers.json"
GENERATEUR_R4 = "scripts/go_live/build_lot41a_r4_authorizations.py"

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


def _release(racine: Path) -> dict:
    reel = _sha_fichier(racine, f"{V4_DIR}/{MANIFESTE}")
    if reel != V4_MANIFEST_SHA256:
        raise ArgumentsRefuses(f"manifeste de {V4_DIR} : {reel} ≠ {V4_MANIFEST_SHA256}")
    manifeste = json.loads((racine / V4_DIR / MANIFESTE).read_text(encoding="utf-8"))
    if manifeste.get("release_id") != V4_ID:
        raise ArgumentsRefuses(f"release_id {manifeste.get('release_id')!r} ≠ {V4_ID}")
    return manifeste


def autorisations_r4(racine: Path) -> dict[str, str]:
    """collection → identifiant r4, tels que le générateur les dérive de V4."""
    spec = importlib.util.spec_from_file_location("build_lot41a_r4", racine / GENERATEUR_R4)
    if spec is None or spec.loader is None:
        raise ArgumentsRefuses(f"générateur r4 introuvable : {GENERATEUR_R4}")
    generateur = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generateur)
    derivees = generateur.construire(racine)
    r4 = {
        document["scope"]["collection"]: identifiant
        for identifiant, document in derivees.items()
    }
    if len(r4) != 11 or not all(i.startswith("lot41a-staging-v4-") and i.endswith("-r4") for i in r4.values()):
        raise ArgumentsRefuses(f"onze autorisations r4 attendues, {sorted(r4.values())}")
    if any(d.get("protocol_version") != "LOT41A-V2" for d in derivees.values()):
        raise ArgumentsRefuses("une r4 n'est pas LOT41A-V2")
    return dict(sorted(r4.items()))


def ingestion_v4(racine: Path, *, transfert: dict, owner: str = "staging-v4-db") -> list[str]:
    manifeste = _release(racine)
    registre = manifeste["artifact_registry"]
    if _sha_fichier(racine, f"{V4_DIR}/{registre['path']}") != registre["sha256"]:
        raise ArgumentsRefuses("artifacts.release.json diverge du manifeste")
    inventaire = manifeste["authorities"]["candidate_inventory_sha256"]
    if _sha_fichier(racine, f"{V4_DIR}/candidate_inventory.json") != inventaire:
        raise ArgumentsRefuses("candidate_inventory.json diverge du manifeste")
    args = [
        "--release-dir", _dans(V4_DIR),
        "--release-manifest-sha256", V4_MANIFEST_SHA256,
        "--artifacts-release-sha256", registre["sha256"],
        "--candidate-inventory-sha256", inventaire,
        "--artifact-transfer-manifest-path", transfert["path"],
        "--artifact-transfer-manifest-sha256", transfert["sha256"],
        "--artifact-store-dir", "/store",
        "--profiles-dir", _dans(PROFILS),
        "--owner", owner,
        "--expected-role", "ingestion_control_app",
    ]
    for collection, identifiant in autorisations_r4(racine).items():
        args += ["--scope-authorization", f"{collection}={identifiant}"]
    return args


def worker_b(
    racine: Path, *, transfert: dict, embedding_root: str, owner: str = "staging-v4-db-worker-b"
) -> list[str]:
    manifeste = _release(racine)
    autorites = manifeste["authorities"]
    args = [
        "--profiles-dir", _dans(PROFILS),
        "--artifact-store-dir", "/store",
        "--owner", owner,
        "--expected-role", "ingestion_control_app",
        "--expected-product-role", "rag_publisher",
        "--release-manifest-path", _dans(f"{V4_DIR}/{MANIFESTE}"),
        "--release-manifest-sha256", V4_MANIFEST_SHA256,
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
    # Le manifeste de profils : la release DÉCLARE son empreinte canonique,
    # Worker B vérifie celle des OCTETS. Deux grandeurs, toutes deux liées par
    # authority_bindings.json ; on transmet celle que le worker contrôle.
    liaisons = json.loads((racine / V4_DIR / "authority_bindings.json").read_text(encoding="utf-8"))
    if liaisons.get("profile_manifest_fingerprint") != autorites["profile_manifest_sha256"]:
        raise ArgumentsRefuses("profile_manifest : empreinte canonique non liée à la release")
    octets = _sha_fichier(racine, PROFILE_MANIFEST)
    if octets != liaisons.get("profile_manifest_file_sha256"):
        raise ArgumentsRefuses(f"{PROFILE_MANIFEST} : {octets} ≠ octets liés par la release")
    args += ["--profile-manifest-path", _dans(PROFILE_MANIFEST), "--profile-manifest-sha256", octets]
    for option, cle, chemin_depot, nom_release in AUTORITES_WORKER_B:
        chemin = chemin_depot or f"{V4_DIR}/{nom_release}"
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
    parser.add_argument("commande", choices=("ingestion-v4", "worker-b", "autorisations-r4"))
    parser.add_argument("--transfer-path", default=TRANSFERT_V4)
    parser.add_argument("--transfer-sha256", default=None)
    parser.add_argument("--embedding-root", default="/models/e5-large")
    args = parser.parse_args(argv)
    racine = Path(__file__).resolve().parents[2]
    transfert = {"path": args.transfer_path, "sha256": args.transfer_sha256}
    try:
        if args.commande == "autorisations-r4":
            sortie = list(autorisations_r4(racine).values())
        elif not args.transfer_sha256:
            raise ArgumentsRefuses("--transfer-sha256 requis : le manifeste de transfert V4 est mesuré")
        elif args.commande == "ingestion-v4":
            sortie = ingestion_v4(racine, transfert=transfert)
        else:
            sortie = worker_b(racine, transfert=transfert, embedding_root=args.embedding_root)
    except ArgumentsRefuses as exc:
        print(f"ARGUMENTS_REFUSES: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(rendre(sortie))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
