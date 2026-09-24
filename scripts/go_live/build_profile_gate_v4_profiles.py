#!/usr/bin/env python3
"""Dérive les onze profils de V4 et leur manifeste (ADR-0061).

Chaque profil V4 est le profil V2 de sa collection à trois champs près :

* ``profile_version`` : ``profile-gate-v3`` ;
* ``scope.programme_version`` : la référence officielle que la taxonomie de SA
  collection établit — celle que le registre de programme de la release déclare
  et que le scope de retrieval sert ;
* ``scope.visibility`` : la visibilité SERVIE par le scope de retrieval
  (ADR-0045), jamais plus large que celle du matériau.

La provenance du corpus (``EDUSCOL_CORPUS_20260808``) reste nommée par le
manifeste ; les profils historiques ne sont pas modifiés.

    python3 scripts/go_live/build_profile_gate_v4_profiles.py [--check]
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml

RACINE = Path(__file__).resolve().parents[2]
for _paquet in ("contracts", "release-chain", "pdf-page-policy"):
    sys.path.insert(0, str(RACINE / f"packages/{_paquet}/src"))

from nexus_release_chain.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
)

PROFILS = "services/rag-engine/configs/ingestion_profiles"
ANCIENS = f"{PROFILS}/v2_livraison_319"
NOUVEAUX = f"{PROFILS}/v3_livraison_315"
MANIFESTE = f"{PROFILS}/ingestion_manifest_v3_livraison_315.yml"
CONFIG_COLLECTIONS = "services/rag-engine/configs/rag_collections.yml"
TAXONOMIES = "services/rag-pedago/taxonomy"
POLITIQUE = "docs/governance/retrieval_scope_policy_registry.yml"
VERSION = "profile-gate-v3"
PROVENANCE_CORPUS = "EDUSCOL_CORPUS_20260808"
DATE = "2026-09-24T00:00:00+00:00"
APPROBATION = (
    "abenrhouma — décision voie S du 2026-09-24 (ADR-0061), confirmée par la "
    "revue humaine de la PR qui verse ces profils"
)
ORDRE_VISIBILITE = ("public", "internal", "restricted", "private")


def taxonomie_de(racine: Path, collection: str) -> dict[str, Any]:
    configuration = yaml.safe_load((racine / CONFIG_COLLECTIONS).read_text(encoding="utf-8"))
    fichier = configuration["collections"][collection]["taxonomy_file"]
    return yaml.safe_load((racine / TAXONOMIES / fichier).read_text(encoding="utf-8"))


def politique_de(racine: Path, collection: str) -> dict[str, Any]:
    """L'entrée gouvernée du registre de politique de retrieval (ADR-0048/0052)."""
    registre = yaml.safe_load((racine / POLITIQUE).read_text(encoding="utf-8"))
    entrees = [e for e in registre["collections"] if e["collection"] == collection]
    if len(entrees) != 1 or entrees[0]["decision_status"] not in (
        "GOVERNED", "GOVERNED_BY_HUMAN_DECISION"
    ):
        raise SystemExit(f"{collection} : aucune politique de retrieval gouvernée")
    return entrees[0]


def deriver_profils(racine: Path) -> dict[str, dict[str, Any]]:
    profils: dict[str, dict[str, Any]] = {}
    for fichier in sorted((racine / ANCIENS).glob("rag_nexus_*.yml")):
        ancien = yaml.safe_load(fichier.read_text(encoding="utf-8"))
        collection = ancien["scope"]["collection"]
        taxonomie = taxonomie_de(racine, collection)
        politique = politique_de(racine, collection)
        for dimension in ("niveau", "matiere"):
            if ancien["scope"][dimension] != taxonomie[dimension]:
                raise SystemExit(f"{collection} : {dimension} du profil ≠ taxonomie")
        if taxonomie["programme_version"] != politique["programme_version"]:
            raise SystemExit(f"{collection} : programme de la taxonomie ≠ programme servi")
        if politique["corpus_provenance_id"] != ancien["scope"]["programme_version"]:
            raise SystemExit(f"{collection} : provenance du corpus non reconnue")
        if politique["evidence_visibility"] != ancien["scope"]["visibility"] or (
            ORDRE_VISIBILITE.index(politique["policy_visibility"])
            < ORDRE_VISIBILITE.index(politique["evidence_visibility"])
        ):
            raise SystemExit(f"{collection} : la visibilité servie élargirait le matériau")
        nouveau = copy.deepcopy(ancien)
        nouveau["profile_version"] = VERSION
        nouveau["scope"]["programme_version"] = taxonomie["programme_version"]
        nouveau["scope"]["visibility"] = politique["policy_visibility"]
        profils[collection] = nouveau
    return profils


def _manifeste(racine: Path) -> dict[str, Any]:
    registre = load_profile_registry(racine / NOUVEAUX)
    entrees = [
        {
            "collection": profil.scope.collection,
            "profile_version": profil.profile_version,
            "fingerprint": profile_fingerprint(profil),
            "approved_by": APPROBATION,
            "approved_at": DATE,
        }
        for profil in sorted(registre.values(), key=lambda p: str(p.scope.collection))
    ]
    return {
        "manifest_version": "1",
        "provenance": (
            "Livraison V4 — les onze collections de la livraison 315 (V2/V3), "
            f"issues du corpus de provenance {PROVENANCE_CORPUS}. programme_version "
            "porte désormais la référence officielle de chaque collection (registre "
            "de programme de la release) ; la provenance du corpus est nommée ici. "
            "ADR-0061."
        ),
        "generated_at": DATE,
        "profiles": entrees,
    }


def _yaml(document: Any) -> str:
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=88)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    profils = deriver_profils(RACINE)
    dossier = RACINE / NOUVEAUX
    ecarts: list[str] = []
    if not args.check:
        dossier.mkdir(parents=True, exist_ok=True)
    for collection, profil in profils.items():
        chemin = dossier / f"{collection}.yml"
        if args.check:
            if not chemin.is_file() or yaml.safe_load(chemin.read_text(encoding="utf-8")) != profil:
                ecarts.append(str(chemin.relative_to(RACINE)))
        else:
            chemin.write_text(_yaml(profil), encoding="utf-8")
    manifeste = _manifeste(RACINE)
    chemin = RACINE / MANIFESTE
    if args.check:
        if not chemin.is_file() or yaml.safe_load(chemin.read_text(encoding="utf-8")) != manifeste:
            ecarts.append(MANIFESTE)
    else:
        chemin.write_text(_yaml(manifeste), encoding="utf-8")
    if ecarts:
        print(f"PROFILS_V4_DIVERGENTS: {ecarts}", file=sys.stderr)
        return 1
    print(f"PROFILS_V4 {len(profils)} {MANIFESTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
