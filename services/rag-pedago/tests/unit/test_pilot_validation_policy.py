from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rag_pedago.governance.pilot_validation import (
    load_policy,
    validate_dormant_policy,
    validate_policy_integrity,
)

SERVICE_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = SERVICE_ROOT / "configs" / "pilot_validation_policy.yml"
PUBLIC_CONTRACT_PATH = SERVICE_ROOT / "configs" / "pedago_interface_contract.yml"

VALIDATION_CAPABILITIES = {
    "validation_real_documents_allowed",
    "validation_pipeline_allowed",
    "validation_answer_generation_allowed",
    "validation_openrouter_allowed",
}
PUBLIC_LOCKS = {
    "real_documents_allowed",
    "ui_runtime_allowed",
    "answer_generation_allowed",
    "curated_ingestion_allowed",
}
STRICT_BOOLEAN_PATHS = (
    ("capabilities", "validation_real_documents_allowed"),
    ("capabilities", "validation_pipeline_allowed"),
    ("capabilities", "validation_answer_generation_allowed"),
    ("capabilities", "validation_openrouter_allowed"),
    ("public_locks", "real_documents_allowed"),
    ("public_locks", "ui_runtime_allowed"),
    ("public_locks", "answer_generation_allowed"),
    ("public_locks", "curated_ingestion_allowed"),
    ("validation_environment", "public_routes_allowed"),
    (
        "authorization_matrix",
        "publish_reviewed_chunks",
        "quality_chain_required",
    ),
    ("required_authorization", "scope_digest_required"),
    ("required_authorization", "policy_digest_required"),
    ("required_authorization", "expiry_required"),
    ("required_authorization", "rights_verification_required"),
    ("required_authorization", "pii_absence_required"),
    ("required_authorization", "rollback_proof_required"),
)


def _load_public_contract() -> dict[str, object]:
    payload = yaml.safe_load(PUBLIC_CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _raw_policy() -> dict[str, object]:
    payload = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_policy(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "policy.yml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_canonical_policy_is_strict_dormant_and_scoped() -> None:
    policy = load_policy(POLICY_PATH)

    assert policy.policy_id == "libre_terminale_validation_policy_v1"
    assert policy.status == "eligible_for_promotion"
    assert policy.scope_ref == "libre_terminale_maths_nsi_real_v1"
    assert policy.activation_boundary == "LOT41A"
    assert set(type(policy.capabilities).model_fields) == VALIDATION_CAPABILITIES
    assert not any(policy.capabilities.model_dump().values())
    assert set(type(policy.public_locks).model_fields) == PUBLIC_LOCKS
    assert not any(policy.public_locks.model_dump().values())
    assert validate_policy_integrity(policy, _load_public_contract()) == ()
    assert validate_dormant_policy(policy) == ()


def test_policy_models_forbid_extra_fields_and_are_frozen(tmp_path: Path) -> None:
    raw_policy = _raw_policy()
    raw_policy["unexpected"] = True

    with pytest.raises(ValidationError):
        load_policy(_write_policy(tmp_path, raw_policy))

    policy = load_policy(POLICY_PATH)
    with pytest.raises(ValidationError):
        policy.status = "active"


class TestPolicyRefutations:
    def test_loader_refuses_a_contradictory_duplicate_capability(
        self,
        tmp_path: Path,
    ) -> None:
        canonical = POLICY_PATH.read_text(encoding="utf-8")
        capability = "  validation_pipeline_allowed: false"
        assert canonical.count(capability) == 1
        path = tmp_path / "policy.duplicate.yml"
        path.write_text(
            canonical.replace(
                capability,
                f"  validation_pipeline_allowed: true\n{capability}",
                1,
            ),
            encoding="utf-8",
        )

        with pytest.raises(yaml.YAMLError):
            load_policy(path)

    @pytest.mark.parametrize(
        "invalid_value",
        [0, 1, "false", "true"],
        ids=["integer-zero", "integer-one", "string-false", "string-true"],
    )
    @pytest.mark.parametrize(
        "path",
        STRICT_BOOLEAN_PATHS,
        ids=lambda path: ".".join(path),
    )
    def test_refuses_coercible_values_for_strict_booleans(
        self,
        tmp_path: Path,
        path: tuple[str, ...],
        invalid_value: object,
    ) -> None:
        raw_policy = _raw_policy()
        parent = raw_policy
        for field in path[:-1]:
            nested = parent[field]
            assert isinstance(nested, dict)
            parent = nested
        parent[path[-1]] = invalid_value

        with pytest.raises(ValidationError):
            load_policy(_write_policy(tmp_path, raw_policy))

    def test_refuses_active_status(self) -> None:
        policy = load_policy(POLICY_PATH).model_copy(update={"status": "active"})

        assert "policy.status_not_dormant" in validate_policy_integrity(
            policy, _load_public_contract()
        )

    @pytest.mark.parametrize(
        ("field", "value", "reason"),
        [
            ("scope_ref", "scope_inconnu", "policy.scope_ref_mismatch"),
            ("activation_boundary", "LOT41", "policy.activation_boundary_mismatch"),
        ],
    )
    def test_refuses_wrong_policy_identity(self, field: str, value: str, reason: str) -> None:
        policy = load_policy(POLICY_PATH).model_copy(update={field: value})

        assert reason in validate_policy_integrity(policy, _load_public_contract())

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("environment_id", "nexus-production-1"),
            ("isolation_status", "isolation_proven"),
            ("public_routes_allowed", True),
            ("credentials_ref_env", "credentials-literal"),
            ("dsn_ref_env", "dsn-literal"),
            ("bucket_ref_env", "bucket-literal"),
            ("network_ref_env", "network-literal"),
        ],
    )
    def test_refuses_untrusted_validation_environment(self, field: str, value: object) -> None:
        policy = load_policy(POLICY_PATH)
        environment = policy.validation_environment.model_copy(update={field: value})
        modified = policy.model_copy(update={"validation_environment": environment})

        assert (
            f"policy.validation_environment_mismatch:{field}"
            in validate_policy_integrity(modified, _load_public_contract())
        )

    def test_missing_capability_is_rejected_at_load_time(self, tmp_path: Path) -> None:
        raw_policy = _raw_policy()
        capabilities = raw_policy["capabilities"]
        assert isinstance(capabilities, dict)
        del capabilities["validation_pipeline_allowed"]

        with pytest.raises(ValidationError):
            load_policy(_write_policy(tmp_path, raw_policy))

    def test_future_true_capability_is_loadable_but_not_dormant(self, tmp_path: Path) -> None:
        raw_policy = _raw_policy()
        capabilities = raw_policy["capabilities"]
        assert isinstance(capabilities, dict)
        capabilities["validation_real_documents_allowed"] = True

        policy = load_policy(_write_policy(tmp_path, raw_policy))

        assert validate_policy_integrity(policy, _load_public_contract()) == ()
        assert validate_dormant_policy(policy) == (
            "policy.capability_not_dormant:validation_real_documents_allowed",
        )

    def test_refuses_a_public_lock_opened_in_policy(self) -> None:
        policy = load_policy(POLICY_PATH)
        locks = policy.public_locks.model_copy(update={"real_documents_allowed": True})
        modified = policy.model_copy(update={"public_locks": locks})
        reasons = validate_policy_integrity(modified, _load_public_contract())

        assert "policy.public_lock_not_closed:real_documents_allowed" in reasons
        assert "policy.public_lock_mismatch:real_documents_allowed" in reasons

    def test_refuses_a_public_contract_lock_mismatch(self) -> None:
        public_contract = _load_public_contract()
        public_contract["ui_runtime_allowed"] = True

        assert "policy.public_lock_mismatch:ui_runtime_allowed" in validate_policy_integrity(
            load_policy(POLICY_PATH), public_contract
        )

    @pytest.mark.parametrize(
        "capabilities",
        [
            (),
            ("validation_real_documents_allowed", "validation_openrouter_allowed"),
        ],
    )
    def test_refuses_missing_or_extra_matrix_capability(
        self, capabilities: tuple[str, ...]
    ) -> None:
        policy = load_policy(POLICY_PATH)
        operation = policy.authorization_matrix.read_real_documents.model_copy(
            update={"capabilities": capabilities}
        )
        matrix = policy.authorization_matrix.model_copy(
            update={"read_real_documents": operation}
        )
        modified = policy.model_copy(update={"authorization_matrix": matrix})

        assert (
            "policy.authorization_matrix_mismatch:read_real_documents:capabilities"
            in validate_policy_integrity(modified, _load_public_contract())
        )

    @pytest.mark.parametrize("caller", ["cockpit", "public_bff"])
    def test_refuses_a_public_caller(self, caller: str) -> None:
        policy = load_policy(POLICY_PATH)
        operation = policy.authorization_matrix.generate_grounded_answer.model_copy(
            update={"allowed_callers": (caller,)}
        )
        matrix = policy.authorization_matrix.model_copy(
            update={"generate_grounded_answer": operation}
        )
        modified = policy.model_copy(update={"authorization_matrix": matrix})

        assert (
            f"policy.public_caller_forbidden:generate_grounded_answer:{caller}"
            in validate_policy_integrity(modified, _load_public_contract())
        )

    def test_refuses_an_unknown_caller(self) -> None:
        policy = load_policy(POLICY_PATH)
        operation = policy.authorization_matrix.publish_reviewed_chunks.model_copy(
            update={"allowed_callers": ("worker-inconnu",)}
        )
        matrix = policy.authorization_matrix.model_copy(
            update={"publish_reviewed_chunks": operation}
        )
        modified = policy.model_copy(update={"authorization_matrix": matrix})

        assert (
            "policy.authorization_matrix_mismatch:publish_reviewed_chunks:allowed_callers"
            in validate_policy_integrity(modified, _load_public_contract())
        )

    @pytest.mark.parametrize("quality_chain_required", [None, False])
    def test_publish_requires_the_quality_chain(
        self, quality_chain_required: bool | None
    ) -> None:
        policy = load_policy(POLICY_PATH)
        operation = policy.authorization_matrix.publish_reviewed_chunks.model_copy(
            update={"quality_chain_required": quality_chain_required}
        )
        matrix = policy.authorization_matrix.model_copy(
            update={"publish_reviewed_chunks": operation}
        )
        modified = policy.model_copy(update={"authorization_matrix": matrix})

        assert (
            "policy.authorization_matrix_mismatch:publish_reviewed_chunks:quality_chain_required"
            in validate_policy_integrity(modified, _load_public_contract())
        )

    @pytest.mark.parametrize("mutation", ["missing", "unknown"])
    def test_refuses_missing_or_unknown_operation(self, tmp_path: Path, mutation: str) -> None:
        raw_policy = _raw_policy()
        matrix = raw_policy["authorization_matrix"]
        assert isinstance(matrix, dict)
        if mutation == "missing":
            del matrix["read_real_documents"]
        else:
            matrix["unknown_operation"] = matrix["read_real_documents"]

        with pytest.raises(ValidationError):
            load_policy(_write_policy(tmp_path, raw_policy))

    def test_refuses_missing_quality_chain_requirement(self, tmp_path: Path) -> None:
        raw_policy = _raw_policy()
        matrix = raw_policy["authorization_matrix"]
        assert isinstance(matrix, dict)
        publication = matrix["publish_reviewed_chunks"]
        assert isinstance(publication, dict)
        del publication["quality_chain_required"]

        policy = load_policy(_write_policy(tmp_path, raw_policy))

        assert (
            "policy.authorization_matrix_mismatch:publish_reviewed_chunks:quality_chain_required"
            in validate_policy_integrity(policy, _load_public_contract())
        )
