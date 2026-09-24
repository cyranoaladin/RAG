"""Les onze scopes de la release V4, émis par l'émetteur canonique (lot CZ).

Le registre V4 ne prend AUCUNE décision : il relie aux subjects de
`production-profile-gate-2026-2027-v4` les politiques déjà décidées au registre
V2 (ADR-0045, ADR-0052, ADR-0053). Ces tests prouvent trois choses, sur les
onze collections et non sur un échantillon :

* la politique V4 est IDENTIQUE, dimension par dimension, à celle du registre
  V2, qui reste inchangé ;
* chaque scope V4 packagé lie EXACTEMENT son subject V4, et son
  `evidence_subject` coïncide avec les placements sur TOUTES les dimensions
  croisées — `programme_version` et `visibility` compris, désormais égaux ;
* les octets packagés sont ceux que l'émetteur canonique refabrique.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from nexus_contracts import RetrievalScopeArtifactV2, load_retrieval_scope_registry
from nexus_contracts.scope import _RETRIEVAL_SCOPE_RESOURCES as PINNED

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACTS_ROOT.parents[1]
SCRIPTS_DIR = CONTRACTS_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_retrieval_scope_artifacts as emitter  # noqa: E402

V2_REGISTRY = REPO_ROOT / "docs/governance/retrieval_scope_policy_registry.yml"
V4_REGISTRY = REPO_ROOT / "docs/governance/retrieval_scope_policy_registry_v4.yml"
V2_SUCCESSORS = (
    CONTRACTS_ROOT / "authorities" / "production-profile-scope-successors-v2.yml"
)
V4_SUCCESSORS = (
    CONTRACTS_ROOT / "authorities" / "production-profile-scope-successors-v4.yml"
)
V4_RELEASE_DIR = REPO_ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/"
    "release-024f8625ebfeb7ce/profile_gate"
)
V4_MANIFEST = V4_RELEASE_DIR / "production-profile-gate.release.json"
V4_RELEASE_ID = "production-profile-gate-2026-2027-v4"
V4_MANIFEST_SHA256 = "bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be"

#: 52 après le lot CN, + les onze scopes V4.
PACKAGED_SCOPE_COUNT = 63

#: Valeurs de POLITIQUE : toutes reprises du registre V2, aucune décidée ici.
POLICY_FIELDS: tuple[str, ...] = (
    "decision_status",
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "corpus_provenance_id",
    "programme_version",
    "programme_taxonomy_path",
    "programme_taxonomy_sha256",
    "authority_source",
    "policy_source_scope_id",
    "policy_source_sha256",
    "programme_authority",
    "policy_visibility",
    "audiences",
    "rights",
    "target_audience",
    "target_candidates",
    "human_decision_status",
    "decision_reviewer",
    "decision_date",
    "target_identity_decision",
)

#: Dimensions qu'un placement déclare et que le scope doit reproduire.
CROSS_CHECKED = (
    "collection",
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "school_year",
    "visibility",
    "programme_version",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _yaml(path: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, Mapping)
    return payload


def _entries(path: Path) -> dict[str, Mapping[str, Any]]:
    return {str(e["collection"]): e for e in _yaml(path)["collections"]}


def _manifest() -> Mapping[str, Any]:
    return json.loads(V4_MANIFEST.read_bytes())


def _subjects() -> dict[str, str]:
    return {str(s["collection"]): str(s["sha256"]) for s in _manifest()["subjects"]}


def _placements(collection: str) -> list[Mapping[str, Any]]:
    path = V4_RELEASE_DIR / "subjects" / f"{collection}.release.json"
    placements = json.loads(path.read_bytes())["placements"]
    assert placements, collection
    return placements


def _declared_programme() -> dict[str, str]:
    payload = json.loads((V4_RELEASE_DIR / "programme_registry.json").read_bytes())
    return {
        str(t["collection"]): str(t["programme_version"]) for t in payload["taxonomies"]
    }


def _packaged_v4_scope(collection: str, sha256: str) -> RetrievalScopeArtifactV2:
    matches = [
        a
        for a in load_retrieval_scope_registry().values()
        if isinstance(a, RetrievalScopeArtifactV2)
        and a.evidence_subject.collection == collection
        and a.source_sha256 == sha256
    ]
    assert len(matches) == 1, (collection, len(matches))
    return matches[0]


# --- le registre V4 est lié à la release V4, et à elle seule --------------


def test_v4_registry_names_the_v4_release_and_its_digest() -> None:
    registry = _yaml(V4_REGISTRY)
    assert registry["registry_kind"] == "NEXUS_RETRIEVAL_SCOPE_POLICY_REGISTRY_V1"
    assert registry["release_id"] == V4_RELEASE_ID
    assert REPO_ROOT / str(registry["release_manifest_path"]) == V4_MANIFEST
    assert registry["release_manifest_sha256"] == V4_MANIFEST_SHA256
    assert _sha256(V4_MANIFEST) == V4_MANIFEST_SHA256
    assert _manifest()["release_id"] == V4_RELEASE_ID
    assert registry["predecessor_registry_path"] == (
        "docs/governance/retrieval_scope_policy_registry.yml"
    )


def test_v4_programme_authority_is_the_one_the_v4_release_embeds() -> None:
    authority = _yaml(V4_REGISTRY)["programme_version_authority"]
    path = REPO_ROOT / str(authority["path"])
    assert path == V4_RELEASE_DIR / "programme_registry.json"
    assert _sha256(path) == authority["sha256"]
    assert (
        authority["sha256"] == _manifest()["authorities"]["programme_registry_sha256"]
    )


def test_v4_registry_binds_every_v4_subject_exactly() -> None:
    subjects = _subjects()
    entries = _entries(V4_REGISTRY)
    assert len(subjects) == 11
    assert set(entries) == set(subjects)
    for collection, sha256 in subjects.items():
        assert entries[collection]["subject_manifest_sha256"] == sha256, collection


def test_v2_registry_is_left_on_the_v2_release() -> None:
    """Le registre historique n'est pas réaffecté : il reste lié à V2."""
    v2 = _yaml(V2_REGISTRY)
    assert v2["release_id"] == "production-profile-gate-2026-2027-v2"
    assert set(_entries(V2_REGISTRY)) == set(_entries(V4_REGISTRY))
    for collection, entry in _entries(V2_REGISTRY).items():
        assert entry["subject_manifest_sha256"] != _subjects()[collection]


# --- aucune décision nouvelle : la politique V4 est celle de V2 ----------


@pytest.mark.parametrize("field", POLICY_FIELDS)
def test_v4_policy_is_identical_to_the_v2_governed_decisions(field: str) -> None:
    v2 = _entries(V2_REGISTRY)
    for collection, entry in sorted(_entries(V4_REGISTRY).items()):
        assert entry.get(field) == v2[collection].get(field), (collection, field)


def test_the_three_human_decisions_stay_under_adr_0053() -> None:
    decided = {
        c
        for c, e in _entries(V4_REGISTRY).items()
        if e["decision_status"] == "GOVERNED_BY_HUMAN_DECISION"
    }
    assert decided == {
        "rag_nexus_hggsp_premiere_specialite",
        "rag_nexus_hggsp_terminale_specialite",
        "rag_nexus_hlp_terminale_specialite",
    }
    for collection in decided:
        entry = _entries(V4_REGISTRY)[collection]
        assert entry["authority_source"] == "NEXUS_HUMAN_DECISION_ADR_0053"
        assert entry["policy_source_scope_id"] is None
        assert entry["human_decision_status"] == "APPROVED_UNDER_ADR_0053"


def test_human_decisions_admissibility_is_recounted_on_v4() -> None:
    for collection, entry in sorted(_entries(V4_REGISTRY).items()):
        if entry["decision_status"] != "GOVERNED_BY_HUMAN_DECISION":
            continue
        evidence = entry["admissibility_evidence"]
        placements = _placements(collection)
        assert evidence["placements_total"] == len(placements), collection
        assert evidence["subject_manifest_sha256"] == entry["subject_manifest_sha256"]
        for field in ("review_status", "placement_status", "currentness"):
            assert {p[field] for p in placements} == {evidence[field]}, (
                collection,
                field,
            )


# --- ADR-0052 : évidence lue sur les placements, jamais élargie ----------


def test_v4_evidence_visibility_is_what_the_placements_declare() -> None:
    for collection, entry in sorted(_entries(V4_REGISTRY).items()):
        observed = {str(p["visibility"]) for p in _placements(collection)}
        assert observed == {"internal"}, collection
        assert entry["evidence_visibility"] == "internal", collection


def test_v4_policy_visibility_never_widens_the_evidence() -> None:
    registry = _yaml(V4_REGISTRY)
    order = list(registry["visibility_restriction_order"])
    assert order == ["public", "internal", "restricted", "private"]
    for collection, entry in sorted(_entries(V4_REGISTRY).items()):
        assert order.index(str(entry["policy_visibility"])) >= order.index(
            str(entry["evidence_visibility"])
        ), collection


def test_v4_programme_version_is_the_authority_s_and_the_placements() -> None:
    declared = _declared_programme()
    for collection, entry in sorted(_entries(V4_REGISTRY).items()):
        observed = {str(p["programme_version"]) for p in _placements(collection)}
        assert entry["programme_version"] == declared[collection], collection
        assert observed == {declared[collection]}, collection
        assert entry["corpus_provenance_id"] == "EDUSCOL_CORPUS_20260808"
        assert entry["corpus_provenance_id"] != entry["programme_version"]


# --- les onze scopes packagés ---------------------------------------------


def test_packaged_registry_size_is_pinned() -> None:
    assert len(load_retrieval_scope_registry()) == PACKAGED_SCOPE_COUNT


def test_every_v4_subject_is_packaged_exactly_once() -> None:
    for collection, sha256 in sorted(_subjects().items()):
        _packaged_v4_scope(collection, sha256)


def test_every_v4_scope_is_named_by_the_successor_authority() -> None:
    named = {
        str(b["collection"]): str(b["scope_id"])
        for b in _yaml(V4_SUCCESSORS)["bindings"]
    }
    assert _yaml(V4_SUCCESSORS)["release_id"] == V4_RELEASE_ID
    for collection, sha256 in sorted(_subjects().items()):
        assert _packaged_v4_scope(collection, sha256).scope_id == named[collection]


def test_every_v4_scope_is_the_successor_of_the_v2_scope() -> None:
    """ADR-0045 : `_v<N>` → `_v<N+1>`, sur la dernière version packagée."""
    v2_named = {
        str(b["collection"]): str(b["scope_id"])
        for b in _yaml(V2_SUCCESSORS)["bindings"]
    }
    v4_named = {
        str(b["collection"]): str(b["scope_id"])
        for b in _yaml(V4_SUCCESSORS)["bindings"]
    }
    assert set(v2_named) == set(v4_named)
    for collection, previous in v2_named.items():
        stem, _, version = previous.rpartition("_v")
        assert v4_named[collection] == f"{stem}_v{int(version) + 1}", collection
        versions = [
            int(s.rpartition("_v")[2]) for s in PINNED if s.rpartition("_v")[0] == stem
        ]
        # Le successeur V4 est la version la plus haute packagée : rien après.
        assert max(versions) == int(version) + 1, collection


def test_every_v4_scope_matches_its_placements_on_every_cross_checked_dimension() -> (
    None
):
    for collection, sha256 in sorted(_subjects().items()):
        evidence = _packaged_v4_scope(collection, sha256).evidence_subject.model_dump(
            mode="json"
        )
        placements = _placements(collection)
        for dimension in CROSS_CHECKED:
            observed = {str(p[dimension]) for p in placements}
            assert observed == {str(evidence[dimension])}, (collection, dimension)


def test_every_v4_scope_carries_the_decided_policy() -> None:
    entries = _entries(V4_REGISTRY)
    declared = _declared_programme()
    for collection, sha256 in sorted(_subjects().items()):
        artifact = _packaged_v4_scope(collection, sha256)
        entry = entries[collection]
        evidence = artifact.evidence_subject
        assert list(evidence.audiences) == list(entry["audiences"])
        assert [r.value for r in evidence.rights] == list(entry["rights"])
        assert evidence.visibility == entry["policy_visibility"]
        assert evidence.programme_version == declared[collection]
        assert artifact.target_identity.audience == entry["target_audience"]
        assert [c.value for c in artifact.target_identity.candidates] == list(
            entry["target_candidates"]
        )


def test_v4_scopes_differ_from_v2_scopes_only_by_their_binding() -> None:
    """Seuls `scope_id` et `source_sha256` changent : aucun droit ne bouge."""
    v2_named = {
        str(b["collection"]): str(b["scope_id"])
        for b in _yaml(V2_SUCCESSORS)["bindings"]
    }
    registry = load_retrieval_scope_registry()
    for collection, sha256 in sorted(_subjects().items()):
        v4 = _packaged_v4_scope(collection, sha256).model_dump(mode="json")
        v2 = registry[v2_named[collection]].model_dump(mode="json")
        for key in ("scope_id", "source_sha256"):
            assert v4.pop(key) != v2.pop(key), (collection, key)
        assert v4 == v2, collection


# --- l'émetteur canonique refabrique les octets packagés ----------------


def _emit(
    artifacts_dir: Path, *, reproduce: bool = True, registry: Path = V4_REGISTRY
) -> Any:
    scope_ids = frozenset(str(b["scope_id"]) for b in _yaml(V4_SUCCESSORS)["bindings"])
    return emitter.emit_from_policy_registry(
        subject_release=V4_MANIFEST,
        subject_release_sha256=V4_MANIFEST_SHA256,
        policy_registry=registry,
        policy_registry_sha256=_sha256(registry),
        successor_authority=V4_SUCCESSORS,
        successor_authority_sha256=_sha256(V4_SUCCESSORS),
        artifacts_dir=artifacts_dir,
        repo_root=REPO_ROOT,
        reproduce_scope_ids=scope_ids if reproduce else frozenset(),
    )


def test_reproduction_matches_the_packaged_bytes(tmp_path: Path) -> None:
    packaged_dir = CONTRACTS_ROOT / "src" / "nexus_contracts" / "artifacts"
    result = _emit(tmp_path)
    assert result.new_scope_count == 11
    for item in result.emitted:
        assert item.canonical_bytes == (packaged_dir / item.resource_name).read_bytes()
        assert PINNED[item.scope_id][1] == item.sha256, item.scope_id


def test_emission_is_deterministic(tmp_path: Path) -> None:
    first = {i.scope_id: i.canonical_bytes for i in _emit(tmp_path / "a").emitted}
    second = {i.scope_id: i.canonical_bytes for i in _emit(tmp_path / "b").emitted}
    assert first == second


def test_without_reproduction_the_v4_scopes_are_reused(tmp_path: Path) -> None:
    result = _emit(tmp_path, reproduce=False)
    assert result.new_scope_count == 0
    assert len(result.reused) == 11


def test_the_v2_registry_cannot_emit_for_the_v4_release(tmp_path: Path) -> None:
    """Le registre V2 lie les subjects V2 : il est refusé sur V4."""
    with pytest.raises(emitter.ScopeEmissionError, match="le registre lie le subject"):
        _emit(tmp_path, registry=V2_REGISTRY)


def test_a_public_evidence_claim_is_refused_against_internal_placements(
    tmp_path: Path,
) -> None:
    """Anti-circularité : l'évidence est lue sur les placements, pas écrite."""
    payload = dict(_yaml(V4_REGISTRY))
    payload["collections"] = [dict(e) for e in payload["collections"]]
    payload["collections"][0]["evidence_visibility"] = "public"
    staged = tmp_path / "registry.yml"
    staged.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    with pytest.raises(emitter.ScopeEmissionError, match="evidence_visibility"):
        _emit(tmp_path / "out", registry=staged)
