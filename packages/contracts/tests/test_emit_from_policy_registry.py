"""Émission depuis le registre de politique gouverné : refus avant tout.

Chaque test ci-dessous RETIRE une garde d'ADR-0052/ADR-0053 en altérant une
entrée, et exige un refus. Une garde dont l'altération passerait ne prouverait
rien : c'est cette expérience-là, et non le succès du cas nominal, qui montre
que l'émission est fail-closed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACTS_ROOT.parents[1]
SCRIPTS_DIR = CONTRACTS_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_retrieval_scope_artifacts as emitter  # noqa: E402

POLICY_REGISTRY = REPO_ROOT / "docs/governance/retrieval_scope_policy_registry.yml"
SUCCESSOR_AUTHORITY = (
    CONTRACTS_ROOT / "authorities" / "production-profile-scope-successors-v2.yml"
)
SUBJECT_RELEASE = REPO_ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"
)

GOVERNED_COLLECTION = "rag_nexus_dgemc_terminale_option"
DECIDED_COLLECTION = "rag_nexus_hggsp_premiere_specialite"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: Les onze identifiants que ce lot a installés. Les nommer en REPRODUCTION
#: les retire de la recherche de réutilisation, afin que l'émetteur refabrique
#: ses propres octets et qu'on puisse les comparer à ce qui est packagé. Cela
#: n'ouvre aucun droit : le résultat est comparé au digest épinglé.
ALL_SCOPE_IDS = frozenset(
    str(b["scope_id"])
    for b in yaml.safe_load(SUCCESSOR_AUTHORITY.read_text(encoding="utf-8"))["bindings"]
)


def _emit(
    artifacts_dir: Path,
    *,
    registry_path: Path | None = None,
    successor_path: Path | None = None,
    reproduce: frozenset[str] = ALL_SCOPE_IDS,
) -> Any:
    registry_path = registry_path or POLICY_REGISTRY
    successor_path = successor_path or SUCCESSOR_AUTHORITY
    return emitter.emit_from_policy_registry(
        subject_release=SUBJECT_RELEASE,
        subject_release_sha256=_sha256(SUBJECT_RELEASE),
        policy_registry=registry_path,
        policy_registry_sha256=_sha256(registry_path),
        successor_authority=successor_path,
        successor_authority_sha256=_sha256(successor_path),
        artifacts_dir=artifacts_dir,
        repo_root=REPO_ROOT,
        reproduce_scope_ids=reproduce,
    )


def _registry_with(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    """Rendre une copie du registre, altérée par `mutate`."""
    payload = yaml.safe_load(POLICY_REGISTRY.read_text(encoding="utf-8"))
    mutate(payload)
    target = tmp_path / "registry.yml"
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return target


def _entry(payload: dict[str, Any], collection: str) -> dict[str, Any]:
    for item in payload["collections"]:
        if item["collection"] == collection:
            return item
    raise AssertionError(collection)


# --- Le cas nominal, pour que les refus aient un point de comparaison -----


def test_emits_one_scope_per_release_collection(tmp_path: Path) -> None:
    result = _emit(tmp_path)
    assert result.new_scope_count == 11
    assert result.subject_count == 11


def test_every_emitted_scope_binds_the_exact_release_subject(tmp_path: Path) -> None:
    release = json.loads(SUBJECT_RELEASE.read_bytes())
    expected = {str(s["collection"]): str(s["sha256"]) for s in release["subjects"]}
    result = _emit(tmp_path)
    observed = {item.collection: item.artifact.source_sha256 for item in result.emitted}
    assert observed == expected


def test_emission_is_deterministic(tmp_path: Path) -> None:
    first = {i.scope_id: i.canonical_bytes for i in _emit(tmp_path / "a").emitted}
    second = {i.scope_id: i.canonical_bytes for i in _emit(tmp_path / "b").emitted}
    assert first == second


def test_collections_without_predecessor_receive_a_first_version(
    tmp_path: Path,
) -> None:
    """Nommer `_v2` un scope sans prédécesseur laisserait croire à une histoire."""
    result = _emit(tmp_path)
    by_collection = {item.collection: item.scope_id for item in result.emitted}
    assert by_collection[DECIDED_COLLECTION] == "prod_hggsp_premiere_specialite_v1"
    assert by_collection[GOVERNED_COLLECTION] == "prod_dgemc_terminale_option_v2"


# --- ADR-0052 §3 — la visibilité ne s'élargit pas ------------------------


def _entry_with_visibility(evidence: str, policy: str) -> Any:
    """Une entrée synthétique, pour éprouver la règle SEULE.

    Sur les données réelles, la garde « divergence avec le scope source »
    intercepte d'abord toute altération d'une collection reconduite : c'est
    une défense en profondeur, mais elle empêche d'observer la règle de
    visibilité isolément. D'où cette entrée minimale.
    """
    return emitter.PolicyRegistryEntry(
        collection="rag_nexus_test",
        decision_status="GOVERNED_BY_HUMAN_DECISION",
        authority_source="NEXUS_HUMAN_DECISION_ADR_0053",
        policy_source_scope_id=None,
        subject_manifest_sha256="00" * 32,
        tenant="libre_terminale",
        niveau="terminale",
        voie="generale",
        matiere="test",
        statut_enseignement="specialite",
        candidat="libre",
        audiences=("libre",),
        rights=("officiel_public",),
        policy_visibility=policy,
        evidence_visibility=evidence,
        programme_version="BOEN_test",
        target_audience="libre",
        target_candidates=("libre",),
    )


ORDER = ("public", "internal", "restricted", "private")


@pytest.mark.parametrize(
    ("evidence", "policy"),
    [
        ("internal", "public"),
        ("restricted", "internal"),
        ("private", "public"),
    ],
)
def test_widening_policy_visibility_is_refused(evidence: str, policy: str) -> None:
    with pytest.raises(emitter.ScopeEmissionError, match="élargissement d'accès"):
        emitter._require_visibility_is_not_widened(
            _entry_with_visibility(evidence, policy), ORDER
        )


@pytest.mark.parametrize(
    ("evidence", "policy"),
    [
        ("public", "internal"),
        ("public", "public"),
        ("internal", "private"),
    ],
)
def test_restricting_policy_visibility_is_admitted(evidence: str, policy: str) -> None:
    emitter._require_visibility_is_not_widened(
        _entry_with_visibility(evidence, policy), ORDER
    )


@pytest.mark.parametrize("unknown", ["confidentiel", "", "PUBLIC"])
def test_unknown_visibility_value_is_refused(unknown: str) -> None:
    """Une valeur hors de l'ordre déclaré n'est comparée à rien : refus."""
    with pytest.raises(emitter.ScopeEmissionError, match="hors de l'ordre"):
        emitter._require_visibility_is_not_widened(
            _entry_with_visibility("public", unknown), ORDER
        )
    with pytest.raises(emitter.ScopeEmissionError, match="hors de l'ordre"):
        emitter._require_visibility_is_not_widened(
            _entry_with_visibility(unknown, "internal"), ORDER
        )


def test_evidence_visibility_must_match_the_placements(tmp_path: Path) -> None:
    """Sans ce croisement, la garde de visibilité serait circulaire."""

    def mutate(payload: dict[str, Any]) -> None:
        # « restricted » passerait l'ordre de restriction face à `internal`…
        _entry(payload, GOVERNED_COLLECTION)["evidence_visibility"] = "restricted"

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="evidence_visibility"):
        _emit(tmp_path / "out", registry_path=registry)


# --- ADR-0052 §2 — programme_version se lit chez son autorité ------------


def test_programme_version_diverging_from_its_authority_is_refused(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, GOVERNED_COLLECTION)["programme_version"] = "BOEN_inexistant"

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="programme_version"):
        _emit(tmp_path / "out", registry_path=registry)


def test_corpus_provenance_is_never_used_as_a_programme_reference(
    tmp_path: Path,
) -> None:
    """Le champ des placements ne doit jamais valoir référence de programme."""

    def mutate(payload: dict[str, Any]) -> None:
        entry = _entry(payload, GOVERNED_COLLECTION)
        entry["programme_version"] = entry["corpus_provenance_id"]

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="programme_version"):
        _emit(tmp_path / "out", registry_path=registry)


def test_programme_authority_digest_is_verified(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["programme_version_authority"]["sha256"] = "00" * 32

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="autorité de programme"):
        _emit(tmp_path / "out", registry_path=registry)


# --- ADR-0052 §1 — les dimensions curriculaires, égalité stricte ---------


def test_curricular_divergence_is_refused(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, GOVERNED_COLLECTION)["tenant"] = "aefe_terminale"

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="tenant"):
        _emit(tmp_path / "out", registry_path=registry)


def test_subject_placement_missing_a_dimension_is_refused(tmp_path: Path) -> None:
    """Une dimension absente est un refus, jamais une dispense de contrôle."""
    release_dir = SUBJECT_RELEASE.parent
    subject_path = release_dir / "subjects" / f"{GOVERNED_COLLECTION}.release.json"
    payload = json.loads(subject_path.read_bytes())
    stripped = copy.deepcopy(payload)
    for placement in stripped["placements"]:
        placement.pop("visibility", None)

    staged_subject = tmp_path / "subject.json"
    staged_subject.write_text(json.dumps(stripped), encoding="utf-8")
    with pytest.raises(emitter.ScopeEmissionError, match="visibility"):
        emitter.load_profile_subject_release(
            _staged_release(tmp_path, staged_subject),
            _sha256(_staged_release(tmp_path, staged_subject)),
        )


def _staged_release(tmp_path: Path, subject: Path) -> Path:
    """Composer une release minimale qui pointe le subject altéré."""
    manifest = tmp_path / "release.json"
    manifest.write_text(
        json.dumps(
            {
                "subjects": [
                    {
                        "collection": GOVERNED_COLLECTION,
                        "sha256": _sha256(subject),
                        "path": subject.name,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return manifest


# --- ADR-0053 — pas d'autorité, pas de scope -----------------------------


def test_collection_absent_from_the_registry_is_refused(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["collections"] = [
            item
            for item in payload["collections"]
            if item["collection"] != DECIDED_COLLECTION
        ]

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="aucune.*autorité|absente"):
        _emit(tmp_path / "out", registry_path=registry)


def test_entry_without_policy_is_refused(tmp_path: Path) -> None:
    """Le cas exact qu'ADR-0053 laissait ouvert avant la décision CM."""

    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, DECIDED_COLLECTION)["rights"] = None

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="rights absent"):
        _emit(tmp_path / "out", registry_path=registry)


def test_human_decision_claiming_a_policy_source_is_refused(tmp_path: Path) -> None:
    """Une décision humaine ne se déguise pas en reconduction."""

    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, DECIDED_COLLECTION)["policy_source_scope_id"] = (
            "prod_hlp_premiere_specialite_v1"
        )

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="décision humaine"):
        _emit(tmp_path / "out", registry_path=registry)


def test_human_decision_without_adr_authority_is_refused(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, DECIDED_COLLECTION)["authority_source"] = "ADR-0045"

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="ADR-0053"):
        _emit(tmp_path / "out", registry_path=registry)


def test_unknown_decision_status_is_refused(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, DECIDED_COLLECTION)["decision_status"] = "PRESUMED_OK"

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="statut de décision"):
        _emit(tmp_path / "out", registry_path=registry)


# --- Le registre cite, il ne devient pas une seconde autorité ------------


def test_governed_entry_diverging_from_its_packaged_source_is_refused(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, GOVERNED_COLLECTION)["audiences"] = ["libre", "aefe", "tous"]

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="diverge de son scope source"):
        _emit(tmp_path / "out", registry_path=registry)


def test_governed_target_identity_diverging_is_refused(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, GOVERNED_COLLECTION)["target_candidates"] = ["libre", "aefe"]

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="target_candidates"):
        _emit(tmp_path / "out", registry_path=registry)


# --- Digests et identifiants ---------------------------------------------


def test_registry_digest_is_verified(tmp_path: Path) -> None:
    staged = tmp_path / "registry.yml"
    staged.write_bytes(POLICY_REGISTRY.read_bytes())
    with pytest.raises(emitter.ScopeEmissionError, match="registre de politique"):
        emitter.load_policy_registry(staged, "00" * 32)


def test_subject_digest_divergence_is_refused(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _entry(payload, GOVERNED_COLLECTION)["subject_manifest_sha256"] = "11" * 32

    registry = _registry_with(tmp_path, mutate)
    with pytest.raises(emitter.ScopeEmissionError, match="le registre lie le subject"):
        _emit(tmp_path / "out", registry_path=registry)


def test_successor_authority_of_unknown_kind_is_refused(tmp_path: Path) -> None:
    payload = yaml.safe_load(SUCCESSOR_AUTHORITY.read_text(encoding="utf-8"))
    payload["authority_id"] = "SOMETHING_ELSE"
    staged = tmp_path / "successors.yml"
    staged.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(emitter.ScopeEmissionError, match="genre inconnu"):
        _emit(tmp_path / "out", successor_path=staged)


def test_duplicate_scope_id_in_the_naming_authority_is_refused(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(SUCCESSOR_AUTHORITY.read_text(encoding="utf-8"))
    payload["bindings"][1]["scope_id"] = payload["bindings"][0]["scope_id"]
    staged = tmp_path / "successors.yml"
    staged.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(emitter.ScopeEmissionError, match="collision de scope_id"):
        _emit(tmp_path / "out", successor_path=staged)


def test_emitting_over_a_pinned_scope_id_with_other_bytes_is_refused(
    tmp_path: Path,
) -> None:
    """Un identifiant déjà packagé ne peut pas changer de contenu."""
    payload = yaml.safe_load(SUCCESSOR_AUTHORITY.read_text(encoding="utf-8"))
    for binding in payload["bindings"]:
        if binding["collection"] == GOVERNED_COLLECTION:
            binding["scope_id"] = "prod_dgemc_terminale_option_v1"
    staged = tmp_path / "successors.yml"
    staged.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(emitter.ScopeEmissionError, match="collision de scope_id"):
        _emit(tmp_path / "out", successor_path=staged)


# --- Le chemin historique reste intact -----------------------------------


def test_legacy_multilevel_reader_still_requires_nested_placements() -> None:
    """Le lecteur multi-niveaux n'a pas été élargi pour accueillir l'autre forme."""
    with pytest.raises(emitter.ScopeEmissionError, match="aucun placement"):
        emitter._observed_subject_dimensions({"placements": [{"tenant": "x"}]}, 0)


def test_reproduction_matches_the_packaged_bytes(tmp_path: Path) -> None:
    """Refabriquer les onze doit rendre, octet pour octet, ce qui est packagé."""
    packaged_dir = CONTRACTS_ROOT / "src" / "nexus_contracts" / "artifacts"
    for item in _emit(tmp_path).emitted:
        packaged = packaged_dir / item.resource_name
        assert packaged.exists(), item.resource_name
        assert item.canonical_bytes == packaged.read_bytes(), item.scope_id


def test_without_reproduction_the_packaged_scopes_are_reused_not_reemitted(
    tmp_path: Path,
) -> None:
    """Un sujet déjà lié exactement n'a pas besoin d'un scope de plus."""
    result = _emit(tmp_path, reproduce=frozenset())
    assert result.new_scope_count == 0
    assert len(result.reused) == 11
