"""Contrat `NEXUS-AUTHORIZATION-REVOCATIONS-V1` — parseur strict partagé.

Porté depuis l'ancien parseur privé de
``rag_pedago.imports.h2b_coverage_report`` (ADR-0042) : ce fichier prouve
que le comportement est identique, jamais assoupli par la migration.
"""
from __future__ import annotations

import json

import pytest
from nexus_contracts.authorization_revocations import (
    REVOCATIONS_PROTOCOL_VERSION,
    AuthorizationRevocationsError,
    parse_revoked_authorization_ids,
)


def _bytes(**overrides: object) -> bytes:
    document: dict[str, object] = {
        "protocol_version": REVOCATIONS_PROTOCOL_VERSION,
        "revoked_authorization_ids": [],
    }
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


class TestValidRegistry:
    def test_empty_revocation_list_is_valid(self) -> None:
        assert parse_revoked_authorization_ids(_bytes()) == frozenset()

    def test_populated_list_is_returned_as_frozenset(self) -> None:
        result = parse_revoked_authorization_ids(
            _bytes(revoked_authorization_ids=["h2f-corpus-eduscol-v1", "h2c-philo-tc-v2"])
        )
        assert result == frozenset({"h2f-corpus-eduscol-v1", "h2c-philo-tc-v2"})


class TestAdversarialCanaries:
    def test_invalid_utf8_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="not valid UTF-8"):
            parse_revoked_authorization_ids(b"\xff\xfe not utf8")

    def test_invalid_json_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="not valid JSON"):
            parse_revoked_authorization_ids(b"not json")

    def test_non_object_json_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="must be a JSON object"):
            parse_revoked_authorization_ids(b"[]")

    def test_unknown_key_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="unknown keys"):
            parse_revoked_authorization_ids(_bytes(extra_field="surprise"))

    def test_wrong_protocol_version_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="protocol_version"):
            parse_revoked_authorization_ids(_bytes(protocol_version="OTHER-V1"))

    def test_missing_protocol_version_is_refused(self) -> None:
        raw = json.dumps({"revoked_authorization_ids": []}).encode("utf-8")
        with pytest.raises(AuthorizationRevocationsError, match="protocol_version"):
            parse_revoked_authorization_ids(raw)

    def test_non_list_ids_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="list of non-empty strings"):
            parse_revoked_authorization_ids(_bytes(revoked_authorization_ids="not-a-list"))

    def test_non_string_id_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="list of non-empty strings"):
            parse_revoked_authorization_ids(_bytes(revoked_authorization_ids=[123]))

    def test_empty_string_id_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="list of non-empty strings"):
            parse_revoked_authorization_ids(_bytes(revoked_authorization_ids=[""]))

    def test_whitespace_only_id_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="list of non-empty strings"):
            parse_revoked_authorization_ids(_bytes(revoked_authorization_ids=["   "]))

    def test_duplicate_id_is_refused(self) -> None:
        with pytest.raises(AuthorizationRevocationsError, match="repeats authorization ids"):
            parse_revoked_authorization_ids(
                _bytes(revoked_authorization_ids=["dup-id", "dup-id"])
            )

    def test_error_is_a_value_error_subclass(self) -> None:
        assert issubclass(AuthorizationRevocationsError, ValueError)
