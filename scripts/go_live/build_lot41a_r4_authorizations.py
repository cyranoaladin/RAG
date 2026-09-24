#!/usr/bin/env python3
"""Dérive les onze autorisations LOT41A-V2 (r4) de publication de V4 (ADR-0060/0061).

Chaque r4 reprend de la r2 de sa collection ce qui ne change pas — droits,
domaines, exclusions, décision — et prend du profil V4 sa portée exacte (au
programme officiel et à la visibilité servie), sa version et son empreinte ;
elle porte une liste POSITIVE de contenus : les placements que V4 prescrit
dans cette collection. Rien n'est ressaisi, rien n'est étendu. Les r2 restent
les autorités de l'acquisition passée.

    python3 scripts/go_live/build_lot41a_r4_authorizations.py [--check]

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
for _paquet in ("contracts", "release-chain", "pdf-page-policy"):
    sys.path.insert(0, str(RACINE / f"packages/{_paquet}/src"))

from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: E402

AUTORISATIONS = "governance/authorizations"
V4_DIR = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/"
    "release-024f8625ebfeb7ce/profile_gate"
)
PROFILS_V4 = "services/rag-engine/configs/ingestion_profiles/v3_livraison_315"
PREFIXE_R2 = "lot41a-staging-v2-"
PREFIXE_R4 = "lot41a-staging-v4-"
VALID_FROM = "2026-09-24T00:00:00.000000Z"


def id_r2(identifiant_r4: str) -> str:
    return PREFIXE_R2 + identifiant_r4.removeprefix(PREFIXE_R4).removesuffix("-r4") + "-r2"


def _profils_v4(racine: Path) -> dict[str, Any]:
    from nexus_release_chain.ingestion_profiles.registry import (
        load_profile_registry,
        profile_fingerprint,
    )

    registre = load_profile_registry(racine / PROFILS_V4)
    return {
        str(p.scope.collection): (p, profile_fingerprint(p)) for p in registre.values()
    }


def construire(racine: Path) -> dict[str, dict[str, Any]]:
    v4 = racine / V4_DIR
    manifeste = json.loads((v4 / "production-profile-gate.release.json").read_text(encoding="utf-8"))
    autorites = manifeste["authorities"]
    profils = _profils_v4(racine)
    contenus: dict[str, list[str]] = {}
    for sujet in sorted((v4 / "subjects").glob("*.release.json")):
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
        if collection not in contenus or collection not in profils:
            raise SystemExit(f"{collection} n'est pas une collection de V4")
        profil, empreinte = profils[collection]
        portee = profil.scope.model_dump(mode="json")
        portee["audience"] = sorted(portee["audience"])
        ecarts = sorted(k for k in set(portee) | set(r2["scope"])
                        if portee.get(k) != r2["scope"].get(k))
        if not set(ecarts) <= {"programme_version", "visibility"}:
            raise SystemExit(f"{collection} : la portée V4 s'écarte de la r2 sur {ecarts}")
        identifiant = PREFIXE_R4 + r2["authorization_id"].removeprefix(PREFIXE_R2).removesuffix("-r2") + "-r4"
        document = {
            **{k: r2[k] for k in (
                "allowed_domains", "decision", "exclusions", "profile_id",
                "rights_categories", "valid_until",
            )},
            "profile_fingerprint": empreinte,
            "profile_version": profil.profile_version,
            "scope": {k: portee[k] for k in r2["scope"]},
            "allowed_content_sha256": contenus[collection],
            "authorization_id": identifiant,
            "manifest_digest": autorites["profile_manifest_sha256"],
            "pii_absence_attested": True,
            "pii_absence_evidence": f"{V4_DIR}/pii_evidence.json@sha256:{autorites['pii_evidence_sha256']}",
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
        print(f"R4_DIVERGENTES: {ecarts}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
