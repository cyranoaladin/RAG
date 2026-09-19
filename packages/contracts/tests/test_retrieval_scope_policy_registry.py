"""Preuves du registre gouverné de politique de scope (ADR-0052, ADR-0053).

Ces tests ne génèrent aucun scope et n'émettent aucun artefact. Ils prouvent
que chaque collection de la release V2 porte une politique dont l'autorité est
NOMMÉE : soit reconduite d'un scope packagé et vérifiée contre son digest
épinglé, soit assumée comme une décision humaine Nexus. Aucune valeur ne peut
être recopiée silencieusement d'une collection voisine.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import typing
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from nexus_contracts import RetrievalScopeArtifactV2, load_retrieval_scope_registry
from nexus_contracts.scope import RetrievalScopeEvidenceSubject, Rights
from nexus_contracts.scope import _RETRIEVAL_SCOPE_RESOURCES as PINNED

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACTS_ROOT.parents[1]

REGISTRY_PATH = REPO_ROOT / "docs/governance/retrieval_scope_policy_registry.yml"

#: Les trois collections dont la politique est une décision humaine (ADR-0053).
HUMAN_DECISION_COLLECTIONS = frozenset(
    {
        "rag_nexus_hggsp_premiere_specialite",
        "rag_nexus_hggsp_terminale_specialite",
        "rag_nexus_hlp_terminale_specialite",
    }
)

GOVERNED = "GOVERNED"
BY_HUMAN_DECISION = "GOVERNED_BY_HUMAN_DECISION"

#: Taille du registre fermé après l'émission des onze scopes de la release V2
#: (41 avant le lot CN). Le compte est épinglé : une entrée ajoutée sans test
#: fait échouer la suite.
PACKAGED_SCOPE_COUNT = 52

#: Vocabulaire canonique, dérivé du contrat et jamais réécrit ici.
CANONICAL_AUDIENCES = frozenset(
    typing.get_args(
        typing.get_args(RetrievalScopeEvidenceSubject.model_fields["audiences"].annotation)[0]
    )
)
CANONICAL_VISIBILITIES = frozenset(
    typing.get_args(RetrievalScopeEvidenceSubject.model_fields["visibility"].annotation)
)
CANONICAL_RIGHTS = frozenset(right.value for right in Rights)


def _load_registry() -> Mapping[str, Any]:
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, Mapping)
    return payload


def _entries() -> dict[str, Mapping[str, Any]]:
    return {str(e["collection"]): e for e in _load_registry()["collections"]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_subjects() -> dict[str, str]:
    registry = _load_registry()
    manifest = REPO_ROOT / str(registry["release_manifest_path"])
    payload = json.loads(manifest.read_bytes())
    return {str(s["collection"]): str(s["sha256"]) for s in payload["subjects"]}


# --- 8. aucune release n'est modifiée ------------------------------------


def test_release_v2_manifest_digest_is_unchanged() -> None:
    registry = _load_registry()
    manifest = REPO_ROOT / str(registry["release_manifest_path"])
    assert _sha256(manifest) == registry["release_manifest_sha256"]


# --- le registre fermé porte exactement ce qui a été décidé --------------


def test_packaged_registry_size_is_pinned() -> None:
    assert len(load_retrieval_scope_registry()) == PACKAGED_SCOPE_COUNT


def test_every_registry_collection_is_now_packaged_exactly_once() -> None:
    """Chaque collection de la release V2 a UN scope liant SON subject.

    C'est la question que `validate_release_startup_configuration` pose au
    démarrage : zéro correspondance est un refus, plusieurs aussi.
    """
    packaged = [
        artifact
        for artifact in load_retrieval_scope_registry().values()
        if isinstance(artifact, RetrievalScopeArtifactV2)
    ]
    for collection, entry in sorted(_entries().items()):
        matches = [
            artifact
            for artifact in packaged
            if artifact.evidence_subject.collection == collection
            and artifact.source_sha256 == entry["subject_manifest_sha256"]
        ]
        assert len(matches) == 1, (collection, len(matches))


def test_packaged_scopes_carry_the_decided_policy() -> None:
    """Le scope émis porte la politique du registre, à la lettre."""
    packaged = [
        artifact
        for artifact in load_retrieval_scope_registry().values()
        if isinstance(artifact, RetrievalScopeArtifactV2)
    ]
    for collection, entry in sorted(_entries().items()):
        artifact = next(
            a
            for a in packaged
            if a.evidence_subject.collection == collection
            and a.source_sha256 == entry["subject_manifest_sha256"]
        )
        evidence = artifact.evidence_subject
        assert list(evidence.audiences) == list(entry["audiences"]), collection
        assert [r.value for r in evidence.rights] == list(entry["rights"]), collection
        assert evidence.visibility == entry["policy_visibility"], collection
        assert evidence.programme_version == entry["programme_version"], collection
        target = artifact.target_identity
        assert target.audience == entry["target_audience"], collection
        assert [c.value for c in target.candidates] == list(
            entry["target_candidates"]
        ), collection


# --- 1/2. les onze collections portent une politique non nulle ------------


def test_registry_covers_every_v2_collection_exactly() -> None:
    subjects = _release_subjects()
    entries = _entries()
    assert len(subjects) == 11
    assert set(entries) == set(subjects)
    for collection, sha256 in subjects.items():
        assert entries[collection]["subject_manifest_sha256"] == sha256


def test_every_v2_collection_has_a_non_null_policy() -> None:
    for collection, entry in sorted(_entries().items()):
        for dimension in ("audiences", "rights", "policy_visibility"):
            assert entry[dimension] is not None, (collection, dimension)


def test_hggsp_and_hlp_decisions_are_no_longer_pending() -> None:
    entries = _entries()
    for collection in sorted(HUMAN_DECISION_COLLECTIONS):
        entry = entries[collection]
        assert entry["decision_status"] == BY_HUMAN_DECISION
        assert entry["human_decision_status"] == "APPROVED_UNDER_ADR_0053"
        assert entry["decision_reviewer"] == "abenrhouma"
        assert str(entry["decision_date"]).strip()
        assert str(entry["decision_binding"]).strip()


def test_every_collection_is_governed_or_humanly_decided() -> None:
    statuses = {e["decision_status"] for e in _entries().values()}
    assert statuses <= {GOVERNED, BY_HUMAN_DECISION}


def test_status_partition_matches_the_declared_collections() -> None:
    entries = _entries()
    decided = {c for c, e in entries.items() if e["decision_status"] == BY_HUMAN_DECISION}
    assert decided == HUMAN_DECISION_COLLECTIONS
    assert len(entries) - len(decided) == 8


# --- 3. aucune valeur n'est recopiée silencieusement ----------------------


def test_human_decisions_never_claim_a_policy_source() -> None:
    """Une décision humaine ne se déguise pas en reconduction."""
    entries = _entries()
    for collection in sorted(HUMAN_DECISION_COLLECTIONS):
        entry = entries[collection]
        assert entry["authority_source"] == "NEXUS_HUMAN_DECISION_ADR_0053"
        # `null` ici est la preuve qu'aucun scope voisin n'est invoqué.
        assert entry["policy_source_scope_id"] is None, collection
        assert "policy_source_sha256" not in entry, collection


def test_governed_policy_is_quoted_from_its_pinned_source() -> None:
    """Pour les 8 reconduites, toute divergence avec la source est un échec."""
    packaged = load_retrieval_scope_registry()
    for collection, entry in sorted(_entries().items()):
        if entry["decision_status"] != GOVERNED:
            continue
        scope_id = str(entry["policy_source_scope_id"])
        assert entry["authority_source"] == "ADR-0045"
        assert scope_id in packaged, collection
        assert entry["policy_source_sha256"] == PINNED[scope_id][1]
        artifact = packaged[scope_id]
        assert isinstance(artifact, RetrievalScopeArtifactV2)
        evidence = artifact.evidence_subject
        assert entry["policy_visibility"] == evidence.visibility
        assert list(entry["audiences"]) == list(evidence.audiences)
        assert list(entry["rights"]) == [r.value for r in evidence.rights]
        for dimension in ("tenant", "matiere"):
            assert entry[dimension] == getattr(evidence, dimension), collection
        assert entry["niveau"] == evidence.niveau.value
        assert entry["voie"] == evidence.voie.value
        assert entry["statut_enseignement"] == evidence.statut_enseignement.value
        assert entry["candidat"] == evidence.candidat.value


# --- 4. chaque décision porte une source d'autorité -----------------------


def test_every_collection_declares_an_authority_source() -> None:
    allowed = {"ADR-0045", "NEXUS_HUMAN_DECISION_ADR_0053"}
    for collection, entry in sorted(_entries().items()):
        assert entry["authority_source"] in allowed, collection
        assert str(entry["justification"]).strip(), collection


def test_human_decisions_carry_sourced_admissibility_evidence() -> None:
    """L'admissibilité se prouve sur la release scellée, pas par affirmation."""
    D = REPO_ROOT / (
        "services/rag-pedago/data/releases/prerentree_2026_2027/"
        "profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate"
    )
    entries = _entries()
    for collection in sorted(HUMAN_DECISION_COLLECTIONS):
        entry = entries[collection]
        assert entry["admissibility_status"] == "ADMISSIBLE_ON_SEALED_RELEASE_EVIDENCE"
        evidence = entry["admissibility_evidence"]
        subject = json.loads((D / "subjects" / f"{collection}.release.json").read_bytes())
        placements = subject["placements"]
        # Chaque chiffre annoncé est recompté sur la release elle-même.
        assert evidence["placements_total"] == len(placements)
        assert evidence["subject_manifest_sha256"] == entry["subject_manifest_sha256"]
        for field in ("review_status", "placement_status", "currentness"):
            observed = {p[field] for p in placements}
            assert observed == {evidence[field]}, (collection, field)


# --- 5. policy_visibility n'élargit jamais evidence_visibility ------------


def test_visibility_order_covers_every_contract_value() -> None:
    order = list(_load_registry()["visibility_restriction_order"])
    assert order == ["public", "internal", "restricted", "private"]
    assert set(order) == CANONICAL_VISIBILITIES


def test_policy_visibility_never_widens_evidence_visibility() -> None:
    """ADR-0052 §3 — sur les ONZE, décisions humaines comprises."""
    order = list(_load_registry()["visibility_restriction_order"])
    for collection, entry in sorted(_entries().items()):
        evidence = str(entry["evidence_visibility"])
        policy = str(entry["policy_visibility"])
        assert evidence in order and policy in order, collection
        assert order.index(policy) >= order.index(evidence), collection


# --- 6. programme_version est résolue via son autorité --------------------


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
        assert entry["corpus_provenance_id"] != entry["programme_version"]


def test_human_decisions_name_the_programme_authority() -> None:
    entries = _entries()
    for collection in sorted(HUMAN_DECISION_COLLECTIONS):
        assert entries[collection]["programme_authority"] == (
            "NEXUS_PROGRAMME_INDEX_REGISTRY_V3"
        ), collection


# --- 7. rights et audiences restent dans le vocabulaire canonique ---------


def test_rights_and_audiences_use_only_canonical_values() -> None:
    for collection, entry in sorted(_entries().items()):
        assert set(entry["audiences"]) <= CANONICAL_AUDIENCES, collection
        assert set(entry["rights"]) <= CANONICAL_RIGHTS, collection
        assert entry["policy_visibility"] in CANONICAL_VISIBILITIES, collection
        assert entry["audiences"], collection
        assert entry["rights"], collection


# --- contrat complet pour l'émetteur futur --------------------------------


def test_every_entry_carries_all_emitter_inputs() -> None:
    common = (
        "collection", "subject_manifest_sha256", "tenant", "niveau", "voie",
        "matiere", "statut_enseignement", "candidat", "audiences", "rights",
        "policy_visibility", "evidence_visibility", "corpus_provenance_id",
        "programme_version", "programme_taxonomy_sha256", "authority_source",
        "human_decision_status", "justification",
    )
    for collection, entry in sorted(_entries().items()):
        for field in common:
            assert entry.get(field) is not None, (collection, field)
        if entry["decision_status"] == GOVERNED:
            for field in ("policy_source_scope_id", "policy_source_sha256"):
                assert entry.get(field) is not None, (collection, field)
        else:
            for field in ("decision_reviewer", "decision_date",
                          "admissibility_status", "admissibility_evidence"):
                assert entry.get(field) is not None, (collection, field)


# --- 10. le dossier de provenance Drive n'est pas committé ---------------


def test_drive_provenance_directory_is_absent_from_the_repository() -> None:
    assert not (REPO_ROOT / "nexus_drive_provenance_8_authorities").exists()


# --- invariants permanents du dépôt, mesurés sur le diff de la branche ---


def _changed_against_main() -> list[tuple[str, str]] | None:
    """(statut, chemin) pour chaque fichier que la branche change."""
    try:
        base = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        if base.returncode != 0:
            return None
        diff = subprocess.run(
            ["git", "diff", "--name-status", base.stdout.strip(), "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        if diff.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    changed: list[tuple[str, str]] = []
    for line in diff.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        changed.append((parts[0], parts[-1]))
    return changed


def test_no_release_file_is_ever_modified() -> None:
    """Une release scellée ne se retouche pas pour faire passer une émission."""
    changed = _changed_against_main()
    if changed is None:
        pytest.skip("dépôt git indisponible")
    for status, path in changed:
        assert not path.startswith(
            "services/rag-pedago/data/releases/"
        ), (status, path)


def test_no_preexisting_scope_artifact_is_modified() -> None:
    """ADR-0045 : un nouveau subject reçoit un NOUVEL artefact, jamais une
    mutation silencieuse d'un artefact déjà adressable. Seuls les ajouts
    (`A`) sont admis sous `artifacts/`."""
    changed = _changed_against_main()
    if changed is None:
        pytest.skip("dépôt git indisponible")
    artifacts = "packages/contracts/src/nexus_contracts/artifacts/"
    for status, path in changed:
        if path.startswith(artifacts):
            assert status == "A", (status, path)
