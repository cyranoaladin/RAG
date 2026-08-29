#!/usr/bin/env python3
"""Reconstruire la FIRST_SERVABLE_RELEASE depuis son membership déclaré.

Le producteur ne choisit rien. Il lit la liste explicite de
`first_servable_release_members.yml`, refuse fail-closed tout membre qui ne
satisfait pas les conditions d'appartenance, puis recalcule le registre, le
manifeste d'agrégat et leurs empreintes depuis les fichiers-sujets canoniques.

**Pourquoi pas un filtre.** `if instanciee: include` ferait disparaître
silencieusement un membre dont le drapeau bascule, et apparaître silencieusement
toute collection nouvellement instanciée. Les deux invariants sont
indépendants :

    RELEASE_MEMBER  =>  INSTANCIEE          imposé ici, fail-closed
    INSTANCIEE      =/=>  RELEASE_MEMBER    l'appartenance reste choisie

Les fichiers-sujets ne sont jamais réécrits : ce sont des artefacts canoniques
déjà scellés par leur SHA-256. Le producteur en sélectionne un sous-ensemble et
recalcule ce qui en dérive — comptes et empreintes — pour qu'aucun nombre ne
soit saisi à la main.

Usage :
    build_first_servable_release.py [--check]

`--check` n'écrit rien et sort en 1 si le résultat diffère de ce qui est
versionné : c'est la forme utilisable en CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOGUE = REPOSITORY_ROOT / "services/rag-engine/configs/rag_collections.yml"
PROFILES = REPOSITORY_ROOT / "services/rag-engine/configs/ingestion_profiles"
MEMBERSHIP = (
    REPOSITORY_ROOT / "services/rag-pedago/configs/first_servable_release_members.yml"
)
AUTHORITIES = (
    REPOSITORY_ROOT / "services/rag-pedago/configs/activation_authorities.yml"
)
RELEASES = REPOSITORY_ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
REGISTRY_PATH = RELEASES / "release-registry.json"
MANIFEST_PATH = RELEASES / "profile_gate/production-profile-gate.release.json"

#: Ensemble EXACT des champs qu'une entrée de registre peut porter, tel que
#: `release_readiness._REGISTRY_ENTRY_FIELDS` l'impose au moteur. Dupliqué ici
#: parce que `rag-pedago` n'importe jamais le code de `rag-engine` ; l'égalité
#: des deux ensembles est mesurée par un test, pas supposée.
REGISTRY_ENTRY_FIELDS = frozenset(
    {
        "release_id",
        "collections",
        "manifest_path",
        "expected_manifest_sha256",
        "release_kind",
    }
)


class ReleaseMembershipError(RuntimeError):
    """Un membre déclaré ne satisfait pas les conditions d'appartenance."""


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def canonical_json_bytes(document: Any) -> bytes:
    """Sérialisation stable : deux exécutions produisent les mêmes octets."""
    return (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _enabled_production_profiles() -> dict[str, str]:
    profiles: dict[str, str] = {}
    for path in sorted(PROFILES.glob("*.yml")):
        document = _load_yaml(path) or {}
        collection = (document.get("scope") or {}).get("collection")
        if collection and document.get("enabled"):
            if collection in profiles:
                raise ReleaseMembershipError(
                    f"{collection} has more than one enabled production profile: "
                    f"{profiles[collection]} and {path.name}"
                )
            profiles[str(collection)] = path.name
    return profiles


def require_membership_is_admissible(members: list[str]) -> None:
    """Refuser, sans jamais corriger de soi-même, tout membre inadmissible."""
    if not members:
        raise ReleaseMembershipError("a release with no declared member is not a release")
    if len(set(members)) != len(members):
        duplicates = sorted({name for name in members if members.count(name) > 1})
        raise ReleaseMembershipError(f"membership repeats collections: {duplicates}")

    catalogue = _load_yaml(CATALOGUE)["collections"]
    authorities = (_load_yaml(AUTHORITIES) or {}).get("collections") or {}
    profiles = _enabled_production_profiles()

    for collection in members:
        entry = catalogue.get(collection)
        if entry is None:
            raise ReleaseMembershipError(
                f"{collection} is declared a release member but is absent from the "
                "catalogue"
            )
        if entry.get("instanciee") is not True:
            raise ReleaseMembershipError(
                f"{collection} is declared a release member but is not instanciated "
                "— RELEASE_MEMBER => INSTANCIEE. Remove it from the membership, or "
                "instanciate it under a named activation authority. The producer "
                "never drops a declared member on its own."
            )
        if collection not in authorities:
            raise ReleaseMembershipError(
                f"{collection} is instanciated without a named activation authority "
                "— an activated collection must always be traceable to a decision"
            )
        if collection not in profiles:
            raise ReleaseMembershipError(
                f"{collection} has no enabled production ingestion profile"
            )

    missing_subjects = [
        collection
        for collection in members
        if not (RELEASES / "profile_gate/subjects" / f"{collection}.release.json").is_file()
    ]
    if missing_subjects:
        raise ReleaseMembershipError(
            f"no canonical subject release file for: {sorted(missing_subjects)}"
        )


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    """Recalculer registre et manifeste depuis les fichiers-sujets canoniques."""
    membership = _load_yaml(MEMBERSHIP)
    members = list(membership["members"])
    require_membership_is_admissible(members)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    by_collection = {entry["collection"]: entry for entry in manifest["subjects"]}

    subjects: list[dict[str, Any]] = []
    totals = {"artifacts": 0, "placements": 0, "chunks": 0}
    for collection in sorted(members):
        subject_path = RELEASES / "profile_gate/subjects" / f"{collection}.release.json"
        raw = subject_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        declared = by_collection.get(collection)
        if declared is not None and declared["sha256"] != digest:
            raise ReleaseMembershipError(
                f"the canonical subject file of {collection} no longer matches the "
                "digest the release recorded — resealing it is a separate decision"
            )
        counts = json.loads(raw.decode("utf-8"))["expected_counts"]
        for key in totals:
            totals[key] += counts[key]
        subjects.append(
            {
                "collection": collection,
                "path": f"subjects/{collection}.release.json",
                "sha256": digest,
            }
        )

    rebuilt_manifest = dict(manifest)
    rebuilt_manifest["subjects"] = subjects
    rebuilt_manifest["expected_counts"] = totals

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    previous = registry["releases"][0]
    # Le registre est une autorité RUNTIME au schéma FERMÉ : le moteur refuse
    # tout champ qu'il ne connaît pas (`releases[i] fields mismatch`). L'entrée
    # est donc reconstruite depuis l'ensemble exact des champs admis, jamais
    # copiée depuis le fichier existant — sinon un champ surnuméraire introduit
    # une fois se propagerait à chaque régénération suivante.
    #
    # Le fait « ce jalon n'est pas le GO-LIVE » est une donnée de gouvernance,
    # pas de runtime : il vit dans le membership versionné et est imposé par un
    # test, jamais injecté dans les octets que le moteur charge.
    release = {
        "release_id": previous["release_id"],
        "release_kind": previous["release_kind"],
        "manifest_path": previous["manifest_path"],
        "collections": sorted(members),
        "expected_manifest_sha256": hashlib.sha256(
            canonical_json_bytes(rebuilt_manifest)
        ).hexdigest(),
    }
    if set(release) != REGISTRY_ENTRY_FIELDS:
        raise ReleaseMembershipError(
            "the rebuilt registry entry does not match the runtime field set "
            f"{sorted(REGISTRY_ENTRY_FIELDS)}"
        )
    rebuilt_registry = dict(registry)
    rebuilt_registry["releases"] = [release]

    return rebuilt_registry, rebuilt_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="n'écrit rien ; sort en 1 si le versionné diffère du recalcul",
    )
    arguments = parser.parse_args(argv)

    try:
        registry, manifest = build()
    except (ReleaseMembershipError, KeyError, ValueError) as exc:
        print("FIRST_SERVABLE_RELEASE=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1

    registry_bytes = canonical_json_bytes(registry)
    manifest_bytes = canonical_json_bytes(manifest)

    if arguments.check:
        drifted = [
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path, expected in (
                (REGISTRY_PATH, registry_bytes),
                (MANIFEST_PATH, manifest_bytes),
            )
            if path.read_bytes() != expected
        ]
        if drifted:
            print("FIRST_SERVABLE_RELEASE=DRIFTED", file=sys.stderr)
            print(f"REASON=regenerate: {drifted}", file=sys.stderr)
            return 1
    else:
        MANIFEST_PATH.write_bytes(manifest_bytes)
        REGISTRY_PATH.write_bytes(registry_bytes)

    membership = _load_yaml(MEMBERSHIP)
    release = registry["releases"][0]
    print(f"RELEASE_NAME={membership['release_name']}")
    print(f"RELEASE_TYPE={membership['release_type']}")
    print(f"GO_LIVE_COMPLETE={str(membership['go_live_complete']).lower()}")
    print(f"EXPECTED_COLLECTIONS={len(release['collections'])}")
    for key in ("artifacts", "placements", "chunks"):
        print(f"EXPECTED_{key.upper()}={manifest['expected_counts'][key]}")
    print(f"REGISTRY_SHA256={hashlib.sha256(registry_bytes).hexdigest()}")
    print(f"MANIFEST_SHA256={release['expected_manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
