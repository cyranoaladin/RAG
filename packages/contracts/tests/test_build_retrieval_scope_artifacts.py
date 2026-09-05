"""Émetteur canonique des scopes de retrieval : dérivation, refus et déterminisme.

L'émetteur sépare deux familles d'entrées : la RELEASE-SUJET, qui ne dit que ce
qui existe, et l'AUTORITÉ DE POLITIQUE, qui seule dit qui peut voir quoi. Les
tests ci-dessous prouvent que la première ne peut jamais devenir la seconde.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from nexus_contracts import RetrievalScopeArtifactV2

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACTS_ROOT.parents[1]
SCRIPTS_DIR = CONTRACTS_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_retrieval_scope_artifacts as emitter  # noqa: E402

POLICY_AUTHORITY = CONTRACTS_ROOT / "authorities" / "multilevel-retrieval-scope-policy-v1.yml"
SUBJECT_RELEASE = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json"
)
ARTIFACTS_DIR = CONTRACTS_ROOT / "src" / "nexus_contracts" / "artifacts"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_scope_ids(policy_authority: Path = POLICY_AUTHORITY) -> frozenset[str]:
    payload = yaml.safe_load(policy_authority.read_text(encoding="utf-8"))
    return frozenset(binding["scope_id"] for binding in payload["bindings"])


def _run(
    tmp_path: Path,
    *,
    policy_authority: Path | None = None,
    subject_release: Path | None = None,
    reproduce: bool = True,
) -> emitter.EmissionResult:
    """Rejouer l'émission. `reproduce` refabrique les scopes déjà installés."""
    policy = policy_authority or POLICY_AUTHORITY
    release = subject_release or SUBJECT_RELEASE
    return emitter.emit_retrieval_scope_artifacts(
        subject_release=release,
        subject_release_sha256=_sha256(release),
        policy_authority=policy,
        policy_authority_sha256=_sha256(policy),
        artifacts_dir=tmp_path,
        # La reproduction retire toujours les DIX scopes que l'autorité
        # canonique déclare : on rejoue l'état du registre au moment de la
        # décision d'émission, pas l'état d'après.
        reproduce_scope_ids=_declared_scope_ids() if reproduce else frozenset(),
    )


def _emit(
    tmp_path: Path,
    *,
    policy_authority: Path | None = None,
    subject_release: Path | None = None,
    reproduce: bool = True,
) -> tuple[emitter.EmittedScope, ...]:
    return _run(
        tmp_path,
        policy_authority=policy_authority,
        subject_release=subject_release,
        reproduce=reproduce,
    ).emitted


def _mutated_authority(tmp_path: Path, mutate: Any) -> Path:
    payload = yaml.safe_load(POLICY_AUTHORITY.read_text(encoding="utf-8"))
    mutate(payload)
    target = tmp_path / "policy.yml"
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def _mutated_release(tmp_path: Path, mutate: Any) -> Path:
    """Recopier la release-sujet dans un arbre isolé, puis muter un subject."""
    source_root = SUBJECT_RELEASE.parent
    target_root = tmp_path / "release"
    aggregate = json.loads(SUBJECT_RELEASE.read_text(encoding="utf-8"))
    subjects: list[dict[str, Any]] = []
    for entry in aggregate["subjects"]:
        raw = (source_root / entry["path"]).read_bytes()
        subjects.append(
            {"entry": entry, "payload": json.loads(raw), "raw": raw, "before": json.loads(raw)}
        )
    mutate(aggregate, subjects)
    for item in subjects:
        path = target_root / item["entry"]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        # Un subject non muté conserve ses octets d'origine : seul le subject
        # que le test touche doit changer de digest.
        raw = (
            item["raw"]
            if item["payload"] == item["before"]
            else json.dumps(item["payload"], ensure_ascii=False, indent=2).encode("utf-8")
        )
        path.write_bytes(raw)
        item["entry"]["sha256"] = hashlib.sha256(raw).hexdigest()
    target = target_root / SUBJECT_RELEASE.name
    target.write_bytes(json.dumps(aggregate, ensure_ascii=False, indent=2).encode("utf-8"))
    return target


def _set_placement_dimension(subject: dict[str, Any], dimension: str, value: str) -> None:
    for artifact in subject["payload"]["artifacts"]:
        for placement in artifact["placements"]:
            placement[dimension] = value


# --- Émission nominale -------------------------------------------------------


def test_emitted_scope_count_is_measured_from_the_release(tmp_path: Path) -> None:
    """NEW_SCOPE_COUNT est le résultat du calcul de réutilisation, jamais un chiffre supposé."""
    aggregate = json.loads(SUBJECT_RELEASE.read_text(encoding="utf-8"))

    result = _run(tmp_path)

    assert result.subject_count == len(aggregate["subjects"])
    assert result.new_scope_count == len(result.emitted)
    assert result.new_scope_count + len(result.reused) == result.subject_count
    assert [item.scope_id for item in result.emitted] == [
        binding["scope_id"]
        for binding in yaml.safe_load(POLICY_AUTHORITY.read_text(encoding="utf-8"))["bindings"]
    ]


def test_every_subject_of_the_regenerated_release_needs_a_new_binding(
    tmp_path: Path,
) -> None:
    """EXACT_EXISTING_MATCH mesuré à 0 pour chaque sujet, hors sorties de ce run."""
    aggregate = json.loads(SUBJECT_RELEASE.read_text(encoding="utf-8"))
    declared = frozenset(
        binding["scope_id"]
        for binding in yaml.safe_load(POLICY_AUTHORITY.read_text(encoding="utf-8"))["bindings"]
    )

    for entry in aggregate["subjects"]:
        assert (
            emitter.exact_existing_matches(
                entry["collection"], entry["sha256"], excluded_scope_ids=declared
            )
            == ()
        )
    assert _run(tmp_path).reused == ()


def test_a_subject_already_bound_exactly_is_reused_and_not_re_emitted(
    tmp_path: Path,
) -> None:
    """Une fois les scopes installés, réémettre ne produit rien : tout est lié."""
    aggregate = json.loads(SUBJECT_RELEASE.read_text(encoding="utf-8"))
    first = aggregate["subjects"][0]

    assert emitter.exact_existing_matches(first["collection"], first["sha256"]) == (
        "entree_premiere_maths_v2",
    )

    result = _run(tmp_path, reproduce=False)

    assert result.emitted == ()
    assert result.new_scope_count == 0
    assert len(result.reused) == len(aggregate["subjects"])
    assert not list(tmp_path.iterdir())


def test_source_sha256_is_the_exact_subject_manifest_digest(tmp_path: Path) -> None:
    aggregate = json.loads(SUBJECT_RELEASE.read_text(encoding="utf-8"))
    expected = {entry["collection"]: entry["sha256"] for entry in aggregate["subjects"]}

    for item in _emit(tmp_path):
        assert item.artifact.source_sha256 == expected[str(item.collection)]


def test_no_authorization_dimension_is_derived_from_the_release(tmp_path: Path) -> None:
    """AUTHORIZATION_SEMANTIC_DIFF == 0 : la politique émise est celle de sa source.

    La comparaison exclut `scope_id` et `source_sha256` — seuls porteurs de la
    nouvelle liaison — et porte sur tout le reste.
    """
    for item in _emit(tmp_path):
        policy = emitter.load_policy_source(item.policy_source_scope_id)
        assert emitter.authorization_semantic_diff(item.artifact, policy) == {}
        assert item.artifact.target_identity == policy.target_identity
        assert item.artifact.evidence_subject == policy.evidence_subject
        assert item.artifact.status == policy.status
        assert item.artifact.scope_id != policy.scope_id
        assert item.artifact.source_sha256 != policy.source_sha256
        assert item.artifact.sha256_digest() != policy.sha256_digest()


def test_emitted_scope_id_is_the_governed_successor(tmp_path: Path) -> None:
    for item in _emit(tmp_path):
        stem, version = item.policy_source_scope_id.rsplit("_v", 1)
        assert item.scope_id == f"{stem}_v{int(version) + 1}"


def test_emitted_bytes_match_the_packaged_artifacts(tmp_path: Path) -> None:
    """L'émetteur reproduit octet pour octet ce que le paquet embarque."""
    for item in _emit(tmp_path):
        packaged = ARTIFACTS_DIR / item.resource_name
        assert packaged.read_bytes() == (tmp_path / item.resource_name).read_bytes()


def test_emission_is_byte_for_byte_deterministic(tmp_path: Path) -> None:
    """SCOPE_EMITTER_DETERMINISTIC : deux exécutions, mêmes octets."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    index_first = tmp_path / "first-index.json"
    index_second = tmp_path / "second-index.json"

    reproduce: list[str] = []
    for scope_id in sorted(_declared_scope_ids()):
        reproduce += ["--reproduce-scope-id", scope_id]

    for output, index in ((first, index_first), (second, index_second)):
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "build_retrieval_scope_artifacts.py"),
                "--subject-release",
                str(SUBJECT_RELEASE),
                "--subject-release-sha256",
                _sha256(SUBJECT_RELEASE),
                "--policy-authority",
                str(POLICY_AUTHORITY),
                "--policy-authority-sha256",
                _sha256(POLICY_AUTHORITY),
                "--artifacts-dir",
                str(output),
                "--registry-index",
                str(index),
                *reproduce,
            ],
            check=True,
            cwd=tmp_path,
        )

    produced = sorted(path.name for path in first.iterdir())
    assert produced == sorted(path.name for path in second.iterdir())
    for name in produced:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert index_first.read_bytes() == index_second.read_bytes()


def test_canonical_bytes_carry_no_local_path_nor_timestamp(tmp_path: Path) -> None:
    index = tmp_path / "index.json"
    reproduce: list[str] = []
    for scope_id in sorted(_declared_scope_ids()):
        reproduce += ["--reproduce-scope-id", scope_id]
    emitter.main(
        [
            *reproduce,
            "--subject-release",
            str(SUBJECT_RELEASE),
            "--subject-release-sha256",
            _sha256(SUBJECT_RELEASE),
            "--policy-authority",
            str(POLICY_AUTHORITY),
            "--policy-authority-sha256",
            _sha256(POLICY_AUTHORITY),
            "--artifacts-dir",
            str(tmp_path / "out"),
            "--registry-index",
            str(index),
        ]
    )

    for path in [*(tmp_path / "out").iterdir(), index]:
        text = path.read_text(encoding="utf-8")
        assert "/home/" not in text
        assert str(tmp_path) not in text
        assert "generated_at" not in text


# --- Cinq mutants d'élargissement de droits, tous refusés --------------------


def _widening_mutant(monkeypatch: pytest.MonkeyPatch, **widened: Any) -> None:
    """Faire produire à l'émetteur un artefact plus large que sa politique."""
    original = emitter._build_scope_artifact

    def mutated(binding: Any, policy: Any, subject: Any) -> Any:
        artifact = original(binding, policy, subject)
        payload = artifact.model_dump(mode="json")
        payload["evidence_subject"].update(widened)
        return RetrievalScopeArtifactV2.model_validate(payload)

    monkeypatch.setattr(emitter, "_build_scope_artifact", mutated)


def test_mutant_a_visibility_widened_to_public_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _widening_mutant(monkeypatch, visibility="public")

    with pytest.raises(emitter.ScopeEmissionError, match="élargissement d'autorisation"):
        _emit(tmp_path)


def test_mutant_b_an_added_audience_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _widening_mutant(monkeypatch, audiences=["libre", "aefe", "tous"])

    with pytest.raises(emitter.ScopeEmissionError, match="élargissement d'autorisation"):
        _emit(tmp_path)


def test_mutant_c_a_changed_collection_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _widening_mutant(monkeypatch, collection="rag_nexus_philo_terminale_tc")

    with pytest.raises(emitter.ScopeEmissionError, match="élargissement d'autorisation"):
        _emit(tmp_path)


def test_mutant_d_a_changed_candidat_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _widening_mutant(monkeypatch, candidat="aefe")

    with pytest.raises(emitter.ScopeEmissionError, match="élargissement d'autorisation"):
        _emit(tmp_path)


def test_mutant_e_two_scopes_for_the_same_collection_and_digest_are_refused(
    tmp_path: Path,
) -> None:
    release = _mutated_release(
        tmp_path,
        # La même entrée, par référence : elle porte donc le même couple
        # (collection, sha256) une fois les digests recalculés.
        lambda aggregate, subjects: aggregate["subjects"].append(
            aggregate["subjects"][0]
        ),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="deux scopes"):
        _emit(tmp_path / "out", subject_release=release)


def test_mutant_d_bis_a_changed_candidat_in_the_release_is_refused(
    tmp_path: Path,
) -> None:
    """La release ne peut pas non plus imposer un candidat que la politique ignore."""
    release = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: _set_placement_dimension(subjects[0], "candidat", "aefe"),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="candidat"):
        _emit(tmp_path / "out", subject_release=release)


def test_mutant_a_bis_a_visibility_widened_in_the_release_is_refused(
    tmp_path: Path,
) -> None:
    release = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: _set_placement_dimension(subjects[0], "visibility", "public"),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="visibility"):
        _emit(tmp_path / "out", subject_release=release)


def test_widened_rights_are_reported_by_the_semantic_diff() -> None:
    policy = emitter.load_policy_source("entree_premiere_maths_v1")
    widened = policy.model_copy(
        update={
            "evidence_subject": policy.evidence_subject.model_copy(
                update={"visibility": "public"}
            )
        }
    )

    assert emitter.authorization_semantic_diff(widened, policy) == {
        "evidence_subject.visibility": ("public", "internal")
    }


# --- Refus : la release ne peut pas devenir une politique --------------------


def test_refuses_a_subject_whose_collection_differs_from_the_policy(tmp_path: Path) -> None:
    release = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: _set_placement_dimension(
            subjects[0], "collection", "rag_nexus_francais_seconde_tc"
        ),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="collection"):
        _emit(tmp_path / "out", subject_release=release)


def test_refuses_a_subject_whose_niveau_differs_from_the_policy(tmp_path: Path) -> None:
    release = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: _set_placement_dimension(subjects[0], "niveau", "premiere"),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="niveau"):
        _emit(tmp_path / "out", subject_release=release)


def test_refuses_a_subject_whose_matiere_differs_from_the_policy(tmp_path: Path) -> None:
    release = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: _set_placement_dimension(subjects[0], "matiere", "francais"),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="matiere"):
        _emit(tmp_path / "out", subject_release=release)


def test_refuses_an_incompatible_programme_version(tmp_path: Path) -> None:
    release = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: _set_placement_dimension(
            subjects[0], "programme_version", "BOEN_INVENTE_2099"
        ),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="programme_version"):
        _emit(tmp_path / "out", subject_release=release)


def test_refuses_a_subject_already_bound_by_two_existing_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EXACT_EXISTING_MATCH > 1 est une ambiguïté d'autorité, donc un refus."""
    monkeypatch.setattr(
        emitter,
        "exact_existing_matches",
        lambda *args, **kwargs: ("terminale_nsi_v1", "terminale_nsi_v2"),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="correspondances exactes multiples"):
        _emit(tmp_path)


def test_refuses_a_subject_without_policy_authority(tmp_path: Path) -> None:
    def drop_first_binding(payload: dict[str, Any]) -> None:
        payload["bindings"] = payload["bindings"][1:]

    policy = _mutated_authority(tmp_path, drop_first_binding)

    with pytest.raises(emitter.ScopeEmissionError, match="autorité de politique absente"):
        _emit(tmp_path / "out", policy_authority=policy)


def test_refuses_a_scope_id_collision_with_different_bytes(tmp_path: Path) -> None:
    """Rebrancher un scope_id déjà épinglé sur une autre release est un refus."""
    drifted = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: subjects[0]["payload"]["expected_counts"].__setitem__(
            "chunks", subjects[0]["payload"]["expected_counts"]["chunks"] + 1
        ),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="collision de scope_id"):
        _emit(tmp_path / "out", subject_release=drifted, reproduce=False)


def test_refuses_two_bindings_that_share_one_scope_id(tmp_path: Path) -> None:
    def collide(payload: dict[str, Any]) -> None:
        payload["bindings"][1]["scope_id"] = payload["bindings"][0]["scope_id"]

    policy = _mutated_authority(tmp_path, collide)

    with pytest.raises(emitter.ScopeEmissionError, match="collision de scope_id"):
        _emit(tmp_path / "out", policy_authority=policy)


def test_refuses_two_scopes_for_the_same_collection_and_subject_digest(tmp_path: Path) -> None:
    def duplicate(payload: dict[str, Any]) -> None:
        clone = copy.deepcopy(payload["bindings"][0])
        clone["scope_id"] = clone["scope_id"].replace("_v2", "_v3")
        payload["bindings"].append(clone)

    policy = _mutated_authority(tmp_path, duplicate)

    with pytest.raises(emitter.ScopeEmissionError, match="deux scopes"):
        _emit(tmp_path / "out", policy_authority=policy)


def test_refuses_a_scope_id_already_held_by_the_historical_registry(tmp_path: Path) -> None:
    drifted = _mutated_release(
        tmp_path,
        lambda aggregate, subjects: subjects[0]["payload"]["expected_counts"].__setitem__(
            "chunks", subjects[0]["payload"]["expected_counts"]["chunks"] + 1
        ),
    )

    with pytest.raises(emitter.ScopeEmissionError, match="registre historique"):
        _emit(tmp_path / "out", subject_release=drifted, reproduce=False)


def test_refuses_a_scope_id_that_is_not_the_governed_successor(tmp_path: Path) -> None:
    def bricolage(payload: dict[str, Any]) -> None:
        payload["bindings"][0]["scope_id"] = "entree_premiere_maths_v1_bis"

    policy = _mutated_authority(tmp_path, bricolage)

    with pytest.raises(emitter.ScopeEmissionError, match="convention"):
        _emit(tmp_path / "out", policy_authority=policy)


def test_refuses_a_release_whose_digest_was_not_named(tmp_path: Path) -> None:
    with pytest.raises(emitter.ScopeEmissionError, match="digest"):
        emitter.emit_retrieval_scope_artifacts(
            subject_release=SUBJECT_RELEASE,
            subject_release_sha256="0" * 64,
            policy_authority=POLICY_AUTHORITY,
            policy_authority_sha256=_sha256(POLICY_AUTHORITY),
            artifacts_dir=tmp_path,
        )


def test_refuses_a_policy_authority_whose_digest_was_not_named(tmp_path: Path) -> None:
    with pytest.raises(emitter.ScopeEmissionError, match="digest"):
        emitter.emit_retrieval_scope_artifacts(
            subject_release=SUBJECT_RELEASE,
            subject_release_sha256=_sha256(SUBJECT_RELEASE),
            policy_authority=POLICY_AUTHORITY,
            policy_authority_sha256="0" * 64,
            artifacts_dir=tmp_path,
        )
