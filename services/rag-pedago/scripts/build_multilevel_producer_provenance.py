#!/usr/bin/env python3
"""Attester la provenance de la lignée de production multi-niveaux régénérée.

Une release dit CE QUI EXISTE. Une attestation de provenance dit **d'où cela
vient** : quel code l'a produite, sur quelles entrées, sous quel runtime
d'extraction, et à quels scopes elle est liée. Sans elle, un artefact servi
est un fait sans histoire — on peut le vérifier, on ne peut pas le refaire.

**L'attestation précédente n'est pas étendue.** Celle du 2026-08-25
(`docs/reports/release_scope_placement_provenance_20260825.json`) atteste une
autre lignée : d'autres releases par collection, d'autres empreintes. La
recycler pour couvrir la lignée régénérée reviendrait à faire dire à une
preuve datée ce qu'elle n'a jamais constaté. Elle reste octet-identique ; une
attestation neuve est émise pour la lignée neuve.

Usage :

    python scripts/build_multilevel_producer_provenance.py            # écrit
    python scripts/build_multilevel_producer_provenance.py --check    # compare
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

#: Racines dérivées de l'emplacement de ce fichier — jamais un chemin absolu
#: de poste de travail.
PEDAGO_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PEDAGO_ROOT.parents[1]

RELEASE_ROOT = (
    PEDAGO_ROOT / "data" / "releases" / "prerentree_2026_2027" / "multilevel"
)
PREFLIGHT_PATH = RELEASE_ROOT / "multilevel_preflight.json"
RELEASE_PATH = RELEASE_ROOT / "multilevel.release.json"

#: Le code qui produit la lignée : le préflight, puis la release. Les deux
#: sont hachés, car changer l'un change ce qui sort de l'autre.
PRODUCER_SOURCES = (
    "services/rag-pedago/scripts/build_multilevel_preflight.py",
    "services/rag-pedago/scripts/build_multilevel_release.py",
)

#: Les scopes de retrieval que cette lignée lie. Ils ne sont pas une entrée du
#: producteur : ils sont ce à quoi la release donne droit, et une attestation
#: qui ne les nommerait pas laisserait la moitié de la chaîne hors preuve.
SCOPE_REGISTRY_SOURCE = (
    "packages/contracts/src/nexus_contracts/scope.py"
)

ATTESTATION_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "reports"
    / "multilevel_producer_provenance_20260906.json"
)

ATTESTATION_KIND = "MULTILEVEL_PRODUCER_PROVENANCE_V1"


class ProvenanceError(RuntimeError):
    """Une entrée de provenance manque ou ne se laisse pas relire."""


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ProvenanceError(f"entrée de provenance illisible : {path}") from exc


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


def _source_commit() -> str:
    """Le commit du dépôt au moment de l'émission, ou l'échec explicite.

    Une attestation qui ne sait pas d'où elle a été produite n'atteste rien.
    """
    completed = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProvenanceError("commit source indisponible : git a refusé")
    return completed.stdout.strip()


def _contracts_version() -> str:
    pyproject = REPOSITORY_ROOT / "packages" / "contracts" / "pyproject.toml"
    return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])


def _preflight() -> dict:
    return json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))


def _input_manifest_shas(preflight: dict) -> dict[str, str]:
    """Les entrées que le préflight NOMME, relues du préflight lui-même.

    Les recopier ici en dur ferait deux vérités : celle du préflight et celle
    de l'attestation, qui divergeraient au premier rescellement.
    """
    named = {
        "candidate_inventory": "candidate_inventory_sha256",
        "corpus_manifest": "corpus_manifest_sha256",
        "currentness_evidence": "currentness_evidence_sha256",
        "pii_evidence": "pii_evidence_sha256",
        "pii_policy": "pii_policy_sha256",
        "profile_manifest": "profile_manifest_sha256",
        "programme_registry": "programme_registry_sha256",
        "rights_registry": "rights_registry_sha256",
        "embedding_inventory": "embedding_inventory_sha256",
    }
    shas: dict[str, str] = {}
    for label, key in named.items():
        value = preflight.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ProvenanceError(f"le préflight ne nomme pas {key}")
        shas[label] = value
    return shas


def _bound_scope_ids(subjects: list[dict]) -> list[str]:
    """Les scopes que le runtime sélectionnera pour ces subjects, mesurés.

    Le runtime choisit un scope par le couple exact
    ``(collection, source_sha256)``. L'attestation rejoue cette sélection au
    lieu de nommer des scopes de mémoire : une liaison qui n'existerait plus
    ferait échouer l'émission, pas passer une attestation fausse.
    """
    sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "contracts" / "src"))
    from nexus_contracts import (  # noqa: PLC0415
        RetrievalScopeArtifactV2,
        load_retrieval_scope_registry,
    )

    registry = load_retrieval_scope_registry()
    bound: list[str] = []
    for subject in subjects:
        collection = str(subject["collection"])
        source_sha256 = str(subject["sha256"])
        matches = sorted(
            scope_id
            for scope_id, artifact in registry.items()
            if isinstance(artifact, RetrievalScopeArtifactV2)
            and str(artifact.evidence_subject.collection) == collection
            and artifact.source_sha256 == source_sha256
        )
        if len(matches) != 1:
            raise ProvenanceError(
                f"{collection} : {len(matches)} scope(s) lié(s) à {source_sha256[:12]}…"
                " — la sélection du runtime doit être exacte"
            )
        bound.append(matches[0])
    return sorted(bound)


def build_attestation() -> dict:
    preflight = _preflight()
    runtime = preflight.get("extraction_runtime")
    if not isinstance(runtime, dict) or set(runtime) != {
        "page_policy_id",
        "page_policy_sha256",
        "pypdf_version",
    }:
        raise ProvenanceError("le préflight ne nomme pas son runtime d'extraction")

    release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
    subjects = release.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise ProvenanceError("la release ne déclare aucun subject")

    return {
        "attestation_kind": ATTESTATION_KIND,
        "source_commit_sha": _source_commit(),
        "producer_code_sha256": {
            source: _sha256(REPOSITORY_ROOT / source) for source in PRODUCER_SOURCES
        },
        "input_manifest_sha256": _input_manifest_shas(preflight),
        "preflight_sha256": _sha256(PREFLIGHT_PATH),
        "preflight_kind": preflight.get("evidence_kind"),
        "multilevel_release_sha256": _sha256(RELEASE_PATH),
        "multilevel_release_id": release.get("release_id"),
        "subject_count": len(subjects),
        "scope_registry_sha256": _sha256(REPOSITORY_ROOT / SCOPE_REGISTRY_SOURCE),
        "bound_scope_ids": _bound_scope_ids(subjects),
        "subject_manifest_sha256_by_collection": {
            str(subject["collection"]): str(subject["sha256"])
            for subject in sorted(subjects, key=lambda item: str(item["collection"]))
        },
        "contracts_version": _contracts_version(),
        "page_policy_sha256": runtime["page_policy_sha256"],
        "extractor_identity": {
            "page_policy_id": runtime["page_policy_id"],
            "pypdf_version": runtime["pypdf_version"],
        },
        # Le budget de découpage est compté par le tokenizer du modèle
        # d'embedding : ce sont donc son identifiant et sa révision qui
        # nomment le découpeur, pas un « compteur de jetons » distinct qui
        # n'existe pas.
        "chunker_identity": {
            "chunker": "ingestor.publication_chunking.chunk_publication",
            "target_tokens": preflight.get("chunk_target_tokens"),
            "embedding_model_id": preflight.get("embedding_model_id"),
            "embedding_model_revision": preflight.get("embedding_model_revision"),
            "max_sequence_length": preflight.get("embedding_max_sequence_length"),
        },
        "school_year": preflight.get("school_year"),
    }


def serialize(attestation: dict) -> bytes:
    """Forme canonique : clés triées, indentation fixe, saut de ligne final."""
    return (
        json.dumps(attestation, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="comparer sans écrire")
    parser.add_argument("--output", type=Path, default=ATTESTATION_PATH)
    arguments = parser.parse_args()

    rendered = serialize(build_attestation())
    output: Path = arguments.output

    if arguments.check:
        if not output.is_file():
            print(f"PROVENANCE_ATTESTATION_MISSING={output}", file=sys.stderr)
            return 1
        if output.read_bytes() != rendered:
            print("PROVENANCE_ATTESTATION_DRIFT=1", file=sys.stderr)
            return 1
        print("PROVENANCE_ATTESTATION_DRIFT=0")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rendered)
    print(f"NEW_PROVENANCE_ATTESTATION_WRITTEN={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
