import shutil
from pathlib import Path

import pytest

from rag_pedago.governance.pilot_validation import load_scope, validate_scope_integrity

SERVICE_ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = SERVICE_ROOT / "configs" / "pilot_validation_scope.yml"


def test_canonical_scope_is_exact_and_taxonomies_are_content_addressed() -> None:
    scope = load_scope(SCOPE_PATH)

    assert scope.scope_id == "libre_terminale_maths_nsi_real_v1"
    assert scope.status == "eligible_for_promotion"
    assert scope.identity.tenant == "libre_terminale"
    assert scope.identity.candidates == ("cned_libre", "individuel", "libre")
    assert tuple(sorted(scope.collections)) == (
        "rag_nexus_maths_terminale_gen_specialite",
        "rag_nexus_nsi_terminale_specialite",
    )
    assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == ()
    assert sum(len(subject.notions) for subject in scope.subjects) == 39


def _scope_with_subject_update(index: int, **updates: object):
    scope = load_scope(SCOPE_PATH)
    subjects = list(scope.subjects)
    subjects[index] = subjects[index].model_copy(update=updates)
    return scope.model_copy(update={"subjects": tuple(subjects)})


class TestScopeRefutations:
    def test_refuses_a_modified_taxonomy_digest(self) -> None:
        scope = _scope_with_subject_update(0, taxonomy_sha256="0" * 64)

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.taxonomy_sha256_mismatch:maths",
        )

    def test_refuses_a_taxonomy_replaced_under_the_supplied_root(self, tmp_path: Path) -> None:
        temporary_service_root = tmp_path / "rag-pedago"
        shutil.copytree(SERVICE_ROOT / "taxonomy", temporary_service_root / "taxonomy")
        replaced_taxonomy = (
            temporary_service_root / "taxonomy" / "maths" / "terminale_gen_specialite.yml"
        )
        replaced_taxonomy.write_bytes(replaced_taxonomy.read_bytes() + b"\n# remplacement\n")
        scope = load_scope(SCOPE_PATH)

        assert validate_scope_integrity(scope, service_root=temporary_service_root) == (
            "scope.taxonomy_sha256_mismatch:maths",
        )

    def test_refuses_a_missing_notion(self) -> None:
        scope = load_scope(SCOPE_PATH)
        maths = scope.subjects[0]
        scope = _scope_with_subject_update(0, notions=maths.notions[:-1])

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.notions_mismatch:maths",
        )

    def test_refuses_an_additional_notion(self) -> None:
        scope = load_scope(SCOPE_PATH)
        maths = scope.subjects[0]
        scope = _scope_with_subject_update(0, notions=(*maths.notions, "notion_hors_scope"))

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.notions_mismatch:maths",
        )

    def test_refuses_an_additional_collection(self) -> None:
        scope = load_scope(SCOPE_PATH)
        extra_subject = scope.subjects[0].model_copy(
            update={"subject": "intrus", "collection": "rag_nexus_collection_intruse"}
        )
        scope = scope.model_copy(update={"subjects": (*scope.subjects, extra_subject)})

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.collections_mismatch",
        )

    def test_refuses_a_wrong_tenant(self) -> None:
        scope = load_scope(SCOPE_PATH)
        identity = scope.identity.model_copy(update={"tenant": "aefe_terminale"})
        scope = scope.model_copy(update={"identity": identity})

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.identity_mismatch:tenant",
        )

    def test_refuses_a_wrong_profile(self) -> None:
        scope = load_scope(SCOPE_PATH)
        identity = scope.identity.model_copy(update={"level": "premiere"})
        scope = scope.model_copy(update={"identity": identity})

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.identity_mismatch:level",
        )

    def test_refuses_active_status(self) -> None:
        scope = load_scope(SCOPE_PATH).model_copy(update={"status": "active"})

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.status_not_dormant",
        )

    def test_refuses_an_absolute_taxonomy_path_without_opening_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scope = _scope_with_subject_update(0, taxonomy_path=str(tmp_path / "outside.yml"))

        def fail_if_opened(_path: Path) -> bytes:
            raise AssertionError("un chemin absolu non fiable ne doit jamais être ouvert")

        monkeypatch.setattr(Path, "read_bytes", fail_if_opened)

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.taxonomy_path_not_confined:maths",
        )

    def test_refuses_taxonomy_path_traversal_without_opening_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scope = _scope_with_subject_update(
            0,
            taxonomy_path="taxonomy/maths/../maths/terminale_gen_specialite.yml",
        )

        def fail_if_opened(_path: Path) -> bytes:
            raise AssertionError("un chemin avec traversal ne doit jamais être ouvert")

        monkeypatch.setattr(Path, "read_bytes", fail_if_opened)

        assert validate_scope_integrity(scope, service_root=SERVICE_ROOT) == (
            "scope.taxonomy_path_not_confined:maths",
        )
