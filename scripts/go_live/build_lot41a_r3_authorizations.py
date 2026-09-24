#!/usr/bin/env python3
"""Dérive les onze autorisations LOT41A-V2 (r3) de publication de V3 (ADR-0060).

Chaque r3 reprend la r2 de sa collection — scope, droits, audience, domaines,
profil — et la porte au protocole V2 avec une liste POSITIVE de contenus : les
placements que V3 prescrit dans cette collection. Rien n'est ressaisi, et
rien n'est étendu : ni droit, ni audience, ni contenu hors de la collection.

    python3 scripts/go_live/build_lot41a_r3_authorizations.py [--check]

Sans ``--check``, écrit les onze artefacts canoniques à leur chemin canonique ;
avec, refuse s'ils diffèrent de ce que la release dérive.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "packages/contracts/src"))

from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: E402

AUTORISATIONS = "governance/authorizations"
V3_DIR = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v3/"
    "release-f8fb983d04f4b7c1/profile_gate"
)
PREFIXE_R2 = "lot41a-staging-v2-"
PREFIXE_R3 = "lot41a-staging-v3-"
VALID_FROM = "2026-09-24T00:00:00.000000Z"


def id_r2(identifiant_r3: str) -> str:
    return PREFIXE_R2 + identifiant_r3.removeprefix(PREFIXE_R3).removesuffix("-r3") + "-r2"


def construire(racine: Path) -> dict[str, dict[str, Any]]:
    v3 = racine / V3_DIR
    manifeste = json.loads((v3 / "production-profile-gate.release.json").read_text(encoding="utf-8"))
    autorites = manifeste["authorities"]
    contenus: dict[str, list[str]] = {}
    for sujet in sorted((v3 / "subjects").glob("*.release.json")):
        document = json.loads(sujet.read_text(encoding="utf-8"))
        contenus[document["collection"]] = sorted(
            {str(p["artifact_id"]) for p in document["placements"]}
        )
    documents: dict[str, dict[str, Any]] = {}
    for fichier in sorted((racine / AUTORISATIONS).glob(f"{PREFIXE_R2}*-r2.json")):
        r2 = json.loads(fichier.read_text(encoding="utf-8"))
        if r2["protocol_version"] != "LOT41A-V1":
            raise SystemExit(f"{fichier.name} n'est pas une r2 LOT41A-V1")
        collection = r2["scope"]["collection"]
        if collection not in contenus:
            raise SystemExit(f"{collection} n'est pas une collection de V3")
        identifiant = PREFIXE_R3 + r2["authorization_id"].removeprefix(PREFIXE_R2).removesuffix("-r2") + "-r3"
        document = {
            **{k: r2[k] for k in (
                "allowed_domains", "decision", "exclusions", "profile_fingerprint",
                "profile_id", "profile_version", "rights_categories", "scope", "valid_until",
            )},
            "allowed_content_sha256": contenus[collection],
            "authorization_id": identifiant,
            "manifest_digest": autorites["profile_manifest_sha256"],
            "pii_absence_attested": True,
            "pii_absence_evidence": f"{V3_DIR}/pii_evidence.json@sha256:{autorites['pii_evidence_sha256']}",
            "protocol_version": "LOT41A-V2",
            "valid_from": VALID_FROM,
        }
        ScopeAuthorizationArtifactV2.model_validate(document)
        documents[identifiant] = document
    if len(documents) != len(contenus):
        raise SystemExit(f"{len(documents)} r2 pour {len(contenus)} collections de V3")
    return documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    ecarts = []
    for document in construire(RACINE).values():
        artefact = ScopeAuthorizationArtifactV2.model_validate(document)
        chemin = RACINE / artefact.canonical_path()
        octets = artefact.canonical_bytes()
        if args.check:
            if not chemin.is_file() or chemin.read_bytes() != octets:
                ecarts.append(str(chemin.relative_to(RACINE)))
        else:
            chemin.write_bytes(octets)
            print(f"{artefact.canonical_path()} {artefact.digest() if hasattr(artefact, 'digest') else ''}")
    if ecarts:
        print(f"R3_DIVERGENTES: {ecarts}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
