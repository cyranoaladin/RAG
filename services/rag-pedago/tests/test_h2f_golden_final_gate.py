"""Non-vacuity tests for the H2-F real sealed-corpus golden gate."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from nexus_contracts import ScopeAuthorizationArtifactV2
from nexus_contracts.authority_artifacts import canonical_authorization_path, git_blob_sha1
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    TRUSTED_REVIEW_PROTOCOL,
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    public_key_hex,
    sign_review_binding,
)

from rag_pedago.imports import h2b_coverage_report as module
from rag_pedago.imports.golden_corpus_validator import validate_golden_corpus
from rag_pedago.imports.h2b_coverage_report import (
    generate_coverage_report,
    main,
    render_markdown,
)


def _sha(index: int) -> str:
    return hashlib.sha256(str(index).encode()).hexdigest()


# P1: Manifest content must match catalog entries; compute SHA256 at module load
def _manifest_content() -> str:
    """Build manifest content from catalog entries (excluding self-object)."""
    lines = [
        f"{_sha(1)}  01_EDUSCOL_OFFICIEL/LYCEE/10_ACTUEL_CONFIRME/PHILOSOPHIE/a.pdf",
        f"{_sha(2)}  01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/b.pdf",
        f"{_sha(3)}  01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/c.pdf",
        f"{_sha(4)}  03_RESSOURCES_INTERACTIVES/a.ggb",
        f"{_sha(5)}  03_RESSOURCES_INTERACTIVES/b.ggb",
    ]
    return "\n".join(lines) + "\n"


_MANIFEST_CONTENT = _manifest_content()
MANIFEST_SHA256 = hashlib.sha256(_MANIFEST_CONTENT.encode()).hexdigest()


def _object(
    index: int,
    *,
    path: str,
    base: str,
    final: str,
    currentness: str | None,
    gates: dict[str, str] | None = None,
    content_sha256_override: str | None = None,
) -> dict[str, object]:
    return {
        "content_sha256": content_sha256_override or _sha(index),
        "path": path,
        "base_disposition": base,
        "disposition": final,
        "currentness": currentness,
        "gate_statuses": gates or {},
        "provenance_status": "VERIFIED",
        "attribution_metadata": {
            "source": path.split("/", maxsplit=1)[0],
            "source_reference": path,
        },
    }


def _catalog() -> dict[str, object]:
    objects = [
        _object(
            1,
            path="01_EDUSCOL_OFFICIEL/LYCEE/10_ACTUEL_CONFIRME/PHILOSOPHIE/a.pdf",
            base="INGEST",
            final="REVIEW_REQUIRED",
            currentness="actuel",
            gates={
                "rights": "PASS",
                "pii": "PASS",
                "authority": "BLOCKED_NOT_CLEARED",
            },
        ),
        _object(
            2,
            path="01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/b.pdf",
            base="REVIEW_REQUIRED",
            final="REVIEW_REQUIRED",
            currentness="a_verifier",
        ),
        _object(
            3,
            path="01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/c.pdf",
            base="REVIEW_REQUIRED",
            final="REVIEW_REQUIRED",
            currentness="a_verifier",
        ),
        _object(
            4,
            path="03_RESSOURCES_INTERACTIVES/a.ggb",
            base="UNSUPPORTED",
            final="UNSUPPORTED",
            currentness=None,
        ),
        _object(
            5,
            path="03_RESSOURCES_INTERACTIVES/b.ggb",
            base="UNSUPPORTED",
            final="UNSUPPORTED",
            currentness=None,
        ),
        _object(
            6,
            path="00_ADMIN/SHA256SUMS.txt",
            base="EXCLUDE",
            final="EXCLUDE",
            currentness=None,
            content_sha256_override=MANIFEST_SHA256,  # P1: Self-object must match manifest
        ),
    ]
    counts: dict[str, int] = {}
    for item in objects:
        disposition = str(item["disposition"])
        counts[disposition] = counts.get(disposition, 0) + 1
    return {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA256,
        "physical_object_count": len(objects),
        "disposition_counts": counts,
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "physical_objects": objects,
    }


def _refresh_catalog_summary(catalog: dict[str, object]) -> None:
    objects = catalog["physical_objects"]
    counts: dict[str, int] = {}
    for item in objects:  # type: ignore[union-attr]
        disposition = str(item["disposition"])
        counts[disposition] = counts.get(disposition, 0) + 1
    catalog["physical_object_count"] = len(objects)  # type: ignore[arg-type]
    catalog["disposition_counts"] = counts


def _spec() -> dict[str, object]:
    return {
        "spec_id": "golden_h2f_test_v2",
        "catalog_kind_required": "REAL_SEALED_CORPUS",
        "positive_controls": [
            {
                "control_id": "pos_01",
                "sha256_prefix": _sha(1)[:12],
                "expected_base_disposition": "INGEST",
                "expected_final_disposition": "REVIEW_REQUIRED",
                "expected_currentness": "actuel",
                "expected_gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
            }
        ],
        "boundary_controls": [
            {
                "control_id": "bnd_01",
                "zone": "01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/",
                "expected_count_in_zone": 2,
                "expected_disposition": "REVIEW_REQUIRED",
                "expected_currentness": "a_verifier",
            }
        ],
        "negative_controls": [
            {
                "control_id": "neg_01",
                "path": "00_ADMIN/SHA256SUMS.txt",
                "expected_count": 1,
                "expected_disposition": "EXCLUDE",
            },
            {
                "control_id": "neg_02",
                "zone": "03_RESSOURCES_INTERACTIVES/",
                "expected_count_in_zone": 2,
                "expected_disposition": "UNSUPPORTED",
            },
        ],
        "descriptive_assertions": {
            "authoritative": False,
            "reason": "Human-readable summary only; controls above are executable.",
            "items": [{"assertion_id": "summary_only"}],
        },
        "coverage_summary": {
            "total_controls": 4,
            "positive_controls": 1,
            "boundary_controls": 1,
            "negative_controls": 2,
        },
    }


def _write_inputs(
    tmp_path: Path,
    *,
    catalog: dict[str, object] | None = None,
    spec: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    catalog_path = tmp_path / "real-catalog.json"
    spec_path = tmp_path / "golden.yml"
    catalog_path.write_text(
        json.dumps(catalog or _catalog(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    spec_path.write_text(
        yaml.safe_dump(spec or _spec(), sort_keys=False),
        encoding="utf-8",
    )
    return catalog_path, spec_path


def _write_external_evidence(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Write external evidence files including manifest.

    Returns (routing_path, rights_path, pii_path, manifest_path).
    """
    # P1: Create manifest file first
    manifest_path = tmp_path / "00_ADMIN" / "SHA256SUMS.txt"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_MANIFEST_CONTENT, encoding="utf-8")

    routing = {
        "config_id": "h2f-routing-v1",
        "manifest_sha256": MANIFEST_SHA256,
        "rights_evidence_perimeter": [
            "00_ADMIN/",
            "01_EDUSCOL_OFFICIEL/",
            "03_RESSOURCES_INTERACTIVES/",
        ],
        "zone_rules": [
            {
                "zone_prefix": "00_ADMIN/",
                "disposition": "EXCLUDE",
                "reason": "admin",
            },
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "sub_zone_routing": [
                    {
                        "sub_zone_suffix": "/10_ACTUEL_CONFIRME/",
                        "disposition": "INGEST",
                        "currentness": "actuel",
                    },
                    {
                        "sub_zone_suffix": None,
                        "disposition": "REVIEW_REQUIRED",
                        "currentness": "unclassified",
                    },
                ],
            },
            {
                "zone_prefix": "03_RESSOURCES_INTERACTIVES/",
                "disposition": "UNSUPPORTED",
                "reason": "format",
            },
        ],
    }
    rights = {
        "registry_id": "h2f-rights-v1",
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
            "interactive": {
                "zone": "03_RESSOURCES_INTERACTIVES/",
                "rights_status": "UNSUPPORTED",
                "disposition_override": "UNSUPPORTED",
            },
        },
        "summary": {"total_zones": 3},
    }
    required_path = (
        "01_EDUSCOL_OFFICIEL/LYCEE/10_ACTUEL_CONFIRME/PHILOSOPHIE/a.pdf"
    )
    pii = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "scanner_version": "h2f-scanner-v1",
        "scanner_sha256": "1" * 64,
        "policy_version": "h2f-policy-v1",
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
            "pii_scan_scope": "INITIAL_PRODUCTION_ELIGIBLE_PDFS",
            "pii_scan_required": 1,
            "pii_scan_exempt": 2,
        },
        "results": [
            {
                "content_sha256": _sha(1),
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
    return routing_path, rights_path, pii_path, manifest_path


#: ADR-0035 — clé Ed25519 de test, engendrée dans ``tmp_path``, jamais
#: commitée. Le dépôt ne contient aucune ancre de production.
TEST_SIGNING_SEED = "66" * 32
TEST_KEY_ID = "nexus-governance-test-1"
AUTHORITY_ID = "h2f_golden_authority_v1"
AUTHORITY_NOW = datetime(2026, 6, 1, tzinfo=UTC)
REPOSITORY = "cyranoaladin/RAG"
TRUSTED_REVIEWER = "abenrhouma"
PR_AUTHOR = "cyranoaladin"
PULL_REQUEST = 95
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40


def _authority_document() -> dict[str, object]:
    """Autorisation minimale mais complète. Le catalogue golden ne route
    aucun objet vers l'ingestion : l'allowlist n'a donc rien à couvrir, mais
    le gate final exige quand même une autorité revue — c'est précisément
    ce que ce lot corrige (auparavant, zéro objet INGEST suffisait à passer
    sans la moindre preuve d'autorité)."""
    return {
        "protocol_version": "LOT41A-V2",
        "authorization_id": AUTHORITY_ID,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": MANIFEST_SHA256,
        "profile_id": "h2f_golden_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review: no PII found",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [_sha(1)],
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


def _write_authority_chain(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Écrit l'autorisation canonique, son reçu de revue signé et l'ancre."""
    document = _authority_document()
    artifact = ScopeAuthorizationArtifactV2.model_validate(document)
    raw = artifact.canonical_bytes()
    authority_path = tmp_path / "authority.json"
    authority_path.write_bytes(raw)

    binding = ScopeAuthorizationReviewBindingV1.model_validate({
        "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST,
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "authorization_artifact_path": canonical_authorization_path(AUTHORITY_ID),
        "authorization_artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(raw),
        "authorization_id": AUTHORITY_ID,
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
    })
    binding_path = tmp_path / "review_binding.json"
    binding_path.write_bytes(
        sign_review_binding(
            binding, private_key_hex=TEST_SIGNING_SEED, key_id=TEST_KEY_ID
        ).canonical_bytes()
    )

    return authority_path, binding_path


def _install_governed_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """ADR-0035 F1/F2 : ancre et registre viennent des chemins gouvernés.

    Écrire une ancre de fixture qui se déclare ``environment="production"``
    et la passer en argument était précisément le défaut F1 : l'appelant
    choisissait quelles clés étaient dignes de confiance. Le mode
    production ne lit plus que la racine dérivée du code."""
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
    (root / module._GOVERNED_TRUST_ANCHOR_PATH).write_text(
        json.dumps({
            "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
            "keys": [{
                "key_id": TEST_KEY_ID,
                "algorithm": "ed25519",
                "public_key": public_key_hex(TEST_SIGNING_SEED),
                "environment": "production",
            }],
        }),
        encoding="utf-8",
    )
    (root / module._GOVERNED_REVOCATIONS_PATH).write_text(
        json.dumps({
            "protocol_version": module._REVOCATIONS_PROTOCOL_VERSION,
            "revoked_authorization_ids": [],
        }),
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


def _coverage(
    tmp_path: Path,
    catalog_path: Path,
    spec_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    routing_path, rights_path, pii_path, manifest_path = _write_external_evidence(tmp_path)
    authority_path, binding_path = _write_authority_chain(tmp_path)
    _install_governed_root(monkeypatch, tmp_path)
    return generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=spec_path,
        manifest_path=manifest_path,
        authority_path=authority_path,
        authority_review_binding_path=binding_path,
        authority_environment="production",
        authority_now=AUTHORITY_NOW,
        expected_total=6,
        expected_manifest_sha256=MANIFEST_SHA256,
    )


def _validate(
    tmp_path: Path,
    *,
    catalog: dict[str, object] | None = None,
    spec: dict[str, object] | None = None,
):
    catalog_path, spec_path = _write_inputs(
        tmp_path,
        catalog=catalog,
        spec=spec,
    )
    return validate_golden_corpus(
        spec or _spec(),
        catalog or _catalog(),
        spec_path,
        catalog_path,
    )


def test_real_sealed_baseline_is_green_and_bound_to_full_digests(
    tmp_path: Path,
) -> None:
    report = _validate(tmp_path)

    assert report.validation_passed is True
    assert report.total_controls == 4
    assert report.passed_controls == 4
    assert report.failed_controls == 0
    assert report.objects_evaluated == 6
    assert len(report.catalog_sha256) == 64
    assert len(report.spec_sha256) == 64
    assert report.catalog_manifest_sha256 == MANIFEST_SHA256
    assert len(report.git_head) == 40
    machine = report.to_dict()
    assert machine["golden_controls_total"] == 4
    assert machine["golden_controls_passed"] == 4
    assert machine["golden_controls_failed"] == 0
    assert machine["golden_validation_passed"] is True
    assert machine["positive_controls_total"] == 1
    assert machine["boundary_controls_total"] == 1
    assert machine["negative_controls_total"] == 2
    assert machine["objects_evaluated"] == 6


def test_final_gate_rejects_legacy_objects_schema(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["objects"] = catalog.pop("physical_objects")

    with pytest.raises(ValueError, match="physical_objects"):
        _validate(tmp_path, catalog=catalog)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("content_sha256", "not-a-sha", "content_sha256"),
        ("provenance_status", None, "provenance_status"),
        ("attribution_metadata", {}, "attribution_metadata"),
        ("gate_statuses", None, "gate_statuses"),
    ],
)
def test_final_gate_rejects_malformed_real_object(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    catalog = _catalog()
    catalog["physical_objects"][0][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        _validate(tmp_path, catalog=catalog)


def test_final_gate_rejects_missing_currentness_field(tmp_path: Path) -> None:
    catalog = _catalog()
    del catalog["physical_objects"][0]["currentness"]  # type: ignore[index]

    with pytest.raises(ValueError, match="currentness field is missing"):
        _validate(tmp_path, catalog=catalog)


def test_final_gate_rejects_duplicate_control_ids(tmp_path: Path) -> None:
    spec = _spec()
    spec["negative_controls"][0]["control_id"] = "pos_01"  # type: ignore[index]

    with pytest.raises(ValueError, match="control_id values must be unique"):
        _validate(tmp_path, spec=spec)


def test_final_gate_rejects_empty_executable_perimeter(tmp_path: Path) -> None:
    spec = _spec()
    spec["positive_controls"] = []
    spec["boundary_controls"] = []
    spec["negative_controls"] = []
    spec["coverage_summary"] = {
        "total_controls": 0,
        "positive_controls": 0,
        "boundary_controls": 0,
        "negative_controls": 0,
    }

    with pytest.raises(ValueError, match="at least one executable control"):
        _validate(tmp_path, spec=spec)


def test_positive_control_requires_unique_sha_prefix(tmp_path: Path) -> None:
    spec = _spec()
    spec["positive_controls"][0]["sha256_prefix"] = ""  # type: ignore[index]
    with pytest.raises(ValueError, match="non-empty SHA256 prefix"):
        _validate(tmp_path, spec=spec)

    spec = _spec()
    spec["positive_controls"][0]["sha256_prefix"] = "f" * 12  # type: ignore[index]
    report = _validate(tmp_path, spec=spec)
    assert report.validation_passed is False
    assert "zero objects" in report.control_results[0].failure_reason

    catalog = _catalog()
    first_sha = catalog["physical_objects"][0]["content_sha256"]  # type: ignore[index]
    catalog["physical_objects"][1]["content_sha256"] = (  # type: ignore[index]
        first_sha[:-1] + ("0" if first_sha[-1] != "0" else "1")
    )
    spec = _spec()
    spec["positive_controls"][0]["sha256_prefix"] = _sha(1)[:10]  # type: ignore[index]
    report = _validate(tmp_path, catalog=catalog, spec=spec)
    assert report.validation_passed is False
    assert "ambiguous" in report.control_results[0].failure_reason


def test_currentness_never_shortcuts_wrong_positive_disposition(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["physical_objects"][0]["base_disposition"] = "REVIEW_REQUIRED"  # type: ignore[index]

    report = _validate(tmp_path, catalog=catalog)

    assert report.validation_passed is False
    assert report.control_results[0].actual_base_disposition == "REVIEW_REQUIRED"


def test_positive_final_disposition_mutation_is_detected(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["physical_objects"][0]["disposition"] = "INGEST"  # type: ignore[index]

    report = _validate(tmp_path, catalog=catalog)

    assert report.validation_passed is False
    assert report.control_results[0].actual_disposition == "INGEST"


@pytest.mark.parametrize(
    ("mutation", "expected_actual"),
    [
        ("wrong_disposition", 2),
        ("remove", 1),
        ("add", 3),
    ],
)
def test_boundary_control_is_exhaustive_and_count_bound(
    tmp_path: Path,
    mutation: str,
    expected_actual: int,
) -> None:
    catalog = _catalog()
    objects = catalog["physical_objects"]
    if mutation == "wrong_disposition":
        objects[2]["disposition"] = "INGEST"  # type: ignore[index]
    elif mutation == "remove":
        objects.pop(2)  # type: ignore[union-attr]
    else:
        objects.append(  # type: ignore[union-attr]
            _object(
                7,
                path="01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/extra.pdf",
                base="REVIEW_REQUIRED",
                final="REVIEW_REQUIRED",
                currentness="a_verifier",
            )
        )
    _refresh_catalog_summary(catalog)

    report = _validate(tmp_path, catalog=catalog)
    boundary = report.control_results[1]
    assert boundary.passed is False
    assert boundary.actual_count == expected_actual
    if mutation == "wrong_disposition":
        assert boundary.mismatching_count == 1


def test_archive_boundary_disposition_mutation_is_detected(tmp_path: Path) -> None:
    catalog = _catalog()
    objects = catalog["physical_objects"]
    objects[1]["path"] = "01_EDUSCOL_OFFICIEL/90_ARCHIVE_CATALOGUE/b.pdf"  # type: ignore[index]
    objects[1]["base_disposition"] = "ARCHIVE_ONLY"  # type: ignore[index]
    objects[1]["disposition"] = "REVIEW_REQUIRED"  # type: ignore[index]
    objects[1]["currentness"] = "archive"  # type: ignore[index]
    spec = _spec()
    spec["boundary_controls"][0] = {  # type: ignore[index]
        "control_id": "bnd_archive",
        "zone": "01_EDUSCOL_OFFICIEL/90_ARCHIVE_CATALOGUE/",
        "expected_count_in_zone": 1,
        "expected_disposition": "ARCHIVE_ONLY",
        "expected_currentness": "archive",
    }
    _refresh_catalog_summary(catalog)

    report = _validate(tmp_path, catalog=catalog, spec=spec)

    assert report.validation_passed is False
    assert report.control_results[1].actual_count == 1
    assert report.control_results[1].mismatching_count == 1


def test_negative_absence_and_one_wrong_match_fail_closed(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["physical_objects"] = [  # type: ignore[index]
        item
        for item in catalog["physical_objects"]  # type: ignore[union-attr]
        if item["path"] != "00_ADMIN/SHA256SUMS.txt"
    ]
    _refresh_catalog_summary(catalog)
    report = _validate(tmp_path, catalog=catalog)
    assert report.control_results[2].passed is False
    assert report.control_results[2].actual_count == 0

    catalog = _catalog()
    catalog["physical_objects"][4]["disposition"] = "INGEST"  # type: ignore[index]
    report = _validate(tmp_path, catalog=catalog)
    assert report.control_results[3].passed is False
    assert report.control_results[3].mismatching_count == 1


def test_coverage_gate_executes_golden_and_separates_decision_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path, spec_path = _write_inputs(tmp_path)

    report = _coverage(tmp_path, catalog_path, spec_path, monkeypatch)

    assert report.decision_coverage_complete is True
    assert report.golden_controls_total == 4
    assert report.golden_controls_passed == 4
    assert report.golden_controls_failed == 0
    assert report.golden_validation_pass is True
    assert report.h2_coverage_gate_pass is True
    assert report.coverage_complete is True
    assert len(report.input_files["catalog"]) == 64
    assert len(report.input_files["golden"]) == 64
    markdown = render_markdown(report)
    assert "DECISION_COVERAGE_COMPLETE=true" in markdown
    assert "GOLDEN_VALIDATION_PASS=true" in markdown
    assert "H2_COVERAGE_GATE_PASS=true" in markdown


def test_perfect_counts_with_one_golden_failure_keep_coverage_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec()
    spec["boundary_controls"][0]["expected_disposition"] = "ARCHIVE_ONLY"  # type: ignore[index]
    catalog_path, spec_path = _write_inputs(tmp_path, spec=spec)

    report = _coverage(tmp_path, catalog_path, spec_path, monkeypatch)

    assert report.decision_coverage_complete is True
    assert report.golden_validation_pass is False
    assert report.h2_coverage_gate_pass is False
    assert report.coverage_complete is False


def test_final_coverage_gate_requires_manifest_and_golden_spec(tmp_path: Path) -> None:
    """P1 PRRT_kwDOTEIbbs6X3cnO: Final gate requires manifest (checked first)."""
    catalog_path, _ = _write_inputs(tmp_path)

    # P1: Manifest is now required first
    with pytest.raises(ValueError, match="sealed manifest file is required"):
        generate_coverage_report(
            catalog_path,
            expected_total=6,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_cli_returns_nonzero_for_golden_failure_and_malformed_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    spec["boundary_controls"][0]["expected_disposition"] = "ARCHIVE_ONLY"  # type: ignore[index]
    catalog_path, spec_path = _write_inputs(tmp_path, spec=spec)
    routing_path, rights_path, pii_path, manifest_path = _write_external_evidence(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "h2b_coverage_report",
            "--catalog",
            str(catalog_path),
            "--golden",
            str(spec_path),
            "--rights",
            str(rights_path),
            "--pii",
            str(pii_path),
            "--routing",
            str(routing_path),
            "--manifest",
            str(manifest_path),
            "--expected-total",
            "6",
            "--expected-manifest-sha256",
            MANIFEST_SHA256,
        ],
    )
    assert main() != 0

    spec_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid spec format"):
        main()


def test_golden_controls_are_non_vacuous(tmp_path: Path) -> None:
    baseline = _validate(tmp_path)
    mutant_catalog = copy.deepcopy(_catalog())
    mutant_catalog["physical_objects"][4]["disposition"] = "INGEST"  # type: ignore[index]
    mutant = _validate(tmp_path, catalog=mutant_catalog)
    restored = _validate(tmp_path)

    assert baseline.validation_passed is True
    assert mutant.validation_passed is False
    assert mutant.control_results[3].mismatching_count == 1
    assert restored.validation_passed is True
