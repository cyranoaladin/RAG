"""Le lecteur API public n'obtient que les SELECT de contrôle nécessaires."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "infra/scripts/provision_ingestion_control_roles.sh"


def test_public_reader_grants_are_explicit_and_read_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "INGESTION_CONTROL_PUBLIC_READER_ROLE" in source
    block = source.split("-- Public successor API reader", 1)[1].split("\\endif", 1)[0]
    assert 'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA ingestion_control FROM :"public_reader_role"' in block
    for table in (
        "resources", "artifacts", "sealed_release_adoptions",
        "scope_authorizations", "publication_attestations", "revoked_review_evidence",
    ):
        assert f'GRANT SELECT ON ingestion_control.{table} TO :"public_reader_role"' in block
    assert "GRANT INSERT" not in block
    assert "GRANT UPDATE" not in block
    assert "GRANT DELETE" not in block


def test_public_reader_is_optional_for_historical_provisioning() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'PUBLIC_READER_ENABLED=0' in source
    assert 'if [[ -n "${INGESTION_CONTROL_PUBLIC_READER_ROLE:-}" ]]' in source
    assert "\\if :public_reader_enabled" in source
