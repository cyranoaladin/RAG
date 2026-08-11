"""Tests for the real sealed-corpus H2-B coverage report."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from nexus_contracts import ScopeAuthorizationArtifactV1, ScopeAuthorizationArtifactV2
from nexus_contracts.authority_artifacts import canonical_authorization_path, git_blob_sha1
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    TRUSTED_REVIEW_PROTOCOL,
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    public_key_hex,
    sign_review_binding,
)
from pydantic import ValidationError

from rag_pedago.imports.h2b_coverage_report import (
    generate_coverage_report,
    render_markdown,
)

#: Instant fixe DANS la fenêtre de validité des autorisations de test — la
#: fenêtre est désormais réellement vérifiée, donc l'horloge ne peut plus
#: être celle de la machine sans rendre ces tests périssables.
AUTHORITY_NOW = datetime(2026, 6, 1, tzinfo=UTC)

#: ADR-0035 — graine Ed25519 de test. L'ancre qui la déclare porte
#: ``environment="test"``, et le contrat refuse de l'exercer en mode
#: production : cette clé ne peut donc jamais rendre un gate final vert
#: (cf. ``test_a_rehearsal_key_can_never_turn_the_final_gate_green``).
TEST_SIGNING_SEED = "44" * 32
TEST_KEY_ID = "nexus-governance-test-1"
REPOSITORY = "cyranoaladin/RAG"
TRUSTED_REVIEWER = "abenrhouma"
PR_AUTHOR = "cyranoaladin"
PULL_REQUEST = 95
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40


def _write_trust_anchor(
    tmp_path: Path, *, environment: str = "test", seed: str = TEST_SIGNING_SEED
) -> Path:
    path = tmp_path / "trust_anchor.json"
    path.write_text(
        json.dumps(
            {
                "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
                "keys": [
                    {
                        "key_id": TEST_KEY_ID,
                        "algorithm": "ed25519",
                        "public_key": public_key_hex(seed),
                        "environment": environment,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _review_binding_document(
    authority_document: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    raw = ScopeAuthorizationArtifactV2.model_validate(
        authority_document
    ).canonical_bytes()
    authorization_id = str(authority_document["authorization_id"])
    document: dict[str, Any] = {
        "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST,
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "authorization_artifact_path": canonical_authorization_path(authorization_id),
        "authorization_artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(raw),
        "authorization_id": authorization_id,
        "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
        "review_id": 4242,
        "reviewer_login": TRUSTED_REVIEWER,
        "reviewer_permission": "admin",
        "author_login": PR_AUTHOR,
        "submitted_at": "2026-05-01T10:00:00Z",
        "challenge_protocol": TRUSTED_REVIEW_PROTOCOL,
        "challenge_digest": expected_challenge_digest(
            repository=REPOSITORY,
            pull_request=PULL_REQUEST,
            base_ref="main",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            author=PR_AUTHOR,
            reviewer=TRUSTED_REVIEWER,
        ),
        "verified_at": "2026-05-15T09:00:00Z",
        "verifier_version": "nexus-review-binding-producer/1",
        "expires_at": "2026-12-01T09:00:00Z",
    }
    document.update(overrides)
    return document


def _write_review_binding(
    tmp_path: Path,
    authority_document: dict[str, Any],
    *,
    seed: str = TEST_SIGNING_SEED,
    key_id: str = TEST_KEY_ID,
    filename: str = "review_binding.json",
    **overrides: Any,
) -> Path:
    binding = ScopeAuthorizationReviewBindingV1.model_validate(
        _review_binding_document(authority_document, **overrides)
    )
    path = tmp_path / filename
    path.write_bytes(
        sign_review_binding(
            binding, private_key_hex=seed, key_id=key_id
        ).canonical_bytes()
    )
    return path


def _write_authority(path: Path, document: dict[str, object]) -> Path:
    """Écrit l'autorisation sous sa forme CANONIQUE octet à octet.

    ``json.dumps`` produisait des octets qui n'étaient pas leur propre
    re-sérialisation canonique : le digest calculé dessus ne désignait donc
    aucun fichier relisible. La couche structurelle refuse maintenant ce
    cas, et ce helper est la seule façon d'écrire une évidence valide."""
    path.write_bytes(
        ScopeAuthorizationArtifactV2.model_validate(document).canonical_bytes()
    )
    return path

CONTENT_SHA256 = "a" * 64  # SHA256 of the PDF content
# P1: Manifest content and SHA256 must be consistent across all fixtures
_MANIFEST_CONTENT = f"{CONTENT_SHA256}  01_EDUSCOL_OFFICIEL/current.pdf\n"
MANIFEST_SHA256 = hashlib.sha256(_MANIFEST_CONTENT.encode()).hexdigest()


def _write_external_evidence(
    tmp_path: Path,
    *,
    include_authority: bool = True,
    environment: str = "production",
) -> tuple[Path, Path, Path, Path | None, Path]:
    """Write external evidence files for testing.

    Returns (routing_path, rights_path, pii_path, authority_path, manifest_path).
    If include_authority is False, authority_path will be None.
    Uses the module-level MANIFEST_SHA256 constant for consistency.
    """
    # P1: Create manifest file with consistent content
    manifest_path = tmp_path / "00_ADMIN" / "SHA256SUMS.txt"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_MANIFEST_CONTENT, encoding="utf-8")

    routing = {
        "config_id": "coverage-routing-v1",
        "manifest_sha256": MANIFEST_SHA256,
        "rights_evidence_perimeter": [
            "00_ADMIN/",
            "01_EDUSCOL_OFFICIEL/",
        ],
        "zone_rules": [
            {
                "zone_prefix": "00_ADMIN/",
                "disposition": "EXCLUDE",
                "reason": "admin",
            },
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "disposition": "INGEST",
                "currentness": "actuel",
            },
        ],
    }
    rights = {
        "registry_id": "coverage-rights-v1",
        "human_rights_decisions": {
            "eduscol": {
                "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                "decision_maker": "Nexus Réussite",
                "decision_date": "2026-08-08",
                "scope_manifest_sha256": MANIFEST_SHA256,
                "scope_zone": "01_EDUSCOL_OFFICIEL/",
                "approved_for_production_rag": True,
                "generic_rights_blocker": False,
            }
        },
        "source_evidence": {
            "admin": {
                "zone": "00_ADMIN/",
                "rights_status": "REVIEW_REQUIRED",
                "disposition_override": "EXCLUDE",
            },
            "eduscol": {
                "zone": "01_EDUSCOL_OFFICIEL/",
                "rights_status": "CLEARED_BY_HUMAN_DECISION",
                "rights_decision_ref": "eduscol",
            },
        },
        "summary": {"total_zones": 2},
    }
    required_path = "01_EDUSCOL_OFFICIEL/current.pdf"
    pii = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "scanner_version": "coverage-scanner-v1",
        "scanner_sha256": "1" * 64,
        "policy_version": "coverage-policy-v1",
        "policy_sha256": "2" * 64,
        "corpus_manifest_sha256": MANIFEST_SHA256,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": 1,
        "required_pdf_path_set_digest": hashlib.sha256(
            f"{required_path}\n".encode()
        ).hexdigest(),
        "summary": {
            "sha256_mismatches": 0,
            "pii_scan_scope": "ALL_CORPUS_PDFS",
            "pii_scan_required": 1,
            "pii_scan_exempt": 0,
        },
        "results": [
            {
                "content_sha256": CONTENT_SHA256,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            }
        ],
    }
    routing_path = tmp_path / "routing.yml"
    rights_path = tmp_path / "rights.yml"
    pii_path = tmp_path / "pii.json"
    routing_path.write_text(yaml.safe_dump(routing), encoding="utf-8")
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")
    pii_path.write_text(json.dumps(pii), encoding="utf-8")

    # H2-F Défaut 5: LOT41A-V2 authority evidence with content allowlist
    authority_path: Path | None = None
    if include_authority:
        authority = {
            "protocol_version": "LOT41A-V2",
            "authorization_id": "h2b_test_authority_v1",
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "manifest_digest": MANIFEST_SHA256,
            "profile_id": "h2b_test_profile",
            "profile_version": "1.0.0",
            "profile_fingerprint": "f" * 64,
            "allowed_domains": ["eduscol.education.fr"],
            "rights_categories": ["officiel_public"],
            "exclusions": [],
            "pii_absence_attested": True,
            "pii_absence_evidence": "Manual review: no PII found",
            "valid_from": "2026-01-01T00:00:00.000000Z",
            "valid_until": "2026-12-31T23:59:59.999999Z",
            "allowed_content_sha256": [CONTENT_SHA256],
            "scope": {
                "audience": ["libre"],
                "candidat": "libre",
                "collection": "test_collection",
                "matiere": "maths",
                "niveau": "terminale",
                "programme_version": "v1",
                "school_year": "2026-2027",
                "tenant": "libre_terminale",
                "visibility": "public",
                "voie": "generale",
            },
        }
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        _write_review_binding(tmp_path, authority)
        # Ancre déclarée ``production`` : c'est une clé engendrée dans
        # ``tmp_path``, jamais commitée, dont l'unique rôle est d'exercer le
        # chemin de code du mode final. Le dépôt ne contient aucune ancre de
        # production (cf. ``test_the_repository_ships_no_production_trust_anchor``).
        # Le gate traduit son mode (``production``/``rehearsal``) en
        # environnement de clé (``production``/``test``) — l'ancre déclare
        # donc le second, jamais le premier.
        _write_trust_anchor(
            tmp_path,
            environment="test" if environment == "rehearsal" else "production",
        )

    return routing_path, rights_path, pii_path, authority_path, manifest_path


def _generate(
    tmp_path: Path,
    catalog_path: Path,
    golden_path: Path,
    *,
    include_authority: bool = True,
    environment: str = "production",
    **kwargs: object,
):
    """Generate coverage report with external evidence.

    If include_authority=True (default), LOT41A-V2 authority evidence is included.
    """
    routing_path, rights_path, pii_path, authority_path, manifest_path = _write_external_evidence(
        tmp_path, include_authority=include_authority, environment=environment
    )
    return generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        authority_path=authority_path,
        manifest_path=manifest_path,
        expected_manifest_sha256=MANIFEST_SHA256,
        authority_now=AUTHORITY_NOW,
        authority_review_binding_path=(
            tmp_path / "review_binding.json" if authority_path is not None else None
        ),
        authority_trust_anchor_path=(
            tmp_path / "trust_anchor.json" if authority_path is not None else None
        ),
        authority_environment=environment,
        **kwargs,
    )


def _write_real_catalog(tmp_path: Path, *, authority_status: str = "PASS") -> Path:
    catalog = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA256,
        "manifest_entries": 1,
        "physical_object_count": 2,
        "content_artifact_count": 2,
        "eduscol_unique_artifacts": 1,
        "eduscol_placement_count": 2,
        "eduscol_placements_classified": 2,
        "eduscol_placements_unclassified": 0,
        "multi_placement_artifacts": 1,
        "disposition_counts": {
            "INGEST": 1,
            "REVIEW_REQUIRED": 0,
            "QUARANTINE": 0,
            "ARCHIVE_ONLY": 0,
            "EXCLUDE": 1,
            "UNSUPPORTED": 0,
        },
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "verification_errors": [],
        "physical_objects": [
            {
                "content_sha256": CONTENT_SHA256,
                "path": "01_EDUSCOL_OFFICIEL/current.pdf",
                "base_disposition": "INGEST",
                "disposition": "INGEST",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "actuel",
                "gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": authority_status,
                },
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": "https://eduscol.education.gouv.fr/test",
                },
            },
            {
                "content_sha256": MANIFEST_SHA256,
                "path": "00_ADMIN/SHA256SUMS.txt",
                "base_disposition": "EXCLUDE",
                "disposition": "EXCLUDE",
                "zone": "00_ADMIN/",
                "currentness": None,
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "NEXUS_CORPUS_GOVERNANCE",
                    "source_reference": "00_ADMIN/SHA256SUMS.txt",
                },
            },
        ],
    }
    path = tmp_path / "real-catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def _write_golden_spec(
    tmp_path: Path,
    *,
    expected_final: str = "INGEST",
    expected_authority: str = "PASS",
) -> Path:
    spec = {
        "spec_id": "coverage_fixture_v2",
        "catalog_kind_required": "REAL_SEALED_CORPUS",
        "positive_controls": [
            {
                "control_id": "pos_01",
                "sha256_prefix": CONTENT_SHA256[:12],
                "expected_base_disposition": "INGEST",
                "expected_final_disposition": expected_final,
                "expected_currentness": "actuel",
                "expected_gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": expected_authority,
                },
            }
        ],
        "boundary_controls": [],
        "negative_controls": [
            {
                "control_id": "neg_manifest",
                "path": "00_ADMIN/SHA256SUMS.txt",
                "expected_count": 1,
                "expected_disposition": "EXCLUDE",
            }
        ],
        "descriptive_assertions": {
            "authoritative": False,
            "items": [],
        },
        "coverage_summary": {
            "total_controls": 2,
            "positive_controls": 1,
            "boundary_controls": 0,
            "negative_controls": 1,
        },
    }
    path = tmp_path / "golden.yml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def test_real_catalog_proves_coverage_and_all_ingest_safety_invariants(
    tmp_path: Path,
) -> None:
    """Nominal test: with proper LOT41A-V2 authority evidence, coverage is complete."""
    report = _generate(
        tmp_path,
        _write_real_catalog(tmp_path),
        _write_golden_spec(tmp_path),
        include_authority=True,  # Include LOT41A-V2 authority evidence
        expected_total=2,
    )

    assert report.real_corpus_catalog_source is True
    assert report.synthetic_catalog_used_for_final_gate is False
    assert report.corpus_total_actual == 2
    assert report.sum_equals_total is True
    assert report.zero_gap is True
    assert report.zero_overlap is True
    # With proper LOT41A-V2 authority evidence, all invariants should be 0
    assert report.safety_invariants == {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0,
        "INGEST_WITHOUT_PII_CLEARANCE": 0,
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0,
        "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
        "INGEST_WITHOUT_PROVENANCE": 0,
        "INGEST_WITHOUT_CONTENT_SHA": 0,
        "INGEST_WITHOUT_AUTHORITY": 0,
        "INGEST_WITH_SELF_DECLARED_AUTHORITY": 0,
        "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
    }
    # With proper authority evidence, coverage is complete
    assert report.coverage_complete is True
    assert report.blocked_ingest_candidates == 0
    markdown = render_markdown(report)
    assert "REAL_CORPUS_CATALOG_SOURCE=true" in markdown
    assert "SYNTHETIC_CATALOG_USED_FOR_FINAL_GATE=false" in markdown


def test_missing_authority_keeps_coverage_gate_red(tmp_path: Path) -> None:
    report = _generate(
        tmp_path,
        _write_real_catalog(tmp_path, authority_status="MISSING"),
        _write_golden_spec(tmp_path),
        expected_total=2,
    )

    assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 1
    assert report.coverage_complete is False


def test_expected_authority_blocked_candidate_can_pass_inert_h2_gate(
    tmp_path: Path,
) -> None:
    path = _write_real_catalog(tmp_path)
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["physical_objects"][0]["disposition"] = "REVIEW_REQUIRED"
    catalog["physical_objects"][0]["gate_statuses"]["authority"] = (
        "BLOCKED_NOT_CLEARED"
    )
    catalog["disposition_counts"]["INGEST"] = 0
    catalog["disposition_counts"]["REVIEW_REQUIRED"] = 1
    path.write_text(json.dumps(catalog), encoding="utf-8")

    report = _generate(
        tmp_path,
        path,
        _write_golden_spec(
            tmp_path,
            expected_final="REVIEW_REQUIRED",
            expected_authority="BLOCKED_NOT_CLEARED",
        ),
        expected_total=2,
    )

    assert report.blocked_ingest_candidates == 1
    assert report.mandatory_gate_blockers == {"authority": 1}
    assert report.coverage_complete is True
    assert "BLOCKED_INGEST_CANDIDATES=1" in render_markdown(report)


def test_rejects_catalog_rights_pass_not_derived_from_registry(
    tmp_path: Path,
) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(tmp_path)
    rights = yaml.safe_load(rights_path.read_text(encoding="utf-8"))
    rights["source_evidence"]["eduscol"]["rights_status"] = "REVIEW_REQUIRED"
    rights["source_evidence"]["eduscol"]["disposition_override"] = (
        "REVIEW_REQUIRED"
    )
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")

    with pytest.raises(ValueError, match="catalog rights gate evidence mismatch"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_rejects_catalog_pii_pass_not_derived_from_sealed_scan(
    tmp_path: Path,
) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(tmp_path)
    pii = json.loads(pii_path.read_text(encoding="utf-8"))
    pii["results"][0]["status"] = "REVIEW_REQUIRED_EXTRACTION_FAILED"
    pii_path.write_text(json.dumps(pii), encoding="utf-8")

    with pytest.raises(ValueError, match="catalog PII gate evidence mismatch"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_final_gate_requires_manifest_rights_pii_and_routing_evidence(
    tmp_path: Path,
) -> None:
    """P1 PRRT_kwDOTEIbbs6X3cnO: Final gate requires manifest, rights, PII, and routing."""
    # P1: Manifest is now required first
    with pytest.raises(ValueError, match="sealed manifest file is required"):
        generate_coverage_report(
            _write_real_catalog(tmp_path),
            golden_path=_write_golden_spec(tmp_path),
            expected_total=2,
        )


def test_rejects_synthetic_catalog_for_final_gate(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.json"
    path.write_text(
        json.dumps(
            {
                "corpus_total_objects": 2584,
                "totals": {"INGEST": 64, "REVIEW_REQUIRED": 2520},
                "verification_passed": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="real sealed corpus catalog"):
        generate_coverage_report(path, expected_total=2584)


def test_rejects_catalog_bound_to_another_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="catalog manifest SHA256 mismatch"):
        generate_coverage_report(
            _write_real_catalog(tmp_path),
            expected_total=2,
            expected_manifest_sha256="0" * 64,
        )


def test_h2f_defaut1_manifest_sha256_mismatch_is_detected(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 1: Any manifest content mismatch must be detected.

    When --manifest is provided, the coverage report MUST verify that:
    1. The manifest file's actual SHA256 matches the catalog's declared manifest_sha256
    2. The manifest entries exactly match the catalog's physical_objects

    If either check fails, the report must reject with a clear error.
    """
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, _ = _write_external_evidence(tmp_path)

    # Create a manifest with different content (will have different SHA256)
    manifest_path = tmp_path / "SHA256SUMS.txt"
    manifest_path.write_text(
        "c" * 64 + "  completely_different_file.pdf\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="H2-F Défaut 1"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_h2f_defaut1_missing_manifest_file_is_rejected(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 1: Non-existent manifest file must be rejected.

    P1 PRRT_kwDOTEIbbs6X3cnO: Manifest is now required for the final gate.
    """
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, _ = _write_external_evidence(tmp_path)

    # Point to non-existent manifest
    manifest_path = tmp_path / "nonexistent_SHA256SUMS.txt"

    # P1: Error message changed to "sealed manifest file is required"
    with pytest.raises(ValueError, match="sealed manifest file is required"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_h2f_defaut5_authority_pass_autodeclare_is_not_sufficient(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: authority=PASS auto-déclaré ne suffit pas sans preuve LOT41A/42.

    Le catalogue peut contenir authority=PASS mais le coverage report doit
    comptabiliser cela comme INGEST_WITH_SELF_DECLARED_AUTHORITY car aucune
    preuve LOT41A/42 externe n'est fournie et liée au manifest exact.

    Note: Le compilateur candidat ne peut jamais produire authority=PASS
    (il est toujours BLOCKED_NOT_CLEARED). Ce test vérifie qu'un catalogue
    manuellement modifié avec authority=PASS est tout de même détecté.
    """
    catalog_path = _write_real_catalog(tmp_path)
    # Simulate a manually injected authority=PASS without LOT41A/42 evidence
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["physical_objects"][0]["gate_statuses"]["authority"] = "PASS"
    catalog["physical_objects"][0]["disposition"] = "INGEST"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    # The spec expects authority=PASS but the system must still count it
    # as a violation if there's no external LOT41A/42 proof
    golden_path = _write_golden_spec(tmp_path, expected_authority="PASS")

    # Key: include_authority=False - no external LOT41A evidence
    report = _generate(
        tmp_path,
        catalog_path,
        golden_path,
        include_authority=False,  # No authority evidence provided
        expected_total=2,
    )

    # H2-F Défaut 5: Self-declared authority=PASS MUST be flagged
    assert report.safety_invariants.get("INGEST_WITH_SELF_DECLARED_AUTHORITY", 0) == 1, \
        "Self-declared authority=PASS should be counted as a violation"
    assert report.coverage_complete is False, \
        "Coverage cannot be complete with self-declared authority"


def test_h2f_defaut5_authority_bound_to_wrong_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: Authority evidence bound to a different manifest must fail closed."""
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(
        tmp_path, include_authority=False
    )

    # Create authority evidence bound to a DIFFERENT manifest
    wrong_manifest_sha256 = "b" * 64  # Different from MANIFEST_SHA256
    authority = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": "wrong_manifest_authority",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": wrong_manifest_sha256,  # Wrong manifest!
        "profile_id": "test_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [CONTENT_SHA256],
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    authority_path = _write_authority(tmp_path / "wrong_authority.json", authority)

    with pytest.raises(
        ValueError, match="SEMANTIC_VALIDATION failed: authority is bound to another"
    ):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            authority_path=authority_path,
            authority_review_binding_path=_write_review_binding(
                tmp_path, _valid_authority_document()
            ),
            authority_trust_anchor_path=_write_trust_anchor(tmp_path),
            authority_environment="rehearsal",
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
            authority_now=AUTHORITY_NOW,
        )


def test_h2f_defaut5_content_not_in_authority_allowlist_fails(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: Content not in authority allowlist must be flagged."""
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(
        tmp_path, include_authority=False
    )

    # Create authority evidence that does NOT include the catalog's content SHA256
    different_content_sha256 = "c" * 64  # Different from CONTENT_SHA256
    authority = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": "narrow_authority",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": MANIFEST_SHA256,
        "profile_id": "test_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [different_content_sha256],  # Wrong content!
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    authority_path = _write_authority(tmp_path / "narrow_authority.json", authority)

    # L'allowlist doit couvrir TOUT le périmètre d'ingestion, pas un
    # échantillon : une couverture partielle est un refus, pas un simple
    # invariant compté dans un rapport par ailleurs présenté comme vérifié.
    with pytest.raises(
        ValueError,
        match="SEMANTIC_VALIDATION failed: the authority allowlist does not cover",
    ):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            authority_path=authority_path,
            authority_review_binding_path=_write_review_binding(
                tmp_path, _valid_authority_document()
            ),
            authority_trust_anchor_path=_write_trust_anchor(tmp_path),
            authority_environment="rehearsal",
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
            authority_now=AUTHORITY_NOW,
        )


def test_h2f_defaut5_lot41a_v1_has_no_content_verification(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: LOT41A-V1 (no content allowlist) cannot verify content authority."""
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(
        tmp_path, include_authority=False
    )

    # Create V1 authority (no allowed_content_sha256)
    authority = {
        "protocol_version": "LOT41A-V1",  # V1, no content list
        "authorization_id": "v1_authority",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": MANIFEST_SHA256,
        "profile_id": "test_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    authority_path = tmp_path / "v1_authority.json"
    authority_path.write_bytes(
        ScopeAuthorizationArtifactV1.model_validate(authority).canonical_bytes()
    )

    # V1 ne porte aucune allowlist de contenu : elle ne peut donc jamais
    # prouver qu'un objet précis du corpus a été autorisé. Le gate final la
    # refuse au lieu de la compter comme « auto-déclarée » dans un rapport
    # qui prétendrait par ailleurs avoir vérifié l'autorité.
    with pytest.raises(
        ValueError, match="STRUCTURAL_VALIDATION failed: the final gate requires"
    ):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            authority_path=authority_path,
            authority_review_binding_path=_write_review_binding(
                tmp_path, _valid_authority_document()
            ),
            authority_trust_anchor_path=_write_trust_anchor(tmp_path),
            authority_environment="rehearsal",
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
            authority_now=AUTHORITY_NOW,
        )


# ---------------------------------------------------------------------------
# H2-F : les trois couches de validation d'autorité, un rejet par contrôle
# ---------------------------------------------------------------------------


def _valid_authority_document() -> dict[str, object]:
    """L'autorisation nominale — chaque test ci-dessous n'en change qu'UNE
    chose, pour qu'un rejet ne puisse jamais être attribué au mauvais
    contrôle."""
    return {
        "protocol_version": "LOT41A-V2",
        "authorization_id": "h2b_test_authority_v1",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": MANIFEST_SHA256,
        "profile_id": "h2b_test_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review: no PII found",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [CONTENT_SHA256],
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test_collection",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }


def _generate_with_authority(
    tmp_path: Path,
    *,
    authority_path: Path,
    now=AUTHORITY_NOW,
    revocations_path: Path | None = None,
    binding_path: Path | None = None,
    trust_anchor_path: Path | None = None,
    environment: str = "rehearsal",
):
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(
        tmp_path, include_authority=False
    )
    if binding_path is None:
        binding_path = _write_review_binding(tmp_path, _valid_authority_document())
    if trust_anchor_path is None:
        trust_anchor_path = _write_trust_anchor(tmp_path)
    return generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        manifest_path=manifest_path,
        authority_path=authority_path,
        authority_revocations_path=revocations_path,
        authority_review_binding_path=binding_path,
        authority_trust_anchor_path=trust_anchor_path,
        authority_environment=environment,
        authority_now=now,
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )


class TestAuthorityStructuralValidation:
    def test_a_merely_well_formed_json_is_never_an_authorization(
        self, tmp_path: Path
    ) -> None:
        """« JSON bien formé » n'est pas « autorisation ». Le minimum
        syntaxique doit être refusé par la couche structurelle."""
        path = tmp_path / "minimal.json"
        path.write_bytes(b'{"protocol_version": "LOT41A-V2"}\n')
        with pytest.raises(ValueError, match="STRUCTURAL_VALIDATION failed"):
            _generate_with_authority(tmp_path, authority_path=path)

    def test_non_canonical_bytes_are_refused(self, tmp_path: Path) -> None:
        """Le contrôle réellement ajouté : des octets valides au sens du
        schéma mais réordonnés/ré-indentés produisaient auparavant une
        autorisation dont le digest ne désignait aucun fichier relisible."""
        document = _valid_authority_document()
        path = tmp_path / "non_canonical.json"
        path.write_text(json.dumps(document, indent=4), encoding="utf-8")
        with pytest.raises(ValueError, match="not in canonical form"):
            _generate_with_authority(tmp_path, authority_path=path)

    def test_an_unknown_protocol_is_refused(self, tmp_path: Path) -> None:
        document = _valid_authority_document()
        document["protocol_version"] = "LOT41A-V3"
        path = tmp_path / "bad_protocol.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match="STRUCTURAL_VALIDATION failed"):
            _generate_with_authority(tmp_path, authority_path=path)


class TestAuthoritySemanticValidation:
    def test_an_expired_authorization_is_refused(self, tmp_path: Path) -> None:
        path = _write_authority(
            tmp_path / "authority.json", _valid_authority_document()
        )
        with pytest.raises(ValueError, match="SEMANTIC_VALIDATION failed: .*expired"):
            _generate_with_authority(
                tmp_path,
                authority_path=path,
                now=datetime(2027, 1, 1, tzinfo=UTC),
            )

    def test_an_authorization_not_valid_yet_is_refused(self, tmp_path: Path) -> None:
        path = _write_authority(
            tmp_path / "authority.json", _valid_authority_document()
        )
        with pytest.raises(
            ValueError, match="SEMANTIC_VALIDATION failed: .*not valid yet"
        ):
            _generate_with_authority(
                tmp_path,
                authority_path=path,
                now=datetime(2025, 1, 1, tzinfo=UTC),
            )

    def test_a_revoked_authorization_is_refused(self, tmp_path: Path) -> None:
        path = _write_authority(
            tmp_path / "authority.json", _valid_authority_document()
        )
        revocations = tmp_path / "revocations.json"
        revocations.write_text(
            json.dumps({"revoked_authorization_ids": ["h2b_test_authority_v1"]}),
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError, match="SEMANTIC_VALIDATION failed: .*revocation registry"
        ):
            _generate_with_authority(
                tmp_path, authority_path=path, revocations_path=revocations
            )

    def test_a_revocation_registry_naming_another_id_does_not_block(
        self, tmp_path: Path
    ) -> None:
        """Garde-fou de sensibilité : le refus ci-dessus doit venir de
        l'identifiant, pas de la simple présence d'un registre."""
        path = _write_authority(
            tmp_path / "authority.json", _valid_authority_document()
        )
        revocations = tmp_path / "revocations.json"
        revocations.write_text(
            json.dumps({"revoked_authorization_ids": ["some_other_authority"]}),
            encoding="utf-8",
        )
        report = _generate_with_authority(
            tmp_path, authority_path=path, revocations_path=revocations
        )
        assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 0

    def test_an_undetermined_rights_category_is_refused(self, tmp_path: Path) -> None:
        """Deux barrières indépendantes, mesurées ensemble : le contrat rend
        ``unknown`` irreprésentable (le fichier ne peut donc pas être écrit
        sous forme canonique), et la couche sémantique le refuserait quand
        même si une telle ligne apparaissait par un chemin inattendu."""
        document = _valid_authority_document()
        document["rights_categories"] = ["unknown"]
        with pytest.raises(ValidationError, match="never contain 'unknown'"):
            ScopeAuthorizationArtifactV2.model_validate(document)

        path = tmp_path / "unknown_rights.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match="STRUCTURAL_VALIDATION failed"):
            _generate_with_authority(tmp_path, authority_path=path)

    def test_a_malformed_revocation_registry_is_refused(self, tmp_path: Path) -> None:
        path = _write_authority(
            tmp_path / "authority.json", _valid_authority_document()
        )
        revocations = tmp_path / "revocations.json"
        revocations.write_text(json.dumps({"revoked_authorization_ids": [""]}), encoding="utf-8")
        with pytest.raises(ValueError, match="revoked_authorization_ids"):
            _generate_with_authority(
                tmp_path, authority_path=path, revocations_path=revocations
            )


class TestAuthorityReviewBindingValidation:
    def test_the_report_publishes_the_recomputed_binding(self, tmp_path: Path) -> None:
        """Le rapport publie ce sur quoi il s'est appuyé — chemin canonique
        dérivé de l'identifiant, digest recalculé, SHA-1 de blob Git des
        octets exacts — plutôt qu'un booléen « vérifié »."""
        document = _valid_authority_document()
        path = _write_authority(tmp_path / "authority.json", document)
        report = _generate_with_authority(tmp_path, authority_path=path)

        artifact = ScopeAuthorizationArtifactV2.model_validate(document)
        assert report.input_files["authority_canonical_path"] == (
            "governance/authorizations/h2b_test_authority_v1.json"
        )
        assert report.input_files["authority_authorization_digest"] == artifact.digest()
        assert report.input_files["authority_artifact_blob_sha"] == git_blob_sha1(
            artifact.canonical_bytes()
        )

    def test_the_canonical_path_is_derived_from_the_identifier_only(
        self, tmp_path: Path
    ) -> None:
        """Un opérateur ne choisit jamais le chemin relu : renommer le
        fichier local ne change pas le chemin gouverné qui sera relu."""
        document = _valid_authority_document()
        path = _write_authority(tmp_path / "renamed-by-operator.json", document)
        report = _generate_with_authority(tmp_path, authority_path=path)
        assert report.input_files["authority_canonical_path"] == (
            "governance/authorizations/h2b_test_authority_v1.json"
        )


# ---------------------------------------------------------------------------
# ADR-0035 — le gate final exige une liaison de revue scellée
# ---------------------------------------------------------------------------


def _generate_with_binding(
    tmp_path: Path,
    *,
    binding_path: Path | None = None,
    trust_anchor_path: Path | None = None,
    environment: str = "production",
    now: datetime = AUTHORITY_NOW,
    **binding_overrides: Any,
):
    """Chemin nominal, avec un seul paramètre du reçu modifié à la fois."""
    authority = _valid_authority_document()
    authority_path = _write_authority(tmp_path / "authority.json", authority)
    if binding_path is None:
        binding_path = _write_review_binding(tmp_path, authority, **binding_overrides)
    if trust_anchor_path is None:
        trust_anchor_path = _write_trust_anchor(tmp_path, environment=environment)
    return _generate_with_authority(
        tmp_path,
        authority_path=authority_path,
        binding_path=binding_path,
        trust_anchor_path=trust_anchor_path,
        environment=environment,
        now=now,
    )


class TestFinalGateRequiresReviewBinding:
    def test_a_valid_receipt_lets_the_final_gate_pass_the_binding_layer(
        self, tmp_path: Path
    ) -> None:
        report = _generate_with_binding(tmp_path)
        assert report.authority_review_binding_verified is True
        assert report.authority_environment == "production"
        assert report.input_files["authority_review_reviewer"] == TRUSTED_REVIEWER
        assert report.input_files["authority_review_head_sha"] == HEAD_SHA
        assert report.input_files["authority_review_repository"] == REPOSITORY

    def test_a_missing_receipt_is_refused(self, tmp_path: Path) -> None:
        """Le défaut fermé par ce lot : sans preuve de revue, le gate ne peut
        plus être vert — et ce n'est pas un avertissement, c'est un refus."""
        authority = _valid_authority_document()
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        catalog_path = _write_real_catalog(tmp_path)
        golden_path = _write_golden_spec(tmp_path)
        routing_path, rights_path, pii_path, _, manifest_path = (
            _write_external_evidence(tmp_path, include_authority=False)
        )
        with pytest.raises(ValueError, match="requires .*review binding receipt"):
            generate_coverage_report(
                catalog_path,
                rights_path=rights_path,
                pii_path=pii_path,
                routing_path=routing_path,
                golden_path=golden_path,
                manifest_path=manifest_path,
                authority_path=authority_path,
                authority_now=AUTHORITY_NOW,
                expected_total=2,
                expected_manifest_sha256=MANIFEST_SHA256,
            )

    def test_a_receipt_file_that_does_not_exist_is_refused(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            _generate_with_binding(tmp_path, binding_path=tmp_path / "absent.json")

    def test_a_missing_trust_anchor_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="trust anchor does not exist"):
            _generate_with_binding(
                tmp_path, trust_anchor_path=tmp_path / "absent_anchor.json"
            )

    def test_a_caller_authored_unsigned_receipt_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Un JSON écrit à la main — le scénario exact que ce lot ferme."""
        path = tmp_path / "forged.json"
        path.write_text(
            json.dumps(_review_binding_document(_valid_authority_document())),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="REVIEW_BINDING_VALIDATION failed"):
            _generate_with_binding(tmp_path, binding_path=path)

    def test_a_receipt_signed_by_an_unapproved_key_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = _write_review_binding(
            tmp_path,
            _valid_authority_document(),
            seed="55" * 32,
            filename="rogue.json",
        )
        with pytest.raises(ValueError, match="signature does not verify"):
            _generate_with_binding(tmp_path, binding_path=path)

    def test_an_unknown_key_id_is_refused(self, tmp_path: Path) -> None:
        path = _write_review_binding(
            tmp_path,
            _valid_authority_document(),
            key_id="rogue-signer",
            filename="unknown_key.json",
        )
        with pytest.raises(ValueError, match="not declared in the trust anchor"):
            _generate_with_binding(tmp_path, binding_path=path)

    def test_a_tampered_receipt_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "review_binding.json"
        _write_review_binding(tmp_path, _valid_authority_document())
        document = json.loads(path.read_text(encoding="utf-8"))
        document["binding"]["reviewer_login"] = "attacker"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="REVIEW_BINDING_VALIDATION failed"):
            _generate_with_binding(tmp_path, binding_path=path)

    @pytest.mark.parametrize(
        ("override", "message"),
        (
            ({"repository": "attacker/RAG"}, "another repository"),
            ({"reviewer_login": "stranger"}, "not among the trusted"),
        ),
    )
    def test_a_receipt_from_another_context_is_refused(
        self, tmp_path: Path, override: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            _generate_with_binding(tmp_path, **override)

    @pytest.mark.parametrize(
        "override",
        (
            {"pull_request": 96},
            {"base_sha": "9" * 40},
            {"head_sha": "8" * 40},
        ),
    )
    def test_a_receipt_for_another_pr_base_or_head_is_refused(
        self, tmp_path: Path, override: dict[str, Any]
    ) -> None:
        """Le challenge dérive de ces dimensions : les changer sans le
        recalculer casse la liaison, et le recalculer produirait un
        challenge qu'aucune review n'a jamais porté."""
        with pytest.raises(ValueError, match="challenge recycled"):
            _generate_with_binding(tmp_path, **override)

    def test_a_receipt_for_another_artifact_is_refused(self, tmp_path: Path) -> None:
        other = _valid_authority_document()
        other["allowed_content_sha256"] = ["b" * 64]
        path = _write_review_binding(tmp_path, other, filename="other_artifact.json")
        with pytest.raises(ValueError, match="different authorization bytes"):
            _generate_with_binding(tmp_path, binding_path=path)

    def test_a_receipt_with_another_git_blob_sha1_is_refused(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="Git blob SHA-1"):
            _generate_with_binding(
                tmp_path, authorization_artifact_git_blob_sha1="c" * 40
            )

    def test_a_receipt_naming_another_authorization_is_refused(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="covers authorization"):
            _generate_with_binding(
                tmp_path,
                authorization_id="other-authority-v1",
                authorization_artifact_path=(
                    "governance/authorizations/other-authority-v1.json"
                ),
            )

    def test_a_self_approved_receipt_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="self-approval"):
            _generate_with_binding(
                tmp_path,
                author_login=TRUSTED_REVIEWER,
                challenge_digest=expected_challenge_digest(
                    repository=REPOSITORY,
                    pull_request=PULL_REQUEST,
                    base_ref="main",
                    base_sha=BASE_SHA,
                    head_sha=HEAD_SHA,
                    author=TRUSTED_REVIEWER,
                    reviewer=TRUSTED_REVIEWER,
                ),
            )

    def test_an_insufficient_permission_is_unrepresentable(self, tmp_path: Path) -> None:
        with pytest.raises(Exception, match="reviewer_permission"):
            _write_review_binding(
                tmp_path, _valid_authority_document(), reviewer_permission="read"
            )

    def test_an_expired_receipt_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="expired"):
            _generate_with_binding(tmp_path, now=datetime(2027, 1, 1, tzinfo=UTC))

    def test_a_revoked_authorization_is_refused_even_with_a_valid_receipt(
        self, tmp_path: Path
    ) -> None:
        """Une revue scellée ne survit jamais à la révocation de ce qu'elle
        a relu."""
        authority = _valid_authority_document()
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        revocations = tmp_path / "revocations.json"
        revocations.write_text(
            json.dumps(
                {"revoked_authorization_ids": [str(authority["authorization_id"])]}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="revocation registry"):
            _generate_with_authority(
                tmp_path,
                authority_path=authority_path,
                revocations_path=revocations,
                binding_path=_write_review_binding(tmp_path, authority),
                trust_anchor_path=_write_trust_anchor(tmp_path, environment="production"),
                environment="production",
            )

    def test_a_receipt_reused_for_another_corpus_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Le reçu couvre des octets, pas un corpus : le réutiliser pour une
        autre autorisation est refusé même s'il est parfaitement signé."""
        first = _valid_authority_document()
        second = _valid_authority_document()
        second["authorization_id"] = "h2b_other_corpus_v1"
        second["allowed_content_sha256"] = ["d" * 64]
        binding_for_second = _write_review_binding(
            tmp_path, second, filename="binding_for_second.json"
        )
        authority_path = _write_authority(tmp_path / "authority.json", first)
        with pytest.raises(ValueError, match="covers authorization"):
            _generate_with_authority(
                tmp_path,
                authority_path=authority_path,
                binding_path=binding_for_second,
                trust_anchor_path=_write_trust_anchor(tmp_path, environment="production"),
                environment="production",
            )


class TestRehearsalCanNeverBeGreen:
    def test_a_rehearsal_run_verifies_the_chain_but_never_turns_green(
        self, tmp_path: Path
    ) -> None:
        """Un mode non final existe, il est explicitement nommé, et il est
        structurellement incapable de rendre un verdict final vert."""
        report = _generate(
            tmp_path,
            _write_real_catalog(tmp_path),
            _write_golden_spec(tmp_path),
            include_authority=True,
            environment="rehearsal",
            expected_total=2,
        )
        assert report.authority_review_binding_verified is True
        assert report.decision_coverage_complete is True
        assert report.golden_validation_pass is True
        assert all(value == 0 for value in report.safety_invariants.values())
        # Toute la chaîne est vérifiée, et pourtant :
        assert report.coverage_complete is False
        assert report.authority_environment == "rehearsal"
        assert "AUTHORITY_EVIDENCE_MODE=rehearsal" in render_markdown(report)

    def test_a_test_key_can_never_validate_a_production_run(
        self, tmp_path: Path
    ) -> None:
        authority = _valid_authority_document()
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        with pytest.raises(ValueError, match="'test' environment"):
            _generate_with_authority(
                tmp_path,
                authority_path=authority_path,
                binding_path=_write_review_binding(tmp_path, authority),
                trust_anchor_path=_write_trust_anchor(tmp_path, environment="test"),
                environment="production",
            )

    def test_an_invalid_environment_is_refused(self, tmp_path: Path) -> None:
        authority = _valid_authority_document()
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        with pytest.raises(ValueError, match="authority_environment must be"):
            _generate_with_authority(
                tmp_path, authority_path=authority_path, environment="whatever"
            )


def test_the_repository_ships_no_production_trust_anchor() -> None:
    """Barrière de go-live, mesurée plutôt que promise : tant qu'aucune ancre
    de production n'est provisionnée, aucun reçu de production ne peut être
    vérifié. Ce test tombera le jour où l'ancre réelle sera commitée — ce
    sera alors une décision consciente, pas un glissement."""
    from rag_pedago.imports.h2b_coverage_report import _REPOSITORY_ROOT

    anchors = list((_REPOSITORY_ROOT / "governance").rglob("*trust*anchor*.json")) if (
        _REPOSITORY_ROOT / "governance"
    ).is_dir() else []
    assert anchors == [], (
        "a production trust anchor appeared in the repository — provisioning it "
        "is a deliberate go-live decision that must be reviewed on its own"
    )
