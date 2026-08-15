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
from nexus_contracts.h2_coverage_evidence import parse_h2_coverage_evidence
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    TRUSTED_REVIEW_PROTOCOL,
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    parse_trust_anchor,
    public_key_hex,
    sign_review_binding,
)
from pydantic import ValidationError

from rag_pedago.imports import h2b_coverage_report as module
from rag_pedago.imports.h2b_coverage_report import (
    _promote_authority_cleared_candidates,
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


def _install_governed_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    anchor_environment: str = "production",
    anchor_seed: str = TEST_SIGNING_SEED,
    revoked: list[str] | None = None,
    write_anchor: bool = True,
    write_revocations: bool = True,
) -> Path:
    """Installe une racine gouvernée de test (ADR-0035, F1/F2).

    ``_GOVERNED_REPOSITORY_ROOT`` est délibérément **non surchargeable
    depuis le code de production** : ni argument, ni variable
    d'environnement. Le seul moyen de l'exercer est donc de le remplacer
    dans le module, ce qui est hors d'atteinte d'un opérateur. Les tests
    de gouvernance vérifient séparément qu'aucun *vrai* vecteur de
    redirection ne fonctionne (``NEXUS_REPOSITORY_ROOT``, argument CLI,
    symlink, évasion).
    """
    root = tmp_path / "governed_root"
    (root / "governance" / "trust-anchors").mkdir(parents=True, exist_ok=True)
    # Le faux checkout doit porter les marqueurs de racine : la garde de
    # packaging refuse toute racine qui ne ressemble pas au dépôt.
    for marker in module._GOVERNED_ROOT_MARKERS:
        target = root / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        if "." in target.name:
            target.write_text("", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
    if write_anchor:
        (root / module._GOVERNED_TRUST_ANCHOR_PATH).write_text(
            json.dumps(
                {
                    "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
                    "keys": [
                        {
                            "key_id": TEST_KEY_ID,
                            "algorithm": "ed25519",
                            "public_key": public_key_hex(anchor_seed),
                            "environment": anchor_environment,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    if write_revocations:
        (root / module._GOVERNED_REVOCATIONS_PATH).write_text(
            json.dumps(
                {
                    "protocol_version": module._REVOCATIONS_PROTOCOL_VERSION,
                    "revoked_authorization_ids": revoked or [],
                }
            ),
            encoding="utf-8",
        )
    # F1 : l'allowlist des relecteurs habilités est elle aussi lue au
    # chemin gouverné en production — le faux checkout doit donc la porter.
    reviewers_path = root / module._TRUSTED_REVIEWERS_CONFIG
    reviewers_path.parent.mkdir(parents=True, exist_ok=True)
    reviewers_path.write_text(
        (
            module._REPOSITORY_ROOT / module._TRUSTED_REVIEWERS_CONFIG
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_GOVERNED_REPOSITORY_ROOT", root)
    return root


def _write_revocations(
    path: Path, revoked: list[str], *, protocol_version: str | None = None
) -> Path:
    path.write_text(
        json.dumps(
            {
                "protocol_version": (
                    module._REVOCATIONS_PROTOCOL_VERSION
                    if protocol_version is None
                    else protocol_version
                ),
                "revoked_authorization_ids": revoked,
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
        # F1 : en production l'ancre est gouvernée et fournir l'argument
        # est un refus ; la fixture n'est donc passée qu'en rehearsal.
        authority_trust_anchor_path=(
            tmp_path / "trust_anchor.json"
            if authority_path is not None and environment == "rehearsal"
            else None
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
                # F4 : la catégorie de droits fait partie du périmètre que
                # l'autorisation doit couvrir exhaustivement.
                "rights_category_candidate": "officiel_public",
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nominal test: with proper LOT41A-V2 authority evidence, coverage is complete.

    F1/F2 : le run est en mode production, donc l'ancre et le registre
    viennent des chemins gouvernés — aucun argument ne les désigne."""
    _install_governed_root(monkeypatch, tmp_path)
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


class TestH2CoverageEvidenceProjection:
    """ADR-0042 : ``report_to_h2_coverage_evidence`` projette un
    ``CoverageReport`` déjà calculé vers le contrat partagé — aucun
    recalcul, une représentation fidèle et strictement validée."""

    def test_a_passing_production_report_projects_to_valid_canonical_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path)
        report = _generate(
            tmp_path,
            _write_real_catalog(tmp_path),
            _write_golden_spec(tmp_path),
            include_authority=True,
            expected_total=2,
        )
        assert report.coverage_complete is True  # fixture sanity, not this test's point

        evidence = module.report_to_h2_coverage_evidence(report)

        assert evidence.h2_coverage_gate_pass == report.h2_coverage_gate_pass
        assert evidence.manifest_sha256 == report.manifest_sha256
        assert evidence.git_commit == report.git_commit
        assert evidence.rights_gate_status == report.rights_gate_status
        assert evidence.pii_gate_status == report.pii_gate_status
        # Round-trips through the shared contract's own strict parser --
        # proves the projection is genuinely canonical, not "close enough".
        reparsed = parse_h2_coverage_evidence(evidence.canonical_bytes())
        assert reparsed.canonical_bytes() == evidence.canonical_bytes()

    def test_input_file_digests_excludes_non_digest_authority_binding_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``report.input_files`` also carries ``authority_<binding-field>``
        entries (path, git blob SHA-1, reviewer login, ...) merged in from
        ``authority_binding`` -- these are never SHA-256 digests, and must
        never leak into the strict digest map the shared contract expects."""
        _install_governed_root(monkeypatch, tmp_path)
        report = _generate(
            tmp_path,
            _write_real_catalog(tmp_path),
            _write_golden_spec(tmp_path),
            include_authority=True,
            expected_total=2,
        )
        non_digest_keys = {
            key
            for key in report.input_files
            if key.startswith("authority_") and key != "authority_revocations"
        }
        assert non_digest_keys, "fixture sanity: expected at least one authority_* binding field"

        evidence = module.report_to_h2_coverage_evidence(report)

        assert not (non_digest_keys & set(evidence.input_file_digests))
        for digest in evidence.input_file_digests.values():
            assert module.re.fullmatch(r"[0-9a-f]{64}", digest) is not None

    def test_rehearsal_report_is_refused(self) -> None:
        # Directly constructed: this test's only point is the environment
        # gate on the pure projection function, not the full generation
        # pipeline -- a hand-built dataclass instance is the right tool.
        report = module.CoverageReport(
            report_id="h2b_coverage_test",
            generated_at="2026-08-13T12:00:00.000000Z",
            git_commit="a" * 40,
            git_branch="main",
            real_corpus_catalog_source=True,
            synthetic_catalog_used_for_final_gate=False,
            manifest_sha256="b" * 64,
            corpus_total_expected=1,
            corpus_total_actual=1,
            corpus_match=True,
            authority_environment="rehearsal",
        )
        with pytest.raises(module.H2CoverageEvidenceError, match="production-only"):
            module.report_to_h2_coverage_evidence(report)


def test_missing_authority_keeps_coverage_gate_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_governed_root(monkeypatch, tmp_path)
    report = _generate(
        tmp_path,
        _write_real_catalog(tmp_path, authority_status="MISSING"),
        _write_golden_spec(tmp_path),
        expected_total=2,
    )

    assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 1
    assert report.coverage_complete is False


def test_real_authority_covering_a_blocked_candidate_promotes_it_to_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2 authority promotion (PR #109's E2E rehearsal finding).

    Formerly ``test_expected_authority_blocked_candidate_can_pass_inert_
    h2_gate`` -- same exact fixture (a real candidate the compiler could
    only ever mark ``REVIEW_REQUIRED``/``BLOCKED_NOT_CLEARED``, since
    ``corpus_catalog_compiler.py`` deliberately never has real LOT41A
    authority available to it, with a real, covering LOT41A-V2 authority
    provided via the default ``include_authority=True``), but its old
    assertions (``blocked_ingest_candidates == 1``,
    ``coverage_complete is True`` *despite* real covering evidence being
    available) described the pre-fix gap this promotion closes, not a
    genuine safety requirement -- corrected here, renamed to match.

    The candidate catalog FILE itself stays exactly as compiled (golden
    spec still expects ``REVIEW_REQUIRED``/``BLOCKED_NOT_CLEARED`` -- the
    golden corpus validator checks the catalog file's own claims, never
    a promoted, evidence-informed state); promotion is evaluated
    separately and only affects safety-invariant/gate-pass computation."""
    _install_governed_root(monkeypatch, tmp_path)
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
        # default include_authority=True: a real LOT41A-V2 authority
        # covering exactly CONTENT_SHA256 is provided (see
        # _write_external_evidence) -- this is what promotes the
        # candidate.
        expected_total=2,
    )

    assert report.blocked_ingest_candidates == 0
    assert report.mandatory_gate_blockers == {}
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
    assert report.coverage_complete is True


def test_no_authority_evidence_at_all_leaves_the_candidate_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without any authority evidence file, promotion never fabricates
    coverage: the candidate stays blocked, and the overall gate stays red
    regardless (``authority_review_binding_verified``/
    ``authority_revocations_checked`` both require a real authority file
    to ever be provided at all, independent of any single item's
    coverage)."""
    _install_governed_root(monkeypatch, tmp_path)
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
        include_authority=False,
        expected_total=2,
    )

    assert report.blocked_ingest_candidates == 1
    assert report.mandatory_gate_blockers == {"authority": 1}
    assert report.authority_review_binding_verified is False
    assert report.coverage_complete is False
    assert "BLOCKED_INGEST_CANDIDATES=1" in render_markdown(report)


def test_authority_covers_candidate_but_rights_gate_still_blocks_promotion() -> None:
    """Authority coverage never substitutes for an independently-failed
    gate -- it only unblocks the one gate it actually speaks to. Here
    ``rights`` is still ``BLOCKED_NOT_CLEARED`` even though the covering
    authority is present: promotion must not happen.

    Exercised directly against ``_promote_authority_cleared_candidates``
    (unit-level) rather than through the full ``generate_coverage_report``
    pipeline: fabricating a whole real-catalog fixture where the declared
    ``rights`` gate is blocked while every other independently-recomputed
    evidence binding (``verify_catalog_evidence_bindings``, which
    recomputes rights/PII clearance from the routing/rights registries
    and rejects any mismatch) still agrees would require faking a real
    rights-registry non-clearance -- orthogonal to what this test is
    about, and exactly the kind of unrelated coupling a dedicated,
    independently-testable promotion function is meant to avoid."""
    item = {
        "content_sha256": CONTENT_SHA256,
        "path": "01_EDUSCOL_OFFICIEL/current.pdf",
        "base_disposition": "INGEST",
        "disposition": "REVIEW_REQUIRED",
        "currentness": "actuel",
        "gate_statuses": {
            "rights": "BLOCKED_NOT_CLEARED",
            "pii": "PASS",
            "authority": "BLOCKED_NOT_CLEARED",
        },
        "provenance_status": "VERIFIED",
        "attribution_metadata": {
            "source": "Eduscol",
            "source_url": "https://eduscol.education.gouv.fr/test",
        },
    }

    promoted = _promote_authority_cleared_candidates(
        [item],
        authority_allowlist=frozenset({CONTENT_SHA256}),
    )

    assert promoted == 0
    assert item["disposition"] == "REVIEW_REQUIRED"
    assert item["gate_statuses"]["authority"] == "BLOCKED_NOT_CLEARED"


def test_authority_covers_candidate_but_stale_currentness_still_blocks_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Promotion also checks the item-level facts the safety-invariant
    loop itself checks (currentness, format, provenance) -- not just the
    ``gate_statuses`` dict -- so a stale document is never promoted just
    because rights/PII/authority all clear. ``currentness`` is never a
    ``gate_statuses`` key (only ``rights``/``pii``/``authority`` are, by
    design -- see ``_apply_mandatory_ingest_gates``), so the reported
    blocker still only names ``authority``, which stays
    ``BLOCKED_NOT_CLEARED`` because promotion never happened."""
    _install_governed_root(monkeypatch, tmp_path)
    path = _write_real_catalog(tmp_path)
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["physical_objects"][0]["disposition"] = "REVIEW_REQUIRED"
    catalog["physical_objects"][0]["gate_statuses"]["authority"] = (
        "BLOCKED_NOT_CLEARED"
    )
    catalog["physical_objects"][0]["currentness"] = "transition"
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
    assert report.coverage_complete is False


def _valid_promotable_item() -> dict[str, Any]:
    """A minimal item that ``_promote_authority_cleared_candidates``
    promotes as-is -- every unit test below flips exactly one field away
    from this baseline and asserts promotion is refused."""
    return {
        "content_sha256": CONTENT_SHA256,
        "path": "01_EDUSCOL_OFFICIEL/current.pdf",
        "base_disposition": "INGEST",
        "disposition": "REVIEW_REQUIRED",
        "currentness": "actuel",
        "gate_statuses": {
            "rights": "PASS",
            "pii": "PASS",
            "authority": "BLOCKED_NOT_CLEARED",
        },
        "provenance_status": "VERIFIED",
        "attribution_metadata": {
            "source": "Eduscol",
            "source_url": "https://eduscol.education.gouv.fr/test",
        },
    }


class TestPromoteAuthorityClearedCandidatesUnit:
    """Unit-level branch coverage for ``_promote_authority_cleared_candidates``,
    one dedicated test per conditional so each can be mutation-tested in
    isolation: temporarily invert the branch, confirm the matching test
    below (and only that one) fails, then restore."""

    def _run(self, item: dict[str, Any], **allowlist_kwargs: Any) -> int:
        allowlist = allowlist_kwargs.get(
            "authority_allowlist", frozenset({CONTENT_SHA256})
        )
        return _promote_authority_cleared_candidates(
            [item], authority_allowlist=allowlist
        )

    def test_baseline_item_is_promoted(self) -> None:
        item = _valid_promotable_item()
        promoted = self._run(item)
        assert promoted == 1
        assert item["disposition"] == "INGEST"
        assert item["gate_statuses"]["authority"] == "PASS"

    def test_empty_allowlist_promotes_nothing(self) -> None:
        item = _valid_promotable_item()
        promoted = _promote_authority_cleared_candidates(
            [item], authority_allowlist=frozenset()
        )
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_none_allowlist_promotes_nothing(self) -> None:
        item = _valid_promotable_item()
        promoted = _promote_authority_cleared_candidates(
            [item], authority_allowlist=None
        )
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_non_dict_entries_are_skipped(self) -> None:
        promoted = _promote_authority_cleared_candidates(
            ["not-a-dict"], authority_allowlist=frozenset({CONTENT_SHA256})
        )
        assert promoted == 0

    def test_non_ingest_base_disposition_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["base_disposition"] = "EXCLUDE"
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_already_ingest_disposition_is_left_untouched(self) -> None:
        """``disposition`` is already ``INGEST`` -- promotion must never
        re-process it, even though every other field here still looks
        promotable (including an inconsistent ``authority`` gate that a
        real compiler would never produce alongside ``disposition==
        INGEST``, chosen specifically so this test cannot pass by
        accident via a later guard)."""
        item = _valid_promotable_item()
        item["disposition"] = "INGEST"
        promoted = self._run(item)
        assert promoted == 0
        assert item["gate_statuses"]["authority"] == "BLOCKED_NOT_CLEARED"

    def test_missing_gate_statuses_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        del item["gate_statuses"]
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_authority_gate_not_blocked_not_cleared_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["gate_statuses"]["authority"] = "BLOCKED_PII_DETECTED"
        promoted = self._run(item)
        assert promoted == 0
        assert item["gate_statuses"]["authority"] == "BLOCKED_PII_DETECTED"

    def test_rights_not_pass_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["gate_statuses"]["rights"] = "BLOCKED_NOT_CLEARED"
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_pii_not_pass_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["gate_statuses"]["pii"] = "BLOCKED_PII_DETECTED"
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_content_sha256_outside_the_allowlist_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        promoted = _promote_authority_cleared_candidates(
            [item], authority_allowlist=frozenset({"c" * 64})
        )
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_malformed_content_sha256_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["content_sha256"] = "not-a-real-sha"
        promoted = _promote_authority_cleared_candidates(
            [item], authority_allowlist=frozenset({"not-a-real-sha"})
        )
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_stale_currentness_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["currentness"] = "transition"
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_non_pdf_path_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["path"] = "01_EDUSCOL_OFFICIEL/current.docx"
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_unverified_provenance_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["provenance_status"] = "UNVERIFIED"
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_missing_attribution_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        del item["attribution_metadata"]
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_incomplete_attribution_is_not_promoted(self) -> None:
        item = _valid_promotable_item()
        item["attribution_metadata"] = {"source": "Eduscol", "source_url": ""}
        promoted = self._run(item)
        assert promoted == 0
        assert item["disposition"] == "REVIEW_REQUIRED"

    def test_original_list_object_is_mutated_in_place_not_replaced(self) -> None:
        """Confirms the promotion contract callers rely on: the function
        mutates the items it is given directly, so a caller-owned deep
        copy of ``physical_objects`` is what must be passed -- never the
        catalog's own list, which golden-corpus validation requires to
        stay byte-identical to the file on disk."""
        item = _valid_promotable_item()
        items = [item]
        promoted = _promote_authority_cleared_candidates(
            items, authority_allowlist=frozenset({CONTENT_SHA256})
        )
        assert promoted == 1
        assert items[0] is item
        assert item["disposition"] == "INGEST"


def test_authority_not_covering_the_real_base_disposition_ingest_candidate_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard for the candidate-set scoping defect found while
    implementing authority promotion: the completeness check
    (``_authority_semantic_validation``) must be evaluated against
    ``base_disposition == INGEST`` (the true candidate set a real
    compiler ever produces), never ``disposition == INGEST`` (which is
    never true for real compiler output, since authority is always
    ``BLOCKED_NOT_CLEARED`` there -- checking that set would make the
    completeness check vacuous, always trivially satisfied against an
    empty set, for every real catalog). Here ``base_disposition`` is
    ``INGEST`` but the provided authority's allowlist does not cover this
    ``content_sha256`` -- this must still raise, exactly like
    ``test_h2f_defaut5_content_not_in_authority_allowlist_fails`` already
    proves for the (less realistic) case where ``disposition`` is also
    already ``INGEST`` in the raw fixture."""
    _install_governed_root(monkeypatch, tmp_path)
    path = _write_real_catalog(tmp_path)
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["physical_objects"][0]["disposition"] = "REVIEW_REQUIRED"
    catalog["physical_objects"][0]["gate_statuses"]["authority"] = (
        "BLOCKED_NOT_CLEARED"
    )
    catalog["disposition_counts"]["INGEST"] = 0
    catalog["disposition_counts"]["REVIEW_REQUIRED"] = 1
    path.write_text(json.dumps(catalog), encoding="utf-8")

    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(
        tmp_path, include_authority=False
    )
    different_content_sha256 = "c" * 64
    authority = dict(_valid_authority_document())
    authority["allowed_content_sha256"] = [different_content_sha256]
    authority_path = _write_authority(tmp_path / "narrow_authority.json", authority)

    with pytest.raises(
        ValueError,
        match="SEMANTIC_VALIDATION failed: the authority allowlist does not cover",
    ):
        generate_coverage_report(
            path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=_write_golden_spec(
                tmp_path,
                expected_final="REVIEW_REQUIRED",
                expected_authority="BLOCKED_NOT_CLEARED",
            ),
            manifest_path=manifest_path,
            authority_path=authority_path,
            # La liaison de revue doit correspondre EXACTEMENT aux octets de
            # l'autorité réellement écrite (narrow, pas le document valide
            # par défaut) -- sinon un défaut différent (liaison, pas
            # complétude) serait déclenché en premier, et ce test ne
            # prouverait plus ce qu'il prétend.
            authority_review_binding_path=_write_review_binding(
                tmp_path, authority
            ),
            authority_trust_anchor_path=_write_trust_anchor(tmp_path),
            authority_environment="rehearsal",
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
            authority_now=AUTHORITY_NOW,
        )


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
    catalog_path: Path | None = None,
):
    if catalog_path is None:
        catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _, manifest_path = _write_external_evidence(
        tmp_path, include_authority=False
    )
    if binding_path is None:
        binding_path = _write_review_binding(tmp_path, _valid_authority_document())
    # F1 : en production, l'ancre est gouvernée et fournir l'argument est
    # un refus — la fixture ne sert donc qu'en rehearsal.
    if trust_anchor_path is None and environment != "production":
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
        revocations = _write_revocations(
            tmp_path / "revocations.json", ["h2b_test_authority_v1"]
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
        revocations = _write_revocations(
            tmp_path / "revocations.json", ["some_other_authority"]
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
        revocations = _write_revocations(tmp_path / "revocations.json", [""])
        with pytest.raises(ValueError, match="REVOCATION_REGISTRY_INVALID"):
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
    environment: str = "rehearsal",
    now: datetime = AUTHORITY_NOW,
    **binding_overrides: Any,
):
    """Chemin nominal, avec un seul paramètre du reçu modifié à la fois.

    Mode ``rehearsal`` par défaut (ADR-0035, F1) : ces tests portent sur la
    *sémantique du reçu*, et une ancre de fixture n'est légitime qu'en
    répétition. La gouvernance du chemin de l'ancre elle-même est couverte
    par ``TestGovernedTrustAnchor``."""
    authority = _valid_authority_document()
    authority_path = _write_authority(tmp_path / "authority.json", authority)
    if binding_path is None:
        binding_path = _write_review_binding(tmp_path, authority, **binding_overrides)
    # F1 : en production, aucune ancre n'est fournie — elle est gouvernée.
    # Le mode CLI ``rehearsal`` correspond à des clés ``environment="test"``.
    if trust_anchor_path is None and environment != "production":
        trust_anchor_path = _write_trust_anchor(tmp_path, environment="test")
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
        assert report.authority_environment == "rehearsal"
        assert report.input_files["authority_review_reviewer"] == TRUSTED_REVIEWER
        assert report.input_files["authority_review_head_sha"] == HEAD_SHA
        assert report.input_files["authority_review_repository"] == REPOSITORY

    def test_a_valid_receipt_under_the_governed_root_passes_in_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le pendant positif, en production réelle : l'ancre et le registre
        viennent des chemins gouvernés, aucun argument n'est fourni."""
        _install_governed_root(monkeypatch, tmp_path)
        report = _generate_with_binding(
            tmp_path, environment="production", trust_anchor_path=None
        )
        assert report.authority_review_binding_verified is True
        assert report.authority_revocations_checked is True
        assert report.authority_environment == "production"

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
        a relu. Le registre est celui, gouverné, du mode rehearsal."""
        authority = _valid_authority_document()
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        revocations = _write_revocations(
            tmp_path / "revocations.json", [str(authority["authorization_id"])]
        )
        with pytest.raises(ValueError, match="revocation registry"):
            _generate_with_authority(
                tmp_path,
                authority_path=authority_path,
                revocations_path=revocations,
                binding_path=_write_review_binding(tmp_path, authority),
                trust_anchor_path=_write_trust_anchor(tmp_path, environment="test"),
                environment="rehearsal",
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
                trust_anchor_path=_write_trust_anchor(tmp_path, environment="test"),
                environment="rehearsal",
            )


class TestGovernedTrustAnchor:
    """F1 — l'ancre de production n'est jamais désignée par l'appelant."""

    def test_a_caller_supplied_anchor_is_refused_in_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le cœur du constat F1 : jusqu'ici, l'opérateur choisissait le
        fichier qui déclarait quelles clés étaient dignes de confiance."""
        _install_governed_root(monkeypatch, tmp_path)
        external = _write_trust_anchor(tmp_path, environment="production")
        with pytest.raises(ValueError, match="TRUST_ANCHOR_ARGUMENT_FORBIDDEN"):
            _generate_with_binding(
                tmp_path, environment="production", trust_anchor_path=external
            )

    def test_an_absent_governed_anchor_refuses_in_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, write_anchor=False)
        with pytest.raises(ValueError, match="TRUST_ANCHOR_MISSING"):
            _generate_with_binding(tmp_path, environment="production")

    def test_a_self_declared_production_key_elsewhere_confers_no_authority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un fichier arbitraire peut écrire ``environment="production"`` ;
        cela ne lui donne rien, car il n'est jamais ouvert."""
        _install_governed_root(monkeypatch, tmp_path, write_anchor=False)
        impostor = tmp_path / "impostor_anchor.json"
        impostor.write_text(
            json.dumps(
                {
                    "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
                    "keys": [
                        {
                            "key_id": TEST_KEY_ID,
                            "algorithm": "ed25519",
                            "public_key": public_key_hex(TEST_SIGNING_SEED),
                            "environment": "production",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="TRUST_ANCHOR_ARGUMENT_FORBIDDEN"):
            _generate_with_binding(
                tmp_path, environment="production", trust_anchor_path=impostor
            )

    def test_nexus_repository_root_never_redirects_the_governed_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'override d'environnement existant était lui-même un vecteur de
        contournement : il ne doit rien pouvoir déplacer."""
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "governance" / "trust-anchors").mkdir(parents=True)
        monkeypatch.setenv("NEXUS_REPOSITORY_ROOT", str(elsewhere))
        import importlib

        reloaded = importlib.reload(module)
        try:
            assert reloaded._GOVERNED_REPOSITORY_ROOT != elsewhere
            assert (
                reloaded._GOVERNED_REPOSITORY_ROOT
                == Path(reloaded.__file__).resolve().parents[4]
            )
        finally:
            monkeypatch.delenv("NEXUS_REPOSITORY_ROOT", raising=False)
            importlib.reload(module)

    def test_a_symlinked_anchor_file_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _install_governed_root(monkeypatch, tmp_path, write_anchor=False)
        real = tmp_path / "real_anchor.json"
        real.write_text(
            json.dumps(
                {"protocol_version": REVIEW_BINDING_PROTOCOL_VERSION, "keys": []}
            ),
            encoding="utf-8",
        )
        (root / module._GOVERNED_TRUST_ANCHOR_PATH).symlink_to(real)
        with pytest.raises(ValueError, match="TRUST_ANCHOR failed: .*symlink"):
            _generate_with_binding(tmp_path, environment="production")

    def test_a_symlinked_path_component_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un lien sur un *répertoire* intermédiaire redirige tout aussi
        efficacement qu'un lien sur le fichier."""
        root = _install_governed_root(
            monkeypatch, tmp_path, write_anchor=False, write_revocations=False
        )
        (root / "governance" / "trust-anchors").rmdir()
        real_dir = tmp_path / "real_anchors"
        real_dir.mkdir()
        (root / "governance" / "trust-anchors").symlink_to(real_dir)
        with pytest.raises(ValueError, match="trust-anchors is a symlink"):
            _generate_with_binding(tmp_path, environment="production")


class TestRightsCategoriesAreCoveredExhaustively:
    """F4 — l'autorisation doit couvrir *toutes* les catégories de droits
    des objets qu'elle prétend autoriser, pas seulement leurs empreintes.

    Le verdict est un refus, jamais un compteur : incrémenter un invariant
    de sécurité laisserait le rapport présenter l'autorisation comme
    vérifiée alors qu'elle ne couvre pas son périmètre.
    """

    def _catalog_with(self, tmp_path: Path, **object_overrides: Any) -> Path:
        path = _write_real_catalog(tmp_path)
        catalog = json.loads(path.read_text(encoding="utf-8"))
        catalog["physical_objects"][0].update(object_overrides)
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return path

    def _run(self, tmp_path: Path, catalog_path: Path):
        return _generate_with_authority(
            tmp_path,
            authority_path=_write_authority(
                tmp_path / "authority.json", _valid_authority_document()
            ),
            catalog_path=catalog_path,
        )

    def test_a_covered_category_is_accepted(self, tmp_path: Path) -> None:
        catalog_path = self._catalog_with(
            tmp_path, rights_category_candidate="officiel_public"
        )
        report = self._run(tmp_path, catalog_path)
        assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 0

    def test_a_missing_category_is_refused(self, tmp_path: Path) -> None:
        catalog_path = self._catalog_with(tmp_path, rights_category_candidate=None)
        with pytest.raises(ValueError, match="without a rights_category_candidate"):
            self._run(tmp_path, catalog_path)

    def test_an_absent_field_is_refused(self, tmp_path: Path) -> None:
        path = _write_real_catalog(tmp_path)
        catalog = json.loads(path.read_text(encoding="utf-8"))
        del catalog["physical_objects"][0]["rights_category_candidate"]
        path.write_text(json.dumps(catalog), encoding="utf-8")
        with pytest.raises(ValueError, match="without a rights_category_candidate"):
            self._run(tmp_path, path)

    def test_a_value_outside_the_canonical_vocabulary_is_refused(
        self, tmp_path: Path
    ) -> None:
        catalog_path = self._catalog_with(
            tmp_path, rights_category_candidate="totally_made_up"
        )
        with pytest.raises(ValueError, match="not in the canonical vocabulary"):
            self._run(tmp_path, catalog_path)

    def test_a_category_the_authorization_does_not_grant_is_refused(
        self, tmp_path: Path
    ) -> None:
        catalog_path = self._catalog_with(
            tmp_path, rights_category_candidate="nexus_proprietaire"
        )
        with pytest.raises(ValueError, match="does not cover every rights category"):
            self._run(tmp_path, catalog_path)

    def test_non_ingest_objects_are_outside_this_perimeter(
        self, tmp_path: Path
    ) -> None:
        """Un objet EXCLUDE n'est pas publié : sa catégorie n'a pas à être
        couverte, et l'exiger rendrait le gate faussement rouge.

        Corrigé pendant l'implémentation de la promotion d'autorité
        (Finding C, ``docs/reports/lot_h2_authority_promotion.md``) : la
        fixture précédente ne modifiait que ``disposition``
        (``REVIEW_REQUIRED``) en laissant ``base_disposition`` à son
        défaut ``INGEST`` -- avant le correctif de périmètre
        (``base_disposition`` au lieu de ``disposition``), cela ne
        prouvait rien de plus que le défaut bogué lui-même : le
        périmètre de complétude était borné sur ``disposition``, donc
        toujours vide pour un candidat réel, quelle que soit sa
        catégorie. Un objet réellement « hors périmètre » est un objet
        dont ``base_disposition`` n'est pas ``INGEST``."""
        catalog_path = self._catalog_with(
            tmp_path,
            base_disposition="EXCLUDE",
            disposition="EXCLUDE",
            rights_category_candidate="nexus_proprietaire",
        )
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["disposition_counts"]["INGEST"] = 0
        catalog["disposition_counts"]["EXCLUDE"] = 2
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        report = self._run(tmp_path, catalog_path)
        assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 0

    def test_two_objects_of_the_same_content_but_distinct_categories(
        self, tmp_path: Path
    ) -> None:
        """Les deux catégories doivent être couvertes — dédupliquer par
        contenu ferait disparaître la seconde.

        Testé au niveau de la couche sémantique : au niveau du gate, la
        liaison manifeste (F5) refuserait d'abord le second objet, ce qui
        masquerait précisément la règle mesurée ici."""
        artifact = ScopeAuthorizationArtifactV2.model_validate(
            _valid_authority_document()
        )
        candidates = (
            (CONTENT_SHA256, "officiel_public"),
            (CONTENT_SHA256, "nexus_proprietaire"),
        )
        with pytest.raises(ValueError, match="nexus_proprietaire"):
            module._authority_semantic_validation(
                artifact,
                manifest_sha256=artifact.manifest_digest,
                ingest_content_sha256=frozenset({CONTENT_SHA256}),
                ingest_rights_candidates=candidates,
                now=AUTHORITY_NOW,
                revoked_authorization_ids=frozenset(),
            )

    def test_the_same_pair_twice_stays_acceptable(self, tmp_path: Path) -> None:
        """Garde-fou de sensibilité : c'est la *catégorie non couverte* qui
        refuse, pas la simple présence de deux entrées."""
        artifact = ScopeAuthorizationArtifactV2.model_validate(
            _valid_authority_document()
        )
        module._authority_semantic_validation(
            artifact,
            manifest_sha256=artifact.manifest_digest,
            ingest_content_sha256=frozenset({CONTENT_SHA256}),
            ingest_rights_candidates=(
                (CONTENT_SHA256, "officiel_public"),
                (CONTENT_SHA256, "officiel_public"),
            ),
            now=AUTHORITY_NOW,
            revoked_authorization_ids=frozenset(),
        )


class TestTheGovernedRootIsADeploymentContract:
    """F1, volet déploiement.

    La racine gouvernée est dérivée par remontée depuis l'emplacement du
    module. Cette dérivation n'a de sens que dans un checkout : le paquet
    ``rag-pedago`` n'embarque que des packages Python, et ``governance/``
    vit à la racine du dépôt, hors de tout wheel. Le gate doit donc
    refuser bruyamment plutôt que faire autorité sur un répertoire
    quelconque de ``site-packages``.
    """

    def test_the_real_governed_root_is_the_repository_checkout(self) -> None:
        root = module._GOVERNED_REPOSITORY_ROOT
        for marker in module._GOVERNED_ROOT_MARKERS:
            assert (root / marker).exists(), f"{marker} missing from {root}"

    def test_the_governed_paths_are_the_canonical_ones(self) -> None:
        assert (
            module._GOVERNED_TRUST_ANCHOR_PATH
            == "governance/trust-anchors/review-binding-v1.json"
        )
        assert (
            module._GOVERNED_REVOCATIONS_PATH
            == "governance/trust-anchors/authorization-revocations-v1.json"
        )

    def test_the_repository_ships_exactly_the_provisioned_review_binding_anchor(
        self,
    ) -> None:
        """H2-B: the review-binding trust anchor (ADR-0035, distinct key
        from the production-readiness anchor of PR #97) is now
        provisioned, discovered by content (protocol_version) rather than
        filename, at the exact governed path this module resolves — never
        a path recomputed independently that could diverge. Sensitivity
        canary, same discipline as the production-readiness anchor: fails
        red on zero or ambiguous matches, never silently accepts either."""
        root = module._GOVERNED_REPOSITORY_ROOT
        governance_dir = root / "governance"
        candidates = []
        for path in sorted(governance_dir.rglob("*.json")):
            try:
                document = json.loads(path.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(document, dict)
                and document.get("protocol_version") == "NEXUS-REVIEW-BINDING-V1"
            ):
                candidates.append(path)
        assert len(candidates) == 1, (
            f"expected exactly one review-binding trust anchor under "
            f"{governance_dir}, found {[str(p) for p in candidates]}"
        )
        expected_path = root / module._GOVERNED_TRUST_ANCHOR_PATH
        assert candidates[0] == expected_path, (
            f"the anchor discovered by content ({candidates[0]}) is not at the "
            f"path this module resolves ({expected_path}) — F1 would never "
            "find it"
        )

        anchor = parse_trust_anchor(expected_path.read_bytes())
        for key in anchor.keys:
            assert key.environment == "production", (
                f"{expected_path} declares key_id {key.key_id!r} for "
                f"environment {key.environment!r} — a rehearsal/test key must "
                "never live at the governed production path"
            )
        # Distinct from the production-readiness key (PR #97) by construction:
        # different protocol_version means this loop never even sees that key.

    def test_the_repository_ships_the_governed_revocation_registry(self) -> None:
        """F2: the governed 'no revocations known' registry is provisioned
        (empty, not absent — REVOCATION_REGISTRY_MISSING is exactly the
        failure this distinguishes from). Parsed through the real
        production parser, not hand-checked."""
        root = module._GOVERNED_REPOSITORY_ROOT
        path = root / module._GOVERNED_REVOCATIONS_PATH
        assert path.is_file(), f"governed revocation registry missing at {path}"
        revoked = module._parse_revocation_registry(path.read_bytes(), origin=path)
        assert revoked == frozenset(), (
            "the governed registry is expected to start empty — a real "
            "revocation appearing here without this test being deliberately "
            "updated would be a silent authority change"
        )

    def test_the_trusted_reviewer_allowlist_is_governed_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F1, second point d'application : ce fichier décide *qui* compte
        comme relecteur habilité. Le laisser dépendre d'une racine
        redirigeable serait le même défaut, à un autre endroit."""
        root = _install_governed_root(monkeypatch, tmp_path)
        (root / module._TRUSTED_REVIEWERS_CONFIG).unlink()
        with pytest.raises(ValueError, match="trusted reviewer configuration"):
            _generate_with_binding(tmp_path, environment="production")

    def test_a_redirected_repository_root_cannot_swap_the_reviewers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un attaquant qui pointerait ``NEXUS_REPOSITORY_ROOT`` vers un
        dépôt portant sa propre allowlist ne gagne rien : en production, ce
        chemin n'est jamais consulté."""
        _install_governed_root(monkeypatch, tmp_path)
        impostor = tmp_path / "impostor_repo"
        (impostor / "scripts" / "github").mkdir(parents=True)
        (impostor / module._TRUSTED_REVIEWERS_CONFIG).write_text(
            json.dumps(
                {
                    "protocol": TRUSTED_REVIEW_PROTOCOL,
                    "repository": REPOSITORY,
                    "base_ref": "main",
                    "reviewers": ["attacker"],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(module, "_REPOSITORY_ROOT", impostor)
        report = _generate_with_binding(tmp_path, environment="production")
        assert report.input_files["authority_review_reviewer"] == TRUSTED_REVIEWER

    def test_a_root_without_the_repository_markers_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simule exactement l'installation en wheel : le calcul de racine
        aboutit dans un répertoire qui n'est pas le dépôt."""
        stray = tmp_path / "site-packages-ish"
        (stray / "governance" / "trust-anchors").mkdir(parents=True)
        (stray / module._GOVERNED_TRUST_ANCHOR_PATH).write_text("{}", encoding="utf-8")
        monkeypatch.setattr(module, "_GOVERNED_REPOSITORY_ROOT", stray)
        with pytest.raises(ValueError, match="does not look like the Nexus repository"):
            _generate_with_binding(tmp_path, environment="production")


class TestGovernedRevocationRegistry:
    """F2 — la non-révocation est prouvée, jamais supposée."""

    def test_an_absent_governed_registry_refuses_in_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, write_revocations=False)
        with pytest.raises(ValueError, match="REVOCATION_REGISTRY_MISSING"):
            _generate_with_binding(tmp_path, environment="production")

    def test_a_caller_supplied_registry_is_refused_in_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path)
        external = _write_revocations(tmp_path / "external.json", [])
        with pytest.raises(ValueError, match="REVOCATION_REGISTRY_ARGUMENT_FORBIDDEN"):
            _generate_with_authority(
                tmp_path,
                authority_path=_write_authority(
                    tmp_path / "authority.json", _valid_authority_document()
                ),
                revocations_path=external,
                environment="production",
            )

    def test_an_empty_governed_registry_is_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """« Rien n'est révoqué » est une affirmation légitime — c'est
        l'absence de fichier qui ne l'est pas."""
        _install_governed_root(monkeypatch, tmp_path, revoked=[])
        report = _generate_with_binding(tmp_path, environment="production")
        assert report.authority_revocations_checked is True

    def test_a_revoked_authorization_is_refused_from_the_governed_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(
            monkeypatch, tmp_path, revoked=[_valid_authority_document()["authorization_id"]]
        )
        with pytest.raises(ValueError, match="revocation registry"):
            _generate_with_binding(tmp_path, environment="production")

    def test_a_registry_without_protocol_version_is_refused(
        self, tmp_path: Path
    ) -> None:
        registry = tmp_path / "revocations.json"
        registry.write_text(
            json.dumps({"revoked_authorization_ids": []}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="REVOCATION_REGISTRY_INVALID.*protocol_version"):
            _generate_with_authority(
                tmp_path,
                authority_path=_write_authority(
                    tmp_path / "authority.json", _valid_authority_document()
                ),
                revocations_path=registry,
            )

    def test_a_registry_with_duplicate_ids_is_refused(self, tmp_path: Path) -> None:
        registry = _write_revocations(
            tmp_path / "revocations.json", ["dup-authorization", "dup-authorization"]
        )
        with pytest.raises(ValueError, match="REVOCATION_REGISTRY_INVALID.*repeats"):
            _generate_with_authority(
                tmp_path,
                authority_path=_write_authority(
                    tmp_path / "authority.json", _valid_authority_document()
                ),
                revocations_path=registry,
            )

    def test_a_registry_with_unknown_keys_is_refused(self, tmp_path: Path) -> None:
        registry = tmp_path / "revocations.json"
        registry.write_text(
            json.dumps(
                {
                    "protocol_version": module._REVOCATIONS_PROTOCOL_VERSION,
                    "revoked_authorization_ids": [],
                    "trusted": True,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="REVOCATION_REGISTRY_INVALID.*unknown keys"):
            _generate_with_authority(
                tmp_path,
                authority_path=_write_authority(
                    tmp_path / "authority.json", _valid_authority_document()
                ),
                revocations_path=registry,
            )

    def test_a_rehearsal_run_without_registry_reports_unchecked(
        self, tmp_path: Path
    ) -> None:
        report = _generate_with_binding(tmp_path)
        assert report.authority_revocations_checked is False
        assert report.coverage_complete is False

    def test_the_report_renders_the_revocation_evidence_field(
        self, tmp_path: Path
    ) -> None:
        report = _generate_with_binding(tmp_path)
        markdown = render_markdown(report)
        assert "AUTHORITY_REVOCATIONS_CHECKED=false" in markdown
        assert "Authority revocations checked (F2)" in markdown


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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        authority = _valid_authority_document()
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        # F1 : l'ancre de production est gouvernée. On installe donc une
        # racine gouvernée dont la clé se déclare ``test`` — le refus doit
        # venir de l'environnement de la clé, pas de l'absence d'ancre.
        _install_governed_root(monkeypatch, tmp_path, anchor_environment="test")
        with pytest.raises(ValueError, match="'test' environment"):
            _generate_with_authority(
                tmp_path,
                authority_path=authority_path,
                binding_path=_write_review_binding(tmp_path, authority),
                environment="production",
            )

    def test_an_invalid_environment_is_refused(self, tmp_path: Path) -> None:
        authority = _valid_authority_document()
        authority_path = _write_authority(tmp_path / "authority.json", authority)
        with pytest.raises(ValueError, match="authority_environment must be"):
            _generate_with_authority(
                tmp_path, authority_path=authority_path, environment="whatever"
            )


def _sole_production_readiness_anchor(governance_dir: Path) -> Path:
    """Découvre et valide l'unique ancre de production sous ``governance_dir``.

    Remédiation Codex (PR #97, P2) : l'ancien canari cherchait un nom de
    fichier (``*trust*anchor*.json``, appliqué au basename) — un fichier
    nommé ``production-readiness-v1.json`` dans un répertoire
    ``trust-anchors/`` ne matchait pas, donc le canari restait vert en
    prétendant qu'aucune ancre n'existait alors qu'une l'avait déjà été
    commitée. Cette fonction discrimine par **contenu**
    (``protocol_version``), jamais par nom : une ancre de review-binding
    (``ScopeAuthorizationReviewBindingV1``/``REVIEW_BINDING_PROTOCOL_VERSION``,
    chemin gouverné distinct ``governance/trust-anchors/review-binding-v1.json``)
    ne doit jamais compter comme une ancre de production ambiguë, et
    inversement aucun renommage de fichier ne peut faire disparaître une
    vraie ancre de production à ce contrôle.

    Fail-closed sur toute forme inattendue : zéro ancre, plusieurs ancres,
    JSON invalide, ou parsing refusé par
    ``parse_production_readiness_trust_anchor`` (protocole, clé_id,
    clé publique, champs inconnus — cf. ``StrictBaseModel``) font toutes
    échouer l'appelant, jamais un défaut permissif."""
    from nexus_contracts.production_readiness import (
        PRODUCTION_READINESS_PROTOCOL_VERSION,
        parse_production_readiness_trust_anchor,
    )

    candidates: list[Path] = []
    if governance_dir.is_dir():
        for path in sorted(governance_dir.rglob("*.json")):
            try:
                document = json.loads(path.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(document, dict)
                and document.get("protocol_version") == PRODUCTION_READINESS_PROTOCOL_VERSION
            ):
                candidates.append(path)

    assert len(candidates) == 1, (
        f"expected exactly one production readiness trust anchor under "
        f"{governance_dir}, found {[str(p) for p in candidates]} — zero means "
        "the anchor is missing (PRODUCTION_TRUST_ANCHOR_PROVISIONED=false), "
        "more than one means an ambiguous set of production signers"
    )
    anchor_path = candidates[0]
    # Parse strict : protocole exact, key_id/clé publique/algorithme valides,
    # aucun champ inconnu (donc jamais de clé privée glissée dans le
    # document) — refuse fermé sur toute forme malformée.
    anchor = parse_production_readiness_trust_anchor(anchor_path.read_bytes())
    for key in anchor.keys:
        assert key.environment == "production", (
            f"{anchor_path} declares key_id {key.key_id!r} for environment "
            f"{key.environment!r} — a rehearsal/test key must never live at "
            "the governed production path"
        )
    return anchor_path


#: Verrou de gouvernance. Cette valeur appartient au gate de production
#: readiness de ``rag-engine`` (``readiness_gate.GOVERNED_TRUST_ANCHOR_PATH``)
#: et est répétée ici **délibérément** : ``rag-pedago`` n'importe jamais
#: ``rag-engine`` (AGENTS.md, ADR-0001) — un `ModuleNotFoundError: No module
#: named 'ingestor'` en CI (job ``services/rag-pedago``, isolé de
#: ``services/rag-engine``) l'a confirmé concrètement. Même motif déjà
#: établi pour ``REVIEW_BINDING_ANCHOR_PATH`` dans
#: ``rag-engine/tests/test_readiness_gate.py``. Si l'un des deux chemins
#: change, ce test doit être relu — c'est précisément son rôle.
_PRODUCTION_READINESS_GOVERNED_PATH = "governance/trust-anchors/production-readiness-v1.json"


def test_the_repository_ships_exactly_the_provisioned_production_trust_anchor() -> None:
    """H2-B Phase D : l'ancre de production readiness est désormais
    provisionnée, réellement découverte au même chemin gouverné que le
    mécanisme de production (``readiness_gate.GOVERNED_TRUST_ANCHOR_PATH``,
    répété ci-dessus faute d'import interservice licite), jamais un chemin
    recalculé indépendamment qui pourrait diverger."""
    from rag_pedago.imports.h2b_coverage_report import _REPOSITORY_ROOT

    expected_path = _REPOSITORY_ROOT / _PRODUCTION_READINESS_GOVERNED_PATH
    discovered = _sole_production_readiness_anchor(_REPOSITORY_ROOT / "governance")
    assert discovered == expected_path, (
        f"the anchor discovered by content ({discovered}) is not at the path "
        f"the real production gate resolves ({expected_path}) — the gate "
        "would never find it"
    )


class TestProductionTrustAnchorSensitivityCanaries:
    """Preuve, par mutation, que ``_sole_production_readiness_anchor``
    refuse effectivement chacune des dérives qu'elle prétend détecter —
    même discipline que le reste du dépôt (ADR-0031, décision 6) : un test
    qui ne passe que sur du code déjà correct ne prouve rien."""

    @staticmethod
    def _seed(tmp_path: Path) -> Path:
        governance = tmp_path / "governance" / "trust-anchors"
        governance.mkdir(parents=True)
        real_anchor = (
            Path(__file__).resolve().parents[3]
            / "governance"
            / "trust-anchors"
            / "production-readiness-v1.json"
        )
        (governance / "production-readiness-v1.json").write_bytes(real_anchor.read_bytes())
        return tmp_path / "governance"

    def test_a_correctly_seeded_directory_passes(self, tmp_path: Path) -> None:
        governance_dir = self._seed(tmp_path)
        anchor_path = _sole_production_readiness_anchor(governance_dir)
        assert anchor_path == governance_dir / "trust-anchors" / "production-readiness-v1.json"

    def test_anchor_removed_fails_closed(self, tmp_path: Path) -> None:
        governance_dir = self._seed(tmp_path)
        (governance_dir / "trust-anchors" / "production-readiness-v1.json").unlink()
        with pytest.raises(AssertionError, match="found \\[\\]"):
            _sole_production_readiness_anchor(governance_dir)

    def test_a_second_ambiguous_production_anchor_fails_closed(self, tmp_path: Path) -> None:
        governance_dir = self._seed(tmp_path)
        original = governance_dir / "trust-anchors" / "production-readiness-v1.json"
        # Nom de fichier différent, mais même contenu/protocole : la
        # détection par contenu doit refuser, contrairement à l'ancien
        # glob qui n'aurait regardé que le nom.
        duplicate = governance_dir / "trust-anchors" / "a-second-signer.json"
        duplicate.write_bytes(original.read_bytes())
        with pytest.raises(AssertionError, match="found"):
            _sole_production_readiness_anchor(governance_dir)

    def test_protocol_drift_fails_closed(self, tmp_path: Path) -> None:
        governance_dir = self._seed(tmp_path)
        anchor_path = governance_dir / "trust-anchors" / "production-readiness-v1.json"
        document = json.loads(anchor_path.read_text())
        document["protocol_version"] = "NEXUS-PRODUCTION-READINESS-V2"
        anchor_path.write_text(json.dumps(document))
        with pytest.raises(AssertionError, match="found \\[\\]"):
            _sole_production_readiness_anchor(governance_dir)

    def test_a_malformed_public_key_fails_closed(self, tmp_path: Path) -> None:
        governance_dir = self._seed(tmp_path)
        anchor_path = governance_dir / "trust-anchors" / "production-readiness-v1.json"
        document = json.loads(anchor_path.read_text())
        document["keys"][0]["public_key"] = "not-a-valid-hex-key"
        anchor_path.write_text(json.dumps(document))
        with pytest.raises(Exception):  # noqa: B017, PT011 - CanonicalArtifactError/ValidationError, contrat non importé ici
            _sole_production_readiness_anchor(governance_dir)

    def test_a_non_production_environment_key_fails_closed(self, tmp_path: Path) -> None:
        governance_dir = self._seed(tmp_path)
        anchor_path = governance_dir / "trust-anchors" / "production-readiness-v1.json"
        document = json.loads(anchor_path.read_text())
        document["keys"][0]["environment"] = "test"
        anchor_path.write_text(json.dumps(document))
        with pytest.raises(AssertionError, match="must never live at"):
            _sole_production_readiness_anchor(governance_dir)
