"""Preuves du registre gouverné de politique de scope (ADR-0052, ADR-0053).

Ces tests ne génèrent aucun scope et n'émettent aucun artefact. Ils prouvent
que `docs/governance/retrieval_scope_policy_registry.yml` **cite** une
politique déjà gouvernée au lieu d'en écrire une, et que les collections sans
source restent bloquantes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from nexus_contracts import RetrievalScopeArtifactV2, load_retrieval_scope_registry
from nexus_contracts.scope import _RETRIEVAL_SCOPE_RESOURCES as PINNED

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACTS_ROOT.parents[1]

REGISTRY_PATH = REPO_ROOT / "docs/governance/retrieval_scope_policy_registry.yml"

#: Les trois collections qu'ADR-0053 déclare bloquantes, faute d'autorité.
BLOCKED_COLLECTIONS = frozenset(
    {
        "rag_nexus_hggsp_premiere_specialite",
        "rag_nexus_hggsp_terminale_specialite",
        "rag_nexus_hlp_terminale_specialite",
    }
)

#: Taille du registre fermé avant ce lot. Aucun scope n'est ajouté ici.
PACKAGED_SCOPE_COUNT = 41


def _load_registry() -> Mapping[str, Any]:
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, Mapping)
    return payload


def _entries() -> dict[str, Mapping[str, Any]]:
    return {str(e["collection"]): e for e in _load_registry()["collections"]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_subjects() -> dict[str, str]:
    """Les collections de la release V2 et le digest de leur subject."""
    registry = _load_registry()
    manifest = REPO_ROOT / str(registry["release_manifest_path"])
    payload = json.loads(manifest.read_bytes())
    return {str(s["collection"]): str(s["sha256"]) for s in payload["subjects"]}


# --- 4. la release V2 scellée n'est pas touchée ---------------------------


def test_release_v2_manifest_digest_is_unchanged() -> None:
    registry = _load_registry()
    manifest = REPO_ROOT / str(registry["release_manifest_path"])
    assert _sha256(manifest) == registry["release_manifest_sha256"]


# --- 1. aucun scope n'est généré par ce lot -------------------------------


def test_no_scope_is_emitted_by_this_lot() -> None:
    assert len(load_retrieval_scope_registry()) == PACKAGED_SCOPE_COUNT


def test_blocked_collections_have_no_packaged_scope() -> None:
    """Aucune politique ne doit exister pour une collection bloquante."""
    packaged = {
        artifact.evidence_subject.collection
        for artifact in load_retrieval_scope_registry().values()
        if isinstance(artifact, RetrievalScopeArtifactV2)
    }
    assert not (BLOCKED_COLLECTIONS & packaged)


# --- 5. les onze collections V2 sont listées ------------------------------


def test_registry_covers_every_v2_collection_exactly() -> None:
    subjects = _release_subjects()
    entries = _entries()
    assert len(subjects) == 11
    assert set(entries) == set(subjects)
    for collection, sha256 in subjects.items():
        assert entries[collection]["subject_manifest_sha256"] == sha256


# --- 6. HGGSP/HLP : autorité explicite, ou bloquantes ---------------------


def test_blocked_collections_declare_no_policy_at_all() -> None:
    entries = _entries()
    for collection in sorted(BLOCKED_COLLECTIONS):
        entry = entries[collection]
        assert entry["decision_status"] == "BLOCKED_PENDING_HUMAN_DECISION"
        assert entry["human_decision_status"] == "PENDING_HUMAN_DECISION"
        # Aucune valeur d'accès, pas même une valeur restrictive par défaut.
        for dimension in ("authority_source", "policy_source_scope_id",
                          "policy_visibility", "audiences", "rights"):
            assert entry[dimension] is None, (collection, dimension)
        assert str(entry["justification"]).strip()


def test_every_collection_is_either_governed_or_blocked() -> None:
    statuses = {e["decision_status"] for e in _entries().values()}
    assert statuses <= {"GOVERNED", "BLOCKED_PENDING_HUMAN_DECISION"}


def test_governed_entries_are_exactly_the_non_blocked_ones() -> None:
    entries = _entries()
    governed = {c for c, e in entries.items() if e["decision_status"] == "GOVERNED"}
    assert governed == set(entries) - BLOCKED_COLLECTIONS
    assert len(governed) == 8


# --- le registre cite sa source, il n'écrit aucune politique --------------


def test_governed_policy_is_quoted_from_its_pinned_source() -> None:
    """Toute divergence entre le registre et sa source est un échec."""
    packaged = load_retrieval_scope_registry()
    for collection, entry in sorted(_entries().items()):
        if entry["decision_status"] != "GOVERNED":
            continue
        scope_id = str(entry["policy_source_scope_id"])
        assert entry["authority_source"] == "ADR-0045"
        assert scope_id in packaged, collection
        # Le digest cité est celui qu'épingle le registre fermé.
        assert entry["policy_source_sha256"] == PINNED[scope_id][1]
        artifact = packaged[scope_id]
        assert isinstance(artifact, RetrievalScopeArtifactV2)
        evidence = artifact.evidence_subject
        assert entry["policy_visibility"] == evidence.visibility
        assert list(entry["audiences"]) == list(evidence.audiences)
        assert list(entry["rights"]) == [r.value for r in evidence.rights]
        # Dimensions curriculaires : égalité stricte (ADR-0052 §1).
        for dimension in ("tenant", "matiere"):
            assert entry[dimension] == getattr(evidence, dimension), collection
        assert entry["niveau"] == evidence.niveau.value
        assert entry["voie"] == evidence.voie.value
        assert entry["statut_enseignement"] == evidence.statut_enseignement.value
        assert entry["candidat"] == evidence.candidat.value


# --- 7. la règle visibility est formalisée et exécutable ------------------


def test_visibility_order_covers_every_contract_value() -> None:
    order = list(_load_registry()["visibility_restriction_order"])
    assert order == ["public", "internal", "restricted", "private"]


def test_policy_visibility_never_widens_evidence_visibility() -> None:
    """ADR-0052 §3 : restreindre est permis, élargir est un refus."""
    registry = _load_registry()
    order = list(registry["visibility_restriction_order"])
    for collection, entry in sorted(_entries().items()):
        if entry["decision_status"] != "GOVERNED":
            continue
        evidence = str(entry["evidence_visibility"])
        policy = str(entry["policy_visibility"])
        assert evidence in order and policy in order, collection
        assert order.index(policy) >= order.index(evidence), collection


# --- 8. la règle programme_version est formalisée ------------------------


def test_programme_version_authority_is_declared_and_digested() -> None:
    authority = _load_registry()["programme_version_authority"]
    assert authority["authority_kind"] == "NEXUS_PROGRAMME_INDEX_REGISTRY_V3"
    path = REPO_ROOT / str(authority["path"])
    assert _sha256(path) == authority["sha256"]


def test_programme_version_is_read_from_its_authority_not_from_placements() -> None:
    registry = _load_registry()
    authority = registry["programme_version_authority"]
    payload = json.loads((REPO_ROOT / str(authority["path"])).read_bytes())
    declared = {
        str(t["collection"]): (str(t["programme_version"]), str(t["sha256"]))
        for t in payload["taxonomies"]
    }
    for collection, entry in sorted(_entries().items()):
        assert collection in declared, collection
        programme_version, taxonomy_sha256 = declared[collection]
        assert entry["programme_version"] == programme_version
        assert entry["programme_taxonomy_sha256"] == taxonomy_sha256
        # Le champ des placements est une provenance de corpus, pas une
        # référence de programme : il ne doit jamais valoir l'un pour l'autre.
        assert entry["corpus_provenance_id"] != entry["programme_version"]


# --- 9. l'émetteur futur dispose d'un contrat complet et testable ---------


def test_every_governed_entry_carries_all_emitter_inputs() -> None:
    required = (
        "collection", "subject_manifest_sha256", "tenant", "niveau", "voie",
        "matiere", "statut_enseignement", "candidat", "audiences", "rights",
        "policy_visibility", "evidence_visibility", "corpus_provenance_id",
        "programme_version", "programme_taxonomy_sha256", "authority_source",
        "policy_source_scope_id", "policy_source_sha256",
        "human_decision_status", "justification",
    )
    for collection, entry in sorted(_entries().items()):
        if entry["decision_status"] != "GOVERNED":
            continue
        for field in required:
            assert entry.get(field) is not None, (collection, field)


# --- 10. le dossier de provenance Drive n'est pas committé ---------------


def test_drive_provenance_directory_is_absent_from_the_repository() -> None:
    assert not (REPO_ROOT / "nexus_drive_provenance_8_authorities").exists()


# --- 2/3/4. ce lot ne touche ni runtime, ni readiness, ni release --------


def _changed_files_against_main() -> list[str] | None:
    """Fichiers changés par la branche, ou None si git ne peut pas répondre."""
    try:
        base = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        if base.returncode != 0:
            return None
        diff = subprocess.run(
            ["git", "diff", "--name-only", base.stdout.strip(), "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        if diff.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return [line for line in diff.stdout.splitlines() if line]


def test_lot_touches_only_governance_documents() -> None:
    changed = _changed_files_against_main()
    if changed is None:
        pytest.skip("dépôt git indisponible : invariant vérifié par ailleurs")
    allowed_prefixes = (
        "docs/adr/",
        "docs/governance/",
        "docs/reports/",
        "packages/contracts/tests/",
    )
    for path in changed:
        assert path.startswith(allowed_prefixes), path
        # Aucun runtime, aucun scope packagé, aucune release.
        assert not path.startswith("services/"), path
        assert not path.startswith("packages/contracts/src/"), path
