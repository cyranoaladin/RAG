import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_pedago.governance import pilot_validation as governance

SERVICE_ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = SERVICE_ROOT / "configs" / "pilot_validation_scope.yml"
BASE_POLICY_PATH = SERVICE_ROOT / "configs" / "pilot_validation_policy.yml"
FIXTURES = SERVICE_ROOT / "tests" / "fixtures" / "pilot_validation"
ACTIVATION_PATH = FIXTURES / "activation.valid.yml"
AUTHORIZATION_PATH = FIXTURES / "authorization.valid.yml"
APPROVAL_PATH = FIXTURES / "github_approval.valid.yml"
PACKAGE_PATH = FIXTURES / "publication_package.valid.yml"
NOW = datetime(2026, 7, 31, 22, 0, tzinfo=UTC)


def _request(**updates: object) -> governance.ValidationRequest:
    values: dict[str, object] = {
        "operation": "publish_reviewed_chunks",
        "caller": "rag-engine",
        "environment_id": "nexus-validation-1",
        "collection": "rag_nexus_maths_terminale_gen_specialite",
        "tenant": "libre_terminale",
        "level": "terminale",
        "track": "generale",
        "teaching_status": "specialite",
        "audience": "libre",
        "candidate": "libre",
        "subject": "maths",
        "school_year": "2026-2027",
    }
    values.update(updates)
    return governance.ValidationRequest(
        **values,
    )


def _payload(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _write_payload(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _variant(tmp_path: Path, source: Path, name: str, **updates: object) -> Path:
    payload = _payload(source)
    payload.update(updates)
    return _write_payload(tmp_path, name, payload)


def _activation_variant(
    tmp_path: Path,
    *,
    capability: str,
) -> tuple[Path, Path]:
    activation = _payload(ACTIVATION_PATH)
    capabilities = activation["capabilities"]
    assert isinstance(capabilities, dict)
    capabilities[capability] = False
    activation_path = _write_payload(tmp_path, "activation.partial.yml", activation)
    authorization = _payload(AUTHORIZATION_PATH)
    authorization["activation_policy_digest"] = sha256(
        activation_path.read_bytes()
    ).hexdigest()
    authorization_path = _write_payload(
        tmp_path,
        "authorization.activation.yml",
        authorization,
    )
    return activation_path, authorization_path


def _evaluate(
    *,
    scope: governance.PilotValidationScope | Path | None = None,
    base_policy: governance.PilotValidationPolicy | Path | None = None,
    activation_policy: governance.PilotValidationPolicy | Path | None = None,
    authorization: governance.ValidationAuthorization | Path | None = AUTHORIZATION_PATH,
    approval: governance.GitHubApprovalEvidence | Path | None = APPROVAL_PATH,
    package: governance.PublicationPackage | Path | None = PACKAGE_PATH,
    request: governance.ValidationRequest | None = None,
    now: datetime = NOW,
    service_root: Path = SERVICE_ROOT,
) -> governance.AuthorizationDecision:
    return governance.evaluate_authorization(
        scope=scope or governance.load_scope(SCOPE_PATH),
        base_policy=base_policy or governance.load_policy(BASE_POLICY_PATH),
        activation_policy=activation_policy or governance.load_policy(ACTIVATION_PATH),
        authorization=authorization,
        approval_evidence=approval,
        publication_package=package,
        request=request or _request(),
        now=now,
        service_root=service_root,
    )


def test_future_activation_loaded_from_yaml_is_authorized() -> None:
    decision = _evaluate()

    assert decision.allowed is True
    assert decision.reasons == ()


def test_canonical_lot38_policy_remains_closed() -> None:
    decision = _evaluate(
        activation_policy=governance.load_policy(BASE_POLICY_PATH),
    )

    assert decision.allowed is False
    assert any(reason.startswith("capability.closed:") for reason in decision.reasons)


def test_authorization_yaml_never_grants_authority_without_external_evidence() -> None:
    decision = _evaluate(approval=None)

    assert decision.allowed is False
    assert "approval.missing" in decision.reasons


class TestAuthorityEvidence:
    def test_refuses_missing_authorization(self) -> None:
        decision = _evaluate(authorization=None)

        assert "authorization.missing" in decision.reasons

    def test_refuses_partial_authorization(self, tmp_path: Path) -> None:
        payload = _payload(AUTHORIZATION_PATH)
        del payload["decision"]
        path = _write_payload(tmp_path, "authorization.partial.yml", payload)

        assert "authorization.invalid" in _evaluate(authorization=path).reasons

    def test_refuses_expired_authorization(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.expired.yml",
            expires_at="2026-07-31T21:59:59Z",
        )

        assert "authorization.expired" in _evaluate(authorization=path).reasons

    def test_refuses_missing_github_evidence(self) -> None:
        assert "approval.missing" in _evaluate(approval=None).reasons

    @pytest.mark.parametrize(
        ("field", "value", "reason"),
        [
            ("repository", "intruder/RAG", "approval.repository_mismatch"),
            ("pull_request", 142, "approval.pull_request_mismatch"),
            ("base_branch", "release", "approval.base_branch_mismatch"),
        ],
    )
    def test_refuses_wrong_github_target(
        self,
        tmp_path: Path,
        field: str,
        value: object,
        reason: str,
    ) -> None:
        path = _variant(tmp_path, APPROVAL_PATH, "approval.target.yml", **{field: value})

        assert reason in _evaluate(approval=path).reasons

    @pytest.mark.parametrize(
        ("updates", "reason"),
        [
            ({"reviewer_role": "maintainer"}, "approval.reviewer_not_human_lead"),
            ({"reviewer_human": False}, "approval.reviewer_not_human_lead"),
            ({"approved_head_sha": "4" * 40}, "approval.approved_head_mismatch"),
            ({"revoked": True}, "approval.revoked"),
        ],
    )
    def test_refuses_untrusted_or_revoked_review(
        self,
        tmp_path: Path,
        updates: dict[str, object],
        reason: str,
    ) -> None:
        path = _variant(tmp_path, APPROVAL_PATH, "approval.review.yml", **updates)

        assert reason in _evaluate(approval=path).reasons

    @pytest.mark.parametrize(
        ("field", "value", "reason"),
        [
            ("decision", "AUTHORIZE_PUBLIC", "authorization.decision_invalid"),
            ("status", "pending", "authorization.status_invalid"),
            ("lot41_sha", "0" * 40, "authorization.lot41_sha_invalid"),
        ],
    )
    def test_refuses_unknown_decision_status_or_lot41_sha(
        self,
        tmp_path: Path,
        field: str,
        value: str,
        reason: str,
    ) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.authority.yml",
            **{field: value},
        )

        assert reason in _evaluate(authorization=path).reasons

    def test_refuses_incoherent_expiration(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.timeline.yml",
            expires_at="2026-07-31T20:00:00Z",
        )

        assert "authorization.expiration_incoherent" in _evaluate(
            authorization=path
        ).reasons

    def test_lot41_reference_is_distinct_from_lot41a_approved_head(self) -> None:
        authorization = governance.load_authorization(AUTHORIZATION_PATH)
        approval = governance.load_approval_evidence(APPROVAL_PATH)
        decision = _evaluate()

        assert decision.allowed is True
        assert approval.referenced_lot41_sha == authorization.lot41_sha
        assert approval.head_sha == approval.approved_head_sha
        assert approval.head_sha != authorization.lot41_sha

    def test_refuses_evidence_whose_lot41_reference_differs(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            APPROVAL_PATH,
            "approval.lot41.yml",
            referenced_lot41_sha="4" * 40,
        )

        assert "approval.referenced_lot41_mismatch" in _evaluate(approval=path).reasons

    def test_refuses_lot41a_head_equal_to_referenced_lot41(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            APPROVAL_PATH,
            "approval.same-head.yml",
            head_sha="1" * 40,
            approved_head_sha="1" * 40,
        )

        assert "approval.head_not_distinct_from_lot41" in _evaluate(
            approval=path
        ).reasons

    def test_refuses_authorization_not_covered_by_approved_head(self, tmp_path: Path) -> None:
        authorization_path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.unapproved.yml",
            authorization_id="lot41a-substituted-v1",
        )

        assert "approval.authorization_digest_mismatch" in _evaluate(
            authorization=authorization_path
        ).reasons

    def test_refuses_evidence_without_distinct_post_merge_sha(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            APPROVAL_PATH,
            "approval.merge.yml",
            merge_sha="3" * 40,
        )

        assert "approval.merge_sha_not_distinct" in _evaluate(approval=path).reasons

    def test_refuses_evidence_read_back_before_merge(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            APPROVAL_PATH,
            "approval.timeline.yml",
            readback_at="2026-07-31T21:15:00Z",
        )

        assert "approval.timeline_incoherent" in _evaluate(approval=path).reasons

    def test_refuses_evidence_read_back_at_merge_instead_of_after(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            APPROVAL_PATH,
            "approval.same-time.yml",
            readback_at="2026-07-31T21:30:00Z",
        )

        assert "approval.timeline_incoherent" in _evaluate(approval=path).reasons


class TestScopeAndIdentityRefutations:
    def test_refuses_wrong_scope_digest(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.scope-digest.yml",
            scope_digest="0" * 64,
        )

        assert "scope.digest_mismatch" in _evaluate(authorization=path).reasons

    @pytest.mark.parametrize(
        ("field", "reason"),
        [
            ("base_policy_digest", "base_policy.digest_mismatch"),
            ("activation_policy_digest", "activation_policy.digest_mismatch"),
        ],
    )
    def test_refuses_wrong_policy_digest(
        self,
        tmp_path: Path,
        field: str,
        reason: str,
    ) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.policy-digest.yml",
            **{field: "0" * 64},
        )

        assert reason in _evaluate(authorization=path).reasons

    def test_refuses_identical_base_and_activation_digests(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.same-digests.yml",
            activation_policy_digest=_payload(AUTHORIZATION_PATH)[
                "base_policy_digest"
            ],
        )

        assert "policy.digests_not_distinct" in _evaluate(authorization=path).reasons

    def test_refuses_a_taxonomy_modified_on_disk(self, tmp_path: Path) -> None:
        temporary_service_root = tmp_path / "rag-pedago"
        shutil.copytree(SERVICE_ROOT / "taxonomy", temporary_service_root / "taxonomy")
        taxonomy = (
            temporary_service_root
            / "taxonomy"
            / "maths"
            / "terminale_gen_specialite.yml"
        )
        taxonomy.write_bytes(taxonomy.read_bytes() + b"\n# derive\n")

        decision = _evaluate(service_root=temporary_service_root)

        assert (
            "scope.invalid:scope.taxonomy_sha256_mismatch:maths" in decision.reasons
        )

    def test_refuses_an_additional_authorized_collection(self, tmp_path: Path) -> None:
        payload = _payload(AUTHORIZATION_PATH)
        collections = payload["collections"]
        assert isinstance(collections, list)
        collections.append("rag_nexus_collection_intruse")
        path = _write_payload(tmp_path, "authorization.collections.yml", payload)

        assert "collections.authorization_mismatch" in _evaluate(
            authorization=path
        ).reasons

    def test_refuses_wrong_tenant(self) -> None:
        assert "identity.request_mismatch:tenant" in _evaluate(
            request=_request(tenant="aefe_terminale")
        ).reasons

    def test_refuses_wrong_candidate_profile(self) -> None:
        assert "identity.request_mismatch:candidate" in _evaluate(
            request=_request(candidate="scolaire")
        ).reasons

    @pytest.mark.parametrize(
        ("field", "value", "reason"),
        [
            ("subject", "physique", "identity.request_mismatch:subject"),
            ("school_year", "2025-2026", "identity.request_mismatch:school_year"),
            ("level", "premiere", "identity.request_mismatch:level"),
            ("track", "technologique", "identity.request_mismatch:track"),
            ("audience", "aefe", "identity.request_mismatch:audience"),
            (
                "teaching_status",
                "option",
                "identity.request_mismatch:teaching_status",
            ),
        ],
    )
    def test_refuses_request_dimension_outside_scope(
        self,
        field: str,
        value: str,
        reason: str,
    ) -> None:
        assert reason in _evaluate(request=_request(**{field: value})).reasons

    @pytest.mark.parametrize(
        ("target", "reason"),
        [
            ("authorization", "environment.authorization_mismatch"),
            ("request", "environment.request_mismatch"),
        ],
    )
    def test_refuses_wrong_environment(
        self,
        tmp_path: Path,
        target: str,
        reason: str,
    ) -> None:
        if target == "authorization":
            path = _variant(
                tmp_path,
                AUTHORIZATION_PATH,
                "authorization.environment.yml",
                environment_id="nexus-production-1",
            )
            decision = _evaluate(authorization=path)
        else:
            decision = _evaluate(request=_request(environment_id="nexus-production-1"))

        assert reason in decision.reasons

    @pytest.mark.parametrize(
        ("capability", "operation", "caller"),
        [
            (
                "validation_real_documents_allowed",
                "read_real_documents",
                "lot42_publisher",
            ),
            (
                "validation_pipeline_allowed",
                "publish_reviewed_chunks",
                "rag-engine",
            ),
            (
                "validation_answer_generation_allowed",
                "generate_grounded_answer",
                "rag-engine",
            ),
            (
                "validation_openrouter_allowed",
                "generate_grounded_answer",
                "rag-engine",
            ),
        ],
    )
    def test_refuses_each_partially_opened_capability_set(
        self,
        tmp_path: Path,
        capability: str,
        operation: str,
        caller: str,
    ) -> None:
        activation_path, authorization_path = _activation_variant(
            tmp_path,
            capability=capability,
        )

        decision = _evaluate(
            activation_policy=governance.load_policy(activation_path),
            authorization=authorization_path,
            request=_request(operation=operation, caller=caller),
        )

        assert f"capability.closed:{capability}" in decision.reasons

    def test_refuses_unknown_operation(self) -> None:
        assert "operation.unknown" in _evaluate(
            request=_request(operation="delete_collection")
        ).reasons

    @pytest.mark.parametrize("caller", ["cockpit", "public_bff"])
    def test_refuses_public_callers(self, caller: str) -> None:
        assert f"caller.public_forbidden:{caller}" in _evaluate(
            request=_request(caller=caller)
        ).reasons

    def test_refuses_unknown_caller(self) -> None:
        assert "caller.not_allowed" in _evaluate(
            request=_request(caller="worker-inconnu")
        ).reasons


class TestPublicationChain:
    @pytest.mark.parametrize(
        "field",
        ["provenance_verified", "rights_verified"],
    )
    def test_refuses_unknown_provenance_or_rights(
        self,
        tmp_path: Path,
        field: str,
    ) -> None:
        payload = _payload(AUTHORIZATION_PATH)
        del payload[field]
        path = _write_payload(tmp_path, "authorization.unknown.yml", payload)

        assert "authorization.invalid" in _evaluate(authorization=path).reasons

    @pytest.mark.parametrize(
        ("field", "reason"),
        [
            ("provenance_verified", "provenance.not_verified"),
            ("rights_verified", "rights.not_verified"),
            ("pii_absence_verified", "pii.not_verified"),
        ],
    )
    def test_refuses_unverified_provenance_rights_or_pii(
        self,
        tmp_path: Path,
        field: str,
        reason: str,
    ) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.verification.yml",
            **{field: False},
        )

        assert reason in _evaluate(authorization=path).reasons

    def test_refuses_missing_rollback(self, tmp_path: Path) -> None:
        payload = _payload(AUTHORIZATION_PATH)
        del payload["rollback"]
        path = _write_payload(tmp_path, "authorization.no-rollback.yml", payload)

        assert "authorization.invalid" in _evaluate(authorization=path).reasons

    def test_refuses_untested_rollback(self, tmp_path: Path) -> None:
        payload = _payload(AUTHORIZATION_PATH)
        rollback = payload["rollback"]
        assert isinstance(rollback, dict)
        rollback["tested"] = False
        path = _write_payload(tmp_path, "authorization.rollback.yml", payload)

        assert "rollback.not_tested" in _evaluate(authorization=path).reasons

    def test_refuses_missing_publication_package(self) -> None:
        assert "package.missing" in _evaluate(package=None).reasons

    def test_refuses_divergent_package_digest(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            PACKAGE_PATH,
            "package.digest.yml",
            content_sha256="0" * 64,
        )

        assert "package.digest_mismatch" in _evaluate(package=path).reasons

    @pytest.mark.parametrize(
        ("field", "value", "reason"),
        [
            ("quality", "failed", "package.quality_not_passed"),
            ("gate", "failed", "package.gate_not_passed"),
            ("review", "needs_review", "package.review_not_reviewed"),
            ("quarantine", True, "package.quarantined"),
            ("revoked", True, "package.revoked"),
            ("publisher", "rag-pedago", "package.publisher_mismatch"),
        ],
    )
    def test_refuses_incomplete_or_revoked_publication_chain(
        self,
        tmp_path: Path,
        field: str,
        value: object,
        reason: str,
    ) -> None:
        path = _variant(
            tmp_path,
            PACKAGE_PATH,
            "package.chain.yml",
            **{field: value},
        )

        assert reason in _evaluate(package=path).reasons

    def test_non_publication_operation_does_not_require_package(self) -> None:
        decision = _evaluate(
            package=None,
            request=_request(
                operation="read_real_documents",
                caller="lot42_publisher",
            ),
        )

        assert decision.allowed is True
        assert decision.reasons == ()


class TestMalformedInputs:
    def test_evaluator_loads_valid_scope_and_policies_from_real_yaml_paths(self) -> None:
        decision = governance.evaluate_authorization(
            scope=SCOPE_PATH,
            base_policy=BASE_POLICY_PATH,
            activation_policy=ACTIVATION_PATH,
            authorization=AUTHORIZATION_PATH,
            approval_evidence=APPROVAL_PATH,
            publication_package=PACKAGE_PATH,
            request=_request(),
            now=NOW,
            service_root=SERVICE_ROOT,
        )

        assert decision.allowed is True
        assert decision.reasons == ()

    @pytest.mark.parametrize(
        ("argument", "reason"),
        [
            ("scope", "scope.invalid"),
            ("base_policy", "base_policy.invalid"),
            ("activation_policy", "activation_policy.invalid"),
        ],
    )
    def test_refuses_malformed_scope_or_policy_without_exception(
        self,
        tmp_path: Path,
        argument: str,
        reason: str,
    ) -> None:
        path = tmp_path / "malformed.yml"
        path.write_text("document: [", encoding="utf-8")

        decision = _evaluate(**{argument: path})

        assert decision.allowed is False
        assert reason in decision.reasons

    @pytest.mark.parametrize(
        ("content", "reason"),
        [
            ("authorization: [", "authorization.invalid"),
            ("- not\n- a\n- mapping\n", "authorization.invalid"),
        ],
    )
    def test_refuses_invalid_yaml_or_non_mapping(
        self,
        tmp_path: Path,
        content: str,
        reason: str,
    ) -> None:
        path = tmp_path / "authorization.malformed.yml"
        path.write_text(content, encoding="utf-8")

        decision = _evaluate(authorization=path)

        assert decision.allowed is False
        assert reason in decision.reasons

    def test_refuses_unknown_authorization_key(self, tmp_path: Path) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.extra.yml",
            merge_sha="3" * 40,
        )

        assert "authorization.invalid" in _evaluate(authorization=path).reasons

    def test_refuses_mutated_loaded_authorization_with_stale_raw_digest(self) -> None:
        authorization = governance.load_authorization(AUTHORIZATION_PATH).model_copy(
            update={"authorization_id": "lot41a-substituted-in-memory-v1"}
        )

        assert "approval.authorization_digest_mismatch" in _evaluate(
            authorization=authorization
        ).reasons

    def test_refuses_mutated_loaded_activation_with_stale_raw_digest(self) -> None:
        activation = governance.load_policy(ACTIVATION_PATH)
        capabilities = activation.capabilities.model_copy(
            update={"validation_answer_generation_allowed": False}
        )
        mutated_activation = activation.model_copy(update={"capabilities": capabilities})

        assert "activation_policy.digest_mismatch" in _evaluate(
            activation_policy=mutated_activation
        ).reasons

    @pytest.mark.parametrize("invalid", ["141", True, 0, -1])
    @pytest.mark.parametrize(
        ("source", "argument", "reason"),
        [
            (AUTHORIZATION_PATH, "authorization", "authorization.invalid"),
            (APPROVAL_PATH, "approval", "approval.invalid"),
        ],
    )
    def test_refuses_non_strict_or_non_positive_pull_request(
        self,
        tmp_path: Path,
        source: Path,
        argument: str,
        reason: str,
        invalid: object,
    ) -> None:
        path = _variant(
            tmp_path,
            source,
            f"{source.stem}.pull-request.yml",
            pull_request=invalid,
        )

        decision = _evaluate(**{argument: path})

        assert reason in decision.reasons

    @pytest.mark.parametrize("reviewer_login", ["", "   "])
    def test_refuses_empty_reviewer_login(
        self,
        tmp_path: Path,
        reviewer_login: str,
    ) -> None:
        path = _variant(
            tmp_path,
            APPROVAL_PATH,
            "approval.empty-reviewer.yml",
            reviewer_login=reviewer_login,
        )

        assert "approval.invalid" in _evaluate(approval=path).reasons

    @pytest.mark.parametrize("field", ["issued_at", "expires_at"])
    def test_refuses_naive_authorization_date(
        self,
        tmp_path: Path,
        field: str,
    ) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.naive.yml",
            **{field: "2026-07-31T22:00:00"},
        )

        assert "authorization.invalid" in _evaluate(authorization=path).reasons

    def test_refuses_naive_evaluation_time_without_exception(self) -> None:
        decision = _evaluate(now=datetime(2026, 7, 31, 22, 0))

        assert decision.allowed is False
        assert "authorization.now_naive" in decision.reasons

    @pytest.mark.parametrize(
        "field",
        ["scope_digest", "base_policy_digest", "activation_policy_digest"],
    )
    def test_refuses_non_sha256_authorization_digest(
        self,
        tmp_path: Path,
        field: str,
    ) -> None:
        path = _variant(
            tmp_path,
            AUTHORIZATION_PATH,
            "authorization.digest.yml",
            **{field: "not-a-sha256"},
        )

        assert "authorization.invalid" in _evaluate(authorization=path).reasons

    @pytest.mark.parametrize(
        "plan_ref",
        ["/etc/passwd", "docs/../../etc/passwd", "C:\\secrets\\rollback.md"],
    )
    def test_refuses_absolute_or_traversing_rollback_path(
        self,
        tmp_path: Path,
        plan_ref: str,
    ) -> None:
        payload = _payload(AUTHORIZATION_PATH)
        rollback = payload["rollback"]
        assert isinstance(rollback, dict)
        rollback["plan_ref"] = plan_ref
        path = _write_payload(tmp_path, "authorization.path.yml", payload)

        assert "rollback.path_invalid" in _evaluate(authorization=path).reasons

    @pytest.mark.parametrize(
        "content_ref",
        ["/var/lib/nexus/package.json", "artifacts/../../package.json", "bad\0path"],
    )
    def test_refuses_invalid_package_path(
        self,
        tmp_path: Path,
        content_ref: str,
    ) -> None:
        path = _variant(
            tmp_path,
            PACKAGE_PATH,
            "package.path.yml",
            content_ref=content_ref,
        )

        assert "package.path_invalid" in _evaluate(package=path).reasons

    @pytest.mark.parametrize("invalid", [0, 1, "false", "true"])
    @pytest.mark.parametrize(
        ("source", "section", "field", "reason"),
        [
            (AUTHORIZATION_PATH, None, "rights_verified", "authorization.invalid"),
            (
                AUTHORIZATION_PATH,
                None,
                "provenance_verified",
                "authorization.invalid",
            ),
            (
                AUTHORIZATION_PATH,
                None,
                "pii_absence_verified",
                "authorization.invalid",
            ),
            (AUTHORIZATION_PATH, "rollback", "tested", "authorization.invalid"),
            (APPROVAL_PATH, None, "reviewer_human", "approval.invalid"),
            (APPROVAL_PATH, None, "revoked", "approval.invalid"),
            (PACKAGE_PATH, None, "quarantine", "package.invalid"),
            (PACKAGE_PATH, None, "revoked", "package.invalid"),
        ],
    )
    def test_refuses_coercible_values_for_new_booleans(
        self,
        tmp_path: Path,
        source: Path,
        section: str | None,
        field: str,
        reason: str,
        invalid: object,
    ) -> None:
        payload = _payload(source)
        target = payload
        if section is not None:
            nested = payload[section]
            assert isinstance(nested, dict)
            target = nested
        target[field] = invalid
        path = _write_payload(tmp_path, f"{source.stem}.bool.yml", payload)
        kwargs: dict[str, object] = {}
        if source == AUTHORIZATION_PATH:
            kwargs["authorization"] = path
        elif source == APPROVAL_PATH:
            kwargs["approval"] = path
        else:
            kwargs["package"] = path

        decision = _evaluate(**kwargs)

        assert decision.allowed is False
        assert reason in decision.reasons

    @pytest.mark.parametrize(
        ("argument", "reason"),
        [
            ("authorization", "authorization.invalid"),
            ("approval", "approval.invalid"),
            ("package", "package.invalid"),
        ],
    )
    def test_refuses_unreadable_documents_without_exception(
        self,
        tmp_path: Path,
        argument: str,
        reason: str,
    ) -> None:
        missing = tmp_path / "missing.yml"

        decision = _evaluate(**{argument: missing})

        assert decision.allowed is False
        assert reason in decision.reasons

    def test_reasons_follow_the_documented_family_order(self, tmp_path: Path) -> None:
        temporary_service_root = tmp_path / "rag-pedago"
        shutil.copytree(SERVICE_ROOT / "taxonomy", temporary_service_root / "taxonomy")
        taxonomy = (
            temporary_service_root
            / "taxonomy"
            / "maths"
            / "terminale_gen_specialite.yml"
        )
        taxonomy.write_bytes(taxonomy.read_bytes() + b"\n# derive ordonnee\n")

        activation = _payload(ACTIVATION_PATH)
        capabilities = activation["capabilities"]
        assert isinstance(capabilities, dict)
        capabilities["validation_pipeline_allowed"] = False
        activation_path = _write_payload(tmp_path, "activation.ordered.yml", activation)

        authorization = _payload(AUTHORIZATION_PATH)
        authorization["activation_policy_digest"] = sha256(
            activation_path.read_bytes()
        ).hexdigest()
        authorization["expires_at"] = "2026-07-31T21:59:59Z"
        authorization["environment_id"] = "nexus-production-1"
        collections = authorization["collections"]
        assert isinstance(collections, list)
        collections.append("rag_nexus_collection_intruse")
        identity = authorization["identity"]
        assert isinstance(identity, dict)
        identity["tenant"] = "aefe_terminale"
        authorization["rights_verified"] = False
        rollback = authorization["rollback"]
        assert isinstance(rollback, dict)
        rollback["tested"] = False
        authorization_path = _write_payload(
            tmp_path,
            "authorization.ordered.yml",
            authorization,
        )
        approval_path = _variant(
            tmp_path,
            APPROVAL_PATH,
            "approval.ordered.yml",
            repository="intruder/RAG",
            authorization_digest=sha256(authorization_path.read_bytes()).hexdigest(),
        )
        package_path = _variant(
            tmp_path,
            PACKAGE_PATH,
            "package.ordered.yml",
            quality="failed",
        )

        decision = _evaluate(
            activation_policy=governance.load_policy(activation_path),
            authorization=authorization_path,
            approval=approval_path,
            package=package_path,
            request=_request(
                caller="cockpit",
                environment_id="nexus-production-1",
                tenant="aefe_terminale",
            ),
            service_root=temporary_service_root,
        )

        assert decision.reasons == (
            "scope.invalid:scope.taxonomy_sha256_mismatch:maths",
            "capability.closed:validation_pipeline_allowed",
            "authorization.expired",
            "approval.repository_mismatch",
            "environment.authorization_mismatch",
            "environment.request_mismatch",
            "collections.authorization_mismatch",
            "identity.authorization_mismatch:tenant",
            "identity.request_mismatch:tenant",
            "rights.not_verified",
            "rollback.not_tested",
            "caller.public_forbidden:cockpit",
            "package.quality_not_passed",
        )
