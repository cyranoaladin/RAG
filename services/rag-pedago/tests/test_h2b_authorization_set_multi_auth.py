"""ADR-0044 — l'ensemble gouverné `AuthorizationSetV1`, exercé de bout en
bout dans l'orchestration H2-B (``_load_authority_set_evidence``,
``generate_coverage_report(authority_paths=...)``,
``report_to_h2_coverage_evidence_v2``).

Réutilise délibérément les mêmes fixtures/helpers que
``test_h2b_coverage_report.py`` (import direct du module de test frère,
même répertoire, mêmes constantes ``AUTHORITY_NOW``/``REPOSITORY``/etc.)
plutôt que de les redupliquer — un ensemble à N autorisations n'est qu'une
composition de ce que ce fichier frère construit déjà une par une.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import test_h2b_coverage_report as v1
import yaml
from nexus_contracts.authorization_set import AuthorizationSetError

from rag_pedago.imports import h2b_coverage_report as module
from rag_pedago.imports.h2b_coverage_report import (
    generate_coverage_report,
    report_to_h2_coverage_evidence,
    report_to_h2_coverage_evidence_v2,
)

GOOD_A_SHA256 = "1" * 64
GOOD_B_SHA256 = "2" * 64


def _write_two_good_catalog_and_evidence(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path, str]:
    """Catalogue + preuves réels à 3 objets (2 bons + l'entrée manifeste) —
    adapté de ``TestAuthorityRequiredSetTopologyABCDEF._write_case_f_catalog_and_evidence``
    (même fichier frère), sans le troisième candidat bloqué PII : ce lot
    n'a besoin que de deux candidats authority-required réels à répartir
    sur deux autorisations distinctes."""
    manifest_content = (
        f"{GOOD_A_SHA256}  01_EDUSCOL_OFFICIEL/good-a.pdf\n"
        f"{GOOD_B_SHA256}  01_EDUSCOL_OFFICIEL/good-b.pdf\n"
    )
    manifest_sha256 = hashlib.sha256(manifest_content.encode()).hexdigest()
    manifest_path = tmp_path / "00_ADMIN" / "SHA256SUMS.txt"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest_content, encoding="utf-8")

    def _item(content_sha256: str, filename: str) -> dict[str, Any]:
        return {
            "content_sha256": content_sha256,
            "path": f"01_EDUSCOL_OFFICIEL/{filename}",
            "base_disposition": "INGEST",
            "disposition": "REVIEW_REQUIRED",
            "zone": "01_EDUSCOL_OFFICIEL/",
            "currentness": "actuel",
            "rights_category_candidate": "officiel_public",
            "gate_statuses": {
                "rights": "PASS",
                "pii": "PASS",
                "authority": "BLOCKED_NOT_CLEARED",
            },
            "provenance_status": "VERIFIED",
            "attribution_metadata": {
                "source": "Eduscol",
                "source_url": f"https://eduscol.education.gouv.fr/{filename}",
            },
        }

    catalog = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": manifest_sha256,
        "manifest_entries": 2,
        "physical_object_count": 3,
        "content_artifact_count": 3,
        "eduscol_unique_artifacts": 2,
        "eduscol_placement_count": 2,
        "eduscol_placements_classified": 2,
        "eduscol_placements_unclassified": 0,
        "multi_placement_artifacts": 0,
        "disposition_counts": {
            "INGEST": 0,
            "REVIEW_REQUIRED": 2,
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
            _item(GOOD_A_SHA256, "good-a.pdf"),
            _item(GOOD_B_SHA256, "good-b.pdf"),
            {
                "content_sha256": manifest_sha256,
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
    catalog_path = tmp_path / "multi_auth_catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    routing = {
        "config_id": "multi-auth-routing-v1",
        "manifest_sha256": manifest_sha256,
        "rights_evidence_perimeter": ["00_ADMIN/", "01_EDUSCOL_OFFICIEL/"],
        "zone_rules": [
            {"zone_prefix": "00_ADMIN/", "disposition": "EXCLUDE", "reason": "admin"},
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "disposition": "INGEST",
                "currentness": "actuel",
            },
        ],
    }
    rights = {
        "registry_id": "multi-auth-rights-v1",
        "human_rights_decisions": {
            "eduscol": {
                "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                "decision_maker": "Nexus Réussite",
                "decision_date": "2026-08-08",
                "scope_manifest_sha256": manifest_sha256,
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
    required_paths = sorted(
        ["01_EDUSCOL_OFFICIEL/good-a.pdf", "01_EDUSCOL_OFFICIEL/good-b.pdf"]
    )
    pii = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "scanner_version": "multi-auth-scanner-v1",
        "scanner_sha256": "1" * 64,
        "policy_version": "multi-auth-policy-v1",
        "policy_sha256": "2" * 64,
        "corpus_manifest_sha256": manifest_sha256,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": len(required_paths),
        "required_pdf_path_set_digest": hashlib.sha256(
            "".join(f"{value}\n" for value in required_paths).encode()
        ).hexdigest(),
        "summary": {
            "sha256_mismatches": 0,
            "pii_scan_scope": "ALL_CORPUS_PDFS",
            "pii_scan_required": len(required_paths),
            "pii_scan_exempt": 0,
        },
        "results": [
            {
                "content_sha256": GOOD_A_SHA256,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            },
            {
                "content_sha256": GOOD_B_SHA256,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            },
        ],
    }
    routing_path = tmp_path / "multi_auth_routing.yml"
    rights_path = tmp_path / "multi_auth_rights.yml"
    pii_path = tmp_path / "multi_auth_pii.json"
    routing_path.write_text(yaml.safe_dump(routing), encoding="utf-8")
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")
    pii_path.write_text(json.dumps(pii), encoding="utf-8")
    return catalog_path, routing_path, rights_path, pii_path, manifest_path, manifest_sha256


def _authority_document(
    *, authorization_id: str, content_sha256: str, manifest_sha256: str, **overrides: Any
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": authorization_id,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": manifest_sha256,
        "profile_id": "multi_auth_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review: no PII found",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [content_sha256],
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "multi_auth",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    document.update(overrides)
    return document


def _write_pair(
    tmp_path: Path, *, manifest_sha256: str, ids: tuple[str, str] = ("multi_auth_a", "multi_auth_b")
) -> tuple[list[Path], list[Path]]:
    """Écrit deux autorisations valides (A couvre GOOD_A, B couvre
    GOOD_B) + leurs reçus de revue, retourne les listes dans le même
    ordre (déjà correctement appariées)."""
    id_a, id_b = ids
    doc_a = _authority_document(
        authorization_id=id_a, content_sha256=GOOD_A_SHA256, manifest_sha256=manifest_sha256
    )
    doc_b = _authority_document(
        authorization_id=id_b, content_sha256=GOOD_B_SHA256, manifest_sha256=manifest_sha256
    )
    path_a = v1._write_authority(tmp_path / f"{id_a}.json", doc_a)
    path_b = v1._write_authority(tmp_path / f"{id_b}.json", doc_b)
    binding_a = v1._write_review_binding(tmp_path, doc_a, filename=f"{id_a}_binding.json")
    binding_b = v1._write_review_binding(tmp_path, doc_b, filename=f"{id_b}_binding.json")
    return [path_a, path_b], [binding_a, binding_b]


def _generate_with_authority_set(
    tmp_path: Path,
    *,
    authority_paths: list[Path],
    binding_paths: list[Path],
    now: datetime = v1.AUTHORITY_NOW,
    revocations_path: Path | None = None,
    trust_anchor_path: Path | None = None,
    environment: str = "production",
    monkeypatch: pytest.MonkeyPatch,
) -> module.CoverageReport:
    v1._install_governed_root(monkeypatch, tmp_path)
    (
        catalog_path,
        routing_path,
        rights_path,
        pii_path,
        manifest_path,
        manifest_sha256,
    ) = _write_two_good_catalog_and_evidence(tmp_path)
    golden_path = tmp_path / "multi_auth_golden.yml"
    golden_path.write_text(
        yaml.safe_dump(
            {
                "spec_id": "multi_auth_topology_v1",
                "catalog_kind_required": "REAL_SEALED_CORPUS",
                "positive_controls": [
                    {
                        "control_id": "pos_good_a",
                        "sha256_prefix": GOOD_A_SHA256[:12],
                        "expected_base_disposition": "INGEST",
                        "expected_final_disposition": "REVIEW_REQUIRED",
                        "expected_currentness": "actuel",
                        "expected_gate_statuses": {
                            "rights": "PASS",
                            "pii": "PASS",
                            "authority": "BLOCKED_NOT_CLEARED",
                        },
                    },
                    {
                        "control_id": "pos_good_b",
                        "sha256_prefix": GOOD_B_SHA256[:12],
                        "expected_base_disposition": "INGEST",
                        "expected_final_disposition": "REVIEW_REQUIRED",
                        "expected_currentness": "actuel",
                        "expected_gate_statuses": {
                            "rights": "PASS",
                            "pii": "PASS",
                            "authority": "BLOCKED_NOT_CLEARED",
                        },
                    },
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
                "descriptive_assertions": {"authoritative": False, "items": []},
                "coverage_summary": {
                    "total_controls": 3,
                    "positive_controls": 2,
                    "boundary_controls": 0,
                    "negative_controls": 1,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    if trust_anchor_path is None and environment != "production":
        trust_anchor_path = v1._write_trust_anchor(tmp_path)
    return generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        manifest_path=manifest_path,
        authority_paths=authority_paths,
        authority_review_binding_paths=binding_paths,
        authority_revocations_path=revocations_path,
        authority_trust_anchor_path=trust_anchor_path,
        authority_environment=environment,
        authority_now=now,
        expected_total=3,
        expected_manifest_sha256=manifest_sha256,
    )


class TestAuthorizationSetEndToEnd:
    def test_two_authorizations_together_pass_the_final_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (
            _,
            _,
            _,
            _,
            _,
            manifest_sha256,
        ) = _write_two_good_catalog_and_evidence(tmp_path / "probe")
        authority_paths, binding_paths = _write_pair(tmp_path, manifest_sha256=manifest_sha256)
        report = _generate_with_authority_set(
            tmp_path,
            authority_paths=authority_paths,
            binding_paths=binding_paths,
            monkeypatch=monkeypatch,
        )
        assert report.authorization_set is not None
        assert report.authorization_set.authorization_count == 2
        assert report.authority_required_count == 2
        assert report.authority_covered_count == 2
        assert report.h2_coverage_gate_pass is True
        assert report.coverage_complete is True
        evidence = report_to_h2_coverage_evidence_v2(report)
        assert evidence.authorization_count == 2
        assert evidence.authority_covered_count == evidence.authority_required_count == 2
        assert evidence.h2_coverage_gate_pass is True
        # V1 projector refuses a V2-shaped report outright, never silently
        # produces a partial/misleading V1 document.
        with pytest.raises(module.H2CoverageEvidenceError):
            report_to_h2_coverage_evidence(report)

    def test_permuting_authority_order_yields_identical_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        probe_dir = tmp_path / "probe"
        (*_ignored, manifest_sha256) = _write_two_good_catalog_and_evidence(probe_dir)
        forward_dir, reverse_dir = tmp_path / "forward", tmp_path / "reverse"
        forward_dir.mkdir()
        reverse_dir.mkdir()
        auth_paths, binding_paths = _write_pair(forward_dir, manifest_sha256=manifest_sha256)
        auth_paths_rev, binding_paths_rev = _write_pair(
            reverse_dir, manifest_sha256=manifest_sha256
        )
        report_forward = _generate_with_authority_set(
            forward_dir,
            authority_paths=auth_paths,
            binding_paths=binding_paths,
            monkeypatch=monkeypatch,
        )
        report_reverse = _generate_with_authority_set(
            reverse_dir,
            authority_paths=list(reversed(auth_paths_rev)),
            binding_paths=list(reversed(binding_paths_rev)),
            monkeypatch=monkeypatch,
        )
        assert (
            report_forward.authorization_set.authorization_set_digest
            == report_reverse.authorization_set.authorization_set_digest
        )

    def test_changing_one_authorization_changes_the_set_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        probe_dir = tmp_path / "probe"
        (*_ignored, manifest_sha256) = _write_two_good_catalog_and_evidence(probe_dir)
        base_dir, changed_dir = tmp_path / "base", tmp_path / "changed"
        base_dir.mkdir()
        changed_dir.mkdir()
        auth_paths, binding_paths = _write_pair(base_dir, manifest_sha256=manifest_sha256)
        report_base = _generate_with_authority_set(
            base_dir, authority_paths=auth_paths, binding_paths=binding_paths, monkeypatch=monkeypatch
        )

        # Autorisation B modifiée : couvre toujours son unique contenu réel
        # mais sous un profil différent, donc un digest différent, sans
        # changer le périmètre couvert (toujours GOOD_A + GOOD_B au total).
        doc_a = _authority_document(
            authorization_id="multi_auth_a",
            content_sha256=GOOD_A_SHA256,
            manifest_sha256=manifest_sha256,
        )
        doc_b_changed = _authority_document(
            authorization_id="multi_auth_b",
            content_sha256=GOOD_B_SHA256,
            manifest_sha256=manifest_sha256,
            profile_version="2.0.0",
        )
        path_a = v1._write_authority(changed_dir / "multi_auth_a.json", doc_a)
        path_b = v1._write_authority(changed_dir / "multi_auth_b.json", doc_b_changed)
        binding_a = v1._write_review_binding(changed_dir, doc_a, filename="a_binding.json")
        binding_b = v1._write_review_binding(changed_dir, doc_b_changed, filename="b_binding.json")
        report_changed = _generate_with_authority_set(
            changed_dir,
            authority_paths=[path_a, path_b],
            binding_paths=[binding_a, binding_b],
            monkeypatch=monkeypatch,
        )
        assert (
            report_base.authorization_set.authorization_set_digest
            != report_changed.authorization_set.authorization_set_digest
        )
        # Le périmètre couvert reste identique malgré le digest différent.
        assert report_changed.authority_covered_count == 2


class TestAuthorizationSetAdversarial:
    """Unit-level : appelle ``_load_authority_set_evidence`` directement,
    sans reconstruire un catalogue complet à chaque cas — chaque test ne
    change qu'UNE chose par rapport au cas nominal à deux membres."""

    def _nominal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        revoked: list[str] | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        v1._install_governed_root(monkeypatch, tmp_path, revoked=revoked)
        manifest_sha256 = "9" * 64
        doc_a = _authority_document(
            authorization_id="adv_a", content_sha256=GOOD_A_SHA256, manifest_sha256=manifest_sha256
        )
        doc_b = _authority_document(
            authorization_id="adv_b", content_sha256=GOOD_B_SHA256, manifest_sha256=manifest_sha256
        )
        path_a = v1._write_authority(tmp_path / "adv_a.json", doc_a)
        path_b = v1._write_authority(tmp_path / "adv_b.json", doc_b)
        binding_a = v1._write_review_binding(tmp_path, doc_a, filename="adv_a_binding.json")
        binding_b = v1._write_review_binding(tmp_path, doc_b, filename="adv_b_binding.json")
        params: dict[str, Any] = {
            "authority_paths": [path_a, path_b],
            "binding_paths": [binding_a, binding_b],
            "manifest_sha256": manifest_sha256,
            "ingest_content_sha256": frozenset({GOOD_A_SHA256, GOOD_B_SHA256}),
            "ingest_rights_candidates": (
                (GOOD_A_SHA256, "officiel_public"),
                (GOOD_B_SHA256, "officiel_public"),
            ),
            "now": v1.AUTHORITY_NOW,
            "revocations_path": None,
            "trust_anchor_path": None,
            "environment": "production",
            "repository_root": tmp_path / "governed_root",
        }
        params.update(overrides)
        return params

    def test_zero_authorizations_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = self._nominal(tmp_path, monkeypatch, authority_paths=[], binding_paths=[])
        with pytest.raises(AuthorizationSetError, match="at least one authorization"):
            module._load_authority_set_evidence(**params)

    def test_mismatched_path_counts_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = self._nominal(tmp_path, monkeypatch)
        params["binding_paths"] = params["binding_paths"][:1]
        with pytest.raises(AuthorizationSetError, match="but 1"):
            module._load_authority_set_evidence(**params)

    def test_incomplete_coverage_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = self._nominal(tmp_path, monkeypatch)
        params["ingest_content_sha256"] = frozenset(
            {GOOD_A_SHA256, GOOD_B_SHA256, "3" * 64}
        )
        params["ingest_rights_candidates"] = (
            *params["ingest_rights_candidates"],
            ("3" * 64, "officiel_public"),
        )
        with pytest.raises(AuthorizationSetError, match="does not cover"):
            module._load_authority_set_evidence(**params)

    def test_extra_coverage_beyond_the_required_perimeter_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR-0044 SS4.3 : aucun SHA supplémentaire — un ensemble qui
        couvre plus que le périmètre mesuré est un scope artificiellement
        élargi, refusé, jamais toléré comme « couverture superflue
        inoffensive »."""
        params = self._nominal(tmp_path, monkeypatch)
        params["ingest_content_sha256"] = frozenset({GOOD_A_SHA256})
        params["ingest_rights_candidates"] = ((GOOD_A_SHA256, "officiel_public"),)
        with pytest.raises(AuthorizationSetError, match="outside the real authority-required"):
            module._load_authority_set_evidence(**params)

    def test_duplicate_authorization_id_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v1._install_governed_root(monkeypatch, tmp_path)
        manifest_sha256 = "9" * 64
        # Deux fichiers distincts, même authorization_id -- l'un des
        # scénarios les plus dangereux : sans ce refus, review_bindings
        # (dict keyed par id) écraserait silencieusement le premier reçu.
        doc_a = _authority_document(
            authorization_id="adv_same", content_sha256=GOOD_A_SHA256, manifest_sha256=manifest_sha256
        )
        doc_a2 = _authority_document(
            authorization_id="adv_same", content_sha256=GOOD_B_SHA256, manifest_sha256=manifest_sha256
        )
        path_a = v1._write_authority(tmp_path / "a.json", doc_a)
        path_a2 = v1._write_authority(tmp_path / "a2.json", doc_a2)
        binding_a = v1._write_review_binding(tmp_path, doc_a, filename="a_binding.json")
        binding_a2 = v1._write_review_binding(tmp_path, doc_a2, filename="a2_binding.json")
        with pytest.raises(AuthorizationSetError, match="more than one"):
            module._load_authority_set_evidence(
                [path_a, path_a2],
                [binding_a, binding_a2],
                manifest_sha256,
                ingest_content_sha256=frozenset({GOOD_A_SHA256, GOOD_B_SHA256}),
                ingest_rights_candidates=(
                    (GOOD_A_SHA256, "officiel_public"),
                    (GOOD_B_SHA256, "officiel_public"),
                ),
                now=v1.AUTHORITY_NOW,
                revocations_path=None,
                trust_anchor_path=None,
                environment="production",
                repository_root=tmp_path / "governed_root",
            )

    def test_overlapping_content_across_members_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le contrat AuthorizationSetV1 lui-même refuse le recouvrement
        (ADR-0044 SS4.2) — ce test prouve que l'orchestration laisse ce
        refus remonter tel quel, sans l'avaler ni le transformer."""
        v1._install_governed_root(monkeypatch, tmp_path)
        manifest_sha256 = "9" * 64
        doc_a = _authority_document(
            authorization_id="adv_overlap_a",
            content_sha256=GOOD_A_SHA256,
            manifest_sha256=manifest_sha256,
        )
        doc_b_overlap = _authority_document(
            authorization_id="adv_overlap_b",
            content_sha256=GOOD_A_SHA256,  # même contenu que A -- recouvrement
            manifest_sha256=manifest_sha256,
        )
        path_a = v1._write_authority(tmp_path / "a.json", doc_a)
        path_b = v1._write_authority(tmp_path / "b.json", doc_b_overlap)
        binding_a = v1._write_review_binding(tmp_path, doc_a, filename="a_binding.json")
        binding_b = v1._write_review_binding(tmp_path, doc_b_overlap, filename="b_binding.json")
        # AuthorizationSetV1's own model_validator raises this as a
        # pydantic ValidationError; build_authorization_set now wraps it
        # into AuthorizationSetError (same discipline as every other
        # refusal in this module and in parse_authorization_set).
        with pytest.raises(AuthorizationSetError, match="overlap on content_sha256"):
            module._load_authority_set_evidence(
                [path_a, path_b],
                [binding_a, binding_b],
                manifest_sha256,
                ingest_content_sha256=frozenset({GOOD_A_SHA256}),
                ingest_rights_candidates=((GOOD_A_SHA256, "officiel_public"),),
                now=v1.AUTHORITY_NOW,
                revocations_path=None,
                trust_anchor_path=None,
                environment="production",
                repository_root=tmp_path / "governed_root",
            )

    def test_wrong_manifest_on_one_member_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v1._install_governed_root(monkeypatch, tmp_path)
        manifest_sha256 = "9" * 64
        doc_a = _authority_document(
            authorization_id="adv_a", content_sha256=GOOD_A_SHA256, manifest_sha256=manifest_sha256
        )
        doc_b_stale = _authority_document(
            authorization_id="adv_b", content_sha256=GOOD_B_SHA256, manifest_sha256="8" * 64
        )
        path_a = v1._write_authority(tmp_path / "a.json", doc_a)
        path_b = v1._write_authority(tmp_path / "b.json", doc_b_stale)
        binding_a = v1._write_review_binding(tmp_path, doc_a, filename="a_binding.json")
        binding_b = v1._write_review_binding(tmp_path, doc_b_stale, filename="b_binding.json")
        with pytest.raises(ValueError, match="SEMANTIC_VALIDATION failed: .*bound to another manifest"):
            module._load_authority_set_evidence(
                [path_a, path_b],
                [binding_a, binding_b],
                manifest_sha256,
                ingest_content_sha256=frozenset({GOOD_A_SHA256, GOOD_B_SHA256}),
                ingest_rights_candidates=(
                    (GOOD_A_SHA256, "officiel_public"),
                    (GOOD_B_SHA256, "officiel_public"),
                ),
                now=v1.AUTHORITY_NOW,
                revocations_path=None,
                trust_anchor_path=None,
                environment="production",
                repository_root=tmp_path / "governed_root",
            )

    def test_one_revoked_authorization_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # En production le registre est gouverné : le peupler via
        # _install_governed_root (revoked=[...]) plutôt que via l'argument
        # --authority-revocations, refusé en production (F2).
        params = self._nominal(tmp_path, monkeypatch, revoked=["adv_b"])
        with pytest.raises(ValueError, match="SEMANTIC_VALIDATION failed: .*revocation registry"):
            module._load_authority_set_evidence(**params)

    def test_one_expired_authorization_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = self._nominal(tmp_path, monkeypatch)
        params["now"] = datetime(2027, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="SEMANTIC_VALIDATION failed: .*expired"):
            module._load_authority_set_evidence(**params)

    def test_one_bad_review_binding_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v1._install_governed_root(monkeypatch, tmp_path)
        manifest_sha256 = "9" * 64
        doc_a = _authority_document(
            authorization_id="adv_a", content_sha256=GOOD_A_SHA256, manifest_sha256=manifest_sha256
        )
        doc_b = _authority_document(
            authorization_id="adv_b", content_sha256=GOOD_B_SHA256, manifest_sha256=manifest_sha256
        )
        path_a = v1._write_authority(tmp_path / "a.json", doc_a)
        path_b = v1._write_authority(tmp_path / "b.json", doc_b)
        binding_a = v1._write_review_binding(tmp_path, doc_a, filename="a_binding.json")
        # Le reçu de B est en réalité celui de A (mauvais contenu lié).
        binding_b_wrong = v1._write_review_binding(
            tmp_path, doc_a, filename="b_binding_wrong.json"
        )
        with pytest.raises(ValueError, match="REVIEW_BINDING_VALIDATION failed"):
            module._load_authority_set_evidence(
                [path_a, path_b],
                [binding_a, binding_b_wrong],
                manifest_sha256,
                ingest_content_sha256=frozenset({GOOD_A_SHA256, GOOD_B_SHA256}),
                ingest_rights_candidates=(
                    (GOOD_A_SHA256, "officiel_public"),
                    (GOOD_B_SHA256, "officiel_public"),
                ),
                now=v1.AUTHORITY_NOW,
                revocations_path=None,
                trust_anchor_path=None,
                environment="production",
                repository_root=tmp_path / "governed_root",
            )

    def test_tampered_authorization_bytes_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Octets non canoniques (ré-indentés) -> refus structurel,
        équivalent N-autorités de ``TestAuthorityStructuralValidation``."""
        params = self._nominal(tmp_path, monkeypatch)
        tampered = params["authority_paths"][1]
        document = json.loads(tampered.read_bytes())
        tampered.write_text(json.dumps(document, indent=4), encoding="utf-8")
        with pytest.raises(ValueError, match="STRUCTURAL_VALIDATION failed"):
            module._load_authority_set_evidence(**params)

    def test_nominal_two_member_set_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = self._nominal(tmp_path, monkeypatch)
        authorization_set, revocations_checked = module._load_authority_set_evidence(**params)
        assert authorization_set.authorization_count == 2
        assert authorization_set.union_content_count == 2
        # En production le registre gouverné est toujours lu (même vide) :
        # révocation réellement vérifiée, jamais seulement supposée (F2).
        assert revocations_checked is True


class TestV1PathUnaffected:
    def test_singular_authority_path_still_produces_v1_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Garde-fou explicite, en plus de la suite complète inchangée de
        ``test_h2b_coverage_report.py`` : un run à une seule autorité
        continue de produire du V1, jamais du V2, et
        ``report.authorization_set`` reste ``None``."""
        v1._install_governed_root(monkeypatch, tmp_path)
        path = v1._write_authority(tmp_path / "authority.json", v1._valid_authority_document())
        report = v1._generate_with_authority(
            tmp_path, authority_path=path, environment="production"
        )
        assert report.authorization_set is None
        evidence = report_to_h2_coverage_evidence(report)
        assert evidence.protocol_version == "NEXUS-H2-COVERAGE-EVIDENCE-V1"
        with pytest.raises(module.H2CoverageEvidenceError):
            report_to_h2_coverage_evidence_v2(report)
