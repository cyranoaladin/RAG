"""Rehearsal end-to-end réel — chaîne de preuve H2 (PR #109, suivi).

`_produce-h2-evidence.yml` (corrigé en PR #109) enchaîne, contre un vrai
corpus scellé : compilation de catalogue candidat -> vue de revue ->
gate H2 -> assemblage de preuve. PR #109 lui-même n'a exercé que des
tests structurels statiques sur le YAML, jamais les vraies étapes
shell/Python. Ce fichier ferme cet écart : il exécute les vrais
producteurs Python (jamais réimplémentés) contre un corpus synthétique
sûr, jamais des données réelles, jamais une clé de signature réelle,
jamais un accès réseau réel.

**Défaut structurel réel trouvé en construisant ce rehearsal, corrigé
depuis (voir `docs/reports/lot_h2_authority_promotion.md`, Finding C)** :
`corpus_catalog_compiler.compile_sealed_catalog`/
`compile_governed_sealed_catalog` ne peuvent TOUJOURS PAS produire
`disposition="INGEST"` pour un objet dans le fichier catalogue lui-même
-- même droits et PII au vert, la disposition qu'ils écrivent reste
`REVIEW_REQUIRED` (`gate_statuses.authority` toujours
`"BLOCKED_NOT_CLEARED"`), par construction explicite ("L'autorité n'est
jamais injectée dans ce compilateur candidat") ; il n'existe toujours
aucune étape de « republication gouvernée » qui réécrirait ce fichier.
Ce qui a changé : `h2b_coverage_report.generate_coverage_report` sait
désormais reconnaître, sur une copie interne jamais écrite sur disque,
qu'une preuve d'autorité externe réelle et vérifiée couvre un tel
candidat lorsque toutes les autres portes obligatoires sont déjà
indépendamment au vert (`_promote_authority_cleared_candidates`) -- le
périmètre de complétude que cette preuve doit couvrir était d'ailleurs
lui-même erroné avant ce correctif (borné sur `disposition`, toujours
vide pour un candidat réel, plutôt que sur `base_disposition`, Finding
C). `test_gate_correctly_recognizes_real_authority_over_the_real_compilers_output`,
ci-dessous, prouve que le VRAI compilateur, chaîné pour de vrai, produit
une sortie que ce mécanisme reconnaît et peut désormais couvrir --
tandis que `coverage_complete` reste correctement faux ici, ce test
s'exécutant en mode `rehearsal`, qui ne peut par construction jamais
rendre un verdict final vert.

Aucune clé privée réelle, aucun accès réseau réel, aucune mutation
pgvector. `LIVE_MUTATIONS_ALLOWED=false`.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_h2b_coverage_report as gate_fixtures  # noqa: E402
from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: E402
from nexus_contracts.authorization_set import (  # noqa: E402
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
    VerifiedProfileFactV1,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.h2_coverage_evidence import parse_h2_coverage_evidence  # noqa: E402
from nexus_contracts.ingestion import (  # noqa: E402
    CollectionProfile,
    ResourceScope,
    collection_profile_fingerprint,
    profile_manifest_fingerprint,
)
from nexus_contracts.release_evidence import (  # noqa: E402
    H2EvidenceBundleV2,
    PromotionEvidenceV2,
    ReleaseEvidenceError,
    verify_h2_evidence_bundle_v2_freshness,
    verify_promotion_evidence_v2,
)

from rag_pedago.governance.corpus_campaign import (  # noqa: E402
    CORPUS_CAMPAIGN_V2_PROTOCOL_VERSION,
    CorpusCampaignV2,
)
from rag_pedago.governance.h2_evidence import (  # noqa: E402
    build_h2_evidence_bundle_v2,
)
from rag_pedago.governance.release_scope_placement import (  # noqa: E402
    ReleaseScopePlacementGitInputs,
)
from rag_pedago.imports.corpus_catalog_compiler import (  # noqa: E402
    Disposition,
    compile_governed_sealed_catalog,
)
from rag_pedago.imports.h2b_coverage_report import (  # noqa: E402
    CoverageReport,
    generate_coverage_report,
    report_to_h2_coverage_evidence,
    report_to_h2_coverage_evidence_v2,
)

CONTENT_SHA256 = gate_fixtures.CONTENT_SHA256
MANIFEST_SHA256 = gate_fixtures.MANIFEST_SHA256
AUTHORITY_NOW = gate_fixtures.AUTHORITY_NOW

# ---------------------------------------------------------------------------
# Part A -- the REAL candidate catalog compiler, chained for real, proving
# its structural incompleteness is correctly detected by the gate rather
# than silently accepted.
# ---------------------------------------------------------------------------


def _write_synthetic_sealed_corpus(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    """Un vrai manifeste GNU + un vrai TSV de placement, jamais du contenu
    réel d'élève ou de production -- un seul objet synthétique, le même
    ``CONTENT_SHA256``/``MANIFEST_SHA256`` que ``test_h2b_coverage_report``
    pour que les fixtures d'autorité/liaison de revue déjà établies là-bas
    restent valables ici sans duplication."""
    manifest_path = tmp_path / "SHA256SUMS.txt"
    manifest_path.write_text(gate_fixtures._MANIFEST_CONTENT, encoding="utf-8")

    placement_path = tmp_path / "placements.tsv"
    columns = (
        "sha256", "scope", "famille", "matiere_ou_rubrique", "niveau",
        "type_document", "annee", "statut", "titre", "url_source",
        "objet_source", "chemin_technique_existant", "chemin_par_niveau",
        "chemin_par_scope",
    )
    row = (
        CONTENT_SHA256, "lycee/terminale/maths", "lycee", "mathematiques",
        "terminale", "cours", "2026", "actuel", "Doc rehearsal E2E",
        "https://eduscol.education.gouv.fr/test", "current.pdf",
        "01_EDUSCOL_OFFICIEL/current.pdf",
        "by_level/terminale/current.pdf", "by_scope/terminale/current.pdf",
    )
    placement_path.write_text(
        "\t".join(columns) + "\n" + "\t".join(row) + "\n", encoding="utf-8"
    )

    config = {
        "config_id": "e2e-rehearsal-v1",
        "manifest_sha256": MANIFEST_SHA256,
        "rights_evidence_perimeter": ["00_ADMIN/", "01_EDUSCOL_OFFICIEL/"],
        "zone_rules": [
            {"zone_prefix": "00_ADMIN/", "disposition": "EXCLUDE", "reason": "admin"},
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "disposition": "INGEST",
                "currentness": "actuel",
                # F4 : sans cette clé, le vrai compilateur produit
                # rights_category_candidate=None -- ce que la couverture
                # de complétude (Finding C) refuse désormais à raison
                # pour tout candidat base_disposition==INGEST.
                "rights_category": "officiel_public",
            },
        ],
    }
    return manifest_path, placement_path, config


def _rights_and_pii_dicts(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Réutilise ``_write_external_evidence`` (fixture déjà établie et
    prouvée compatible avec ``_derive_rights_clearances``/
    ``_derive_pii_clearances``) plutôt que de réinventer un schéma à la
    main -- une première tentative avec des dictionnaires construits
    indépendamment a été refusée par la revérification interne du
    compilateur (« catalog rights gate evidence mismatch »), confirmant
    que ces schémas sont plus stricts que leur description informelle."""
    _routing_path, rights_path, pii_path, _authority_path, _manifest_path = (
        gate_fixtures._write_external_evidence(tmp_path, include_authority=False)
    )
    rights = yaml.safe_load(rights_path.read_text(encoding="utf-8"))
    pii = json.loads(pii_path.read_text(encoding="utf-8"))
    return rights, pii


def test_real_catalog_compiler_never_promotes_a_candidate_to_ingest(tmp_path: Path) -> None:
    """Le VRAI compilateur candidat, contre un vrai corpus scellé
    synthétique, avec droits et PII réellement dérivés d'un registre/preuve
    réels (``compile_governed_sealed_catalog``, jamais réimplémenté)."""
    manifest_path, placement_path, config = _write_synthetic_sealed_corpus(tmp_path)
    rights_registry, pii_evidence = _rights_and_pii_dicts(tmp_path)
    catalog = compile_governed_sealed_catalog(
        manifest_path, placement_path, config,
        rights_registry=rights_registry,
        pii_evidence=pii_evidence,
    )
    artifact = catalog.artifacts[CONTENT_SHA256]
    physical = artifact.physical_objects[0]

    assert physical.base_disposition is Disposition.INGEST
    assert physical.gate_statuses["rights"] == "PASS"
    assert physical.gate_statuses["pii"] == "PASS"
    # Le constat structurel central de ce fichier :
    assert physical.gate_statuses["authority"] == "BLOCKED_NOT_CLEARED"
    assert physical.disposition is Disposition.REVIEW_REQUIRED
    assert physical.disposition_reason == "Mandatory gates not cleared: authority"


def test_gate_correctly_recognizes_real_authority_over_the_real_compilers_output(
    tmp_path: Path,
) -> None:
    """Le catalogue RÉEL (jamais promu dans son propre fichier, §ci-dessus)
    est ensuite soumis au vrai gate H2, avec une autorité par ailleurs
    valide couvrant ce ``content_sha256`` -- le mécanisme de promotion
    (Finding C) doit le reconnaître comme couvert, puisque toutes les
    autres portes obligatoires (droits, PII, actualité, format,
    provenance, attribution) sont déjà indépendamment au vert.
    ``coverage_complete`` reste néanmoins faux ici, parce que ce test
    s'exécute en mode ``rehearsal``, qui ne peut jamais rendre un verdict
    final vert par construction -- pas à cause d'une incapacité du gate
    à reconnaître la couverture elle-même."""
    manifest_path, placement_path, config = _write_synthetic_sealed_corpus(tmp_path)
    rights_registry, pii_evidence = _rights_and_pii_dicts(tmp_path)
    catalog = compile_governed_sealed_catalog(
        manifest_path, placement_path, config,
        rights_registry=rights_registry,
        pii_evidence=pii_evidence,
    )
    artifact = catalog.artifacts[CONTENT_SHA256]
    physical = artifact.physical_objects[0]

    catalog_json = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA256,
        "manifest_entries": 1,
        "physical_object_count": 2,
        "disposition_counts": {"INGEST": 0, "REVIEW_REQUIRED": 1, "QUARANTINE": 0, "ARCHIVE_ONLY": 0, "EXCLUDE": 1, "UNSUPPORTED": 0},
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "verification_errors": [],
        "physical_objects": [
            {
                "content_sha256": CONTENT_SHA256,
                "path": physical.path,
                "base_disposition": physical.base_disposition.value,
                "disposition": physical.disposition.value,
                "zone": physical.zone,
                "currentness": "actuel",
                "gate_statuses": physical.gate_statuses,
                # F4 : un vrai catalogue compilé porte toujours cette
                # valeur pour un candidat base_disposition==INGEST --
                # l'omission ici (avant Finding C) n'était jamais exercée,
                # ce candidat tombant hors du périmètre de complétude par
                # erreur borné sur ``disposition`` plutôt que
                # ``base_disposition``.
                "rights_category_candidate": physical.rights_category_candidate,
                "provenance_status": physical.provenance_status,
                "attribution_metadata": physical.attribution_metadata,
            },
            {
                # H2-F Défaut 1 : le gate exige que le catalogue porte lui-même
                # l'auto-référence du manifeste scellé -- jamais implicite.
                "content_sha256": MANIFEST_SHA256,
                "path": "00_ADMIN/SHA256SUMS.txt",
                "base_disposition": "EXCLUDE",
                "disposition": "EXCLUDE",
                "zone": "00_ADMIN/",
                "currentness": None,
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {"source": "NEXUS_CORPUS_GOVERNANCE", "source_reference": "00_ADMIN/SHA256SUMS.txt"},
            },
        ],
    }
    catalog_path = tmp_path / "real-compiled-catalog.json"
    catalog_path.write_text(json.dumps(catalog_json), encoding="utf-8")

    routing_path, rights_path, pii_path, authority_path, real_manifest_path = (
        gate_fixtures._write_external_evidence(tmp_path, include_authority=True, environment="rehearsal")
    )
    golden_path = gate_fixtures._write_golden_spec(tmp_path, expected_final="REVIEW_REQUIRED", expected_authority="BLOCKED_NOT_CLEARED")

    report = generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        authority_path=authority_path,
        manifest_path=real_manifest_path,
        expected_manifest_sha256=MANIFEST_SHA256,
        authority_now=AUTHORITY_NOW,
        authority_review_binding_path=tmp_path / "review_binding.json",
        authority_trust_anchor_path=tmp_path / "trust_anchor.json",
        authority_environment="rehearsal",
        expected_total=1,
    )
    assert report.blocked_ingest_candidates == 0
    assert report.mandatory_gate_blockers == {}
    assert report.coverage_complete is False


# ---------------------------------------------------------------------------
# Part B -- the gate MECHANISM itself (rights/PII/authority/revocation/
# manifest cross-checks), nominal + 5 adversarial scenarios, using a
# catalog shaped as the not-yet-built "governed republish" step's output
# would look -- the same established shape this repo's own gate test suite
# already uses (`_write_real_catalog`) for exactly this reason.
# ---------------------------------------------------------------------------


def _catalog_with_ingest_candidate(tmp_path: Path, *, authority_status: str = "PASS") -> Path:
    return gate_fixtures._write_real_catalog(tmp_path, authority_status=authority_status)


def _nominal_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any):
    gate_fixtures._install_governed_root(monkeypatch, tmp_path)
    return gate_fixtures._generate(
        tmp_path,
        _catalog_with_ingest_candidate(tmp_path),
        gate_fixtures._write_golden_spec(tmp_path),
        include_authority=True,
        expected_total=2,
        **overrides,
    )


class TestE2ERehearsalNominal:
    def test_full_chain_reaches_a_real_gate_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        report = _nominal_report(tmp_path, monkeypatch)
        assert report.coverage_complete is True
        assert report.authority_review_binding_verified is True
        assert report.authority_revocations_checked is True

    def test_json_evidence_round_trips_through_the_real_contract_parser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        report = _nominal_report(tmp_path, monkeypatch)
        assert report.coverage_complete is True
        evidence = report_to_h2_coverage_evidence(report)
        canonical = evidence.canonical_bytes()
        reparsed = parse_h2_coverage_evidence(canonical)
        assert reparsed.h2_coverage_gate_pass is True
        assert reparsed.manifest_sha256 == MANIFEST_SHA256
        # Round-trip stability: re-serializing the reparsed object must be
        # byte-identical -- a canonical form that isn't its own fixed point
        # would mean the digest a signer signs doesn't match what a later
        # verifier recomputes.
        assert reparsed.canonical_bytes() == canonical


class TestE2ERehearsalAdversarial:
    def test_wrong_expected_manifest_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        gate_fixtures._install_governed_root(monkeypatch, tmp_path)
        catalog_path = _catalog_with_ingest_candidate(tmp_path)
        golden_path = gate_fixtures._write_golden_spec(tmp_path)
        routing_path, rights_path, pii_path, authority_path, manifest_path = gate_fixtures._write_external_evidence(
            tmp_path, include_authority=True
        )
        # H2-F Défaut 1 : un manifeste attendu erroné est un refus dur
        # (exception), jamais un rapport dégradé avec corpus_match=False --
        # aucune preuve partielle n'est jamais rendue pour un manifeste
        # dont l'identité elle-même n'est pas celle attendue.
        with pytest.raises(ValueError, match="manifest SHA256 mismatch"):
            generate_coverage_report(
                catalog_path, rights_path=rights_path, pii_path=pii_path, routing_path=routing_path,
                golden_path=golden_path, authority_path=authority_path, manifest_path=manifest_path,
                expected_manifest_sha256="f" * 64, authority_now=AUTHORITY_NOW,
                authority_review_binding_path=tmp_path / "review_binding.json",
                authority_environment="production", expected_total=2,
            )

    def test_authority_not_covering_the_content_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        gate_fixtures._install_governed_root(monkeypatch, tmp_path)
        catalog_path = _catalog_with_ingest_candidate(tmp_path)
        # Un candidat encore en attente d'autorité (base_disposition=INGEST,
        # disposition=REVIEW_REQUIRED, authority=BLOCKED_NOT_CLEARED) -- le
        # seul état qu'un compilateur réel produit avant autorisation, et le
        # seul état qu'``authority_required_candidate_facts`` inclut dans le
        # périmètre requis.
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["physical_objects"][0]["disposition"] = "REVIEW_REQUIRED"
        catalog["physical_objects"][0]["gate_statuses"]["authority"] = (
            "BLOCKED_NOT_CLEARED"
        )
        catalog["disposition_counts"]["INGEST"] = 0
        catalog["disposition_counts"]["REVIEW_REQUIRED"] = 1
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        golden_path = gate_fixtures._write_golden_spec(tmp_path)
        routing_path, rights_path, pii_path, _unused, manifest_path = gate_fixtures._write_external_evidence(
            tmp_path, include_authority=False
        )
        # Une autorité réelle, structurellement valide, mais qui ne couvre
        # PAS ce content_sha256 -- jamais une autorisation auto-déclarée
        # acceptée pour un contenu qu'elle ne cite pas explicitement. Le
        # gate REFUSE (lève), il ne rend pas un rapport dégradé -- une
        # sémantique invalide n'a pas de verdict partiel.
        other_content = "b" * 64
        authority_doc = {
            "protocol_version": "LOT41A-V2",
            "authorization_id": "e2e_wrong_scope_v1",
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "manifest_digest": MANIFEST_SHA256,
            "profile_id": "e2e_test_profile",
            "profile_version": "1.0.0",
            "profile_fingerprint": "f" * 64,
            "allowed_domains": ["eduscol.education.fr"],
            "rights_categories": ["officiel_public"],
            "exclusions": [],
            "pii_absence_attested": True,
            "pii_absence_evidence": "n/a",
            "valid_from": "2026-01-01T00:00:00.000000Z",
            "valid_until": "2026-12-31T23:59:59.999999Z",
            "allowed_content_sha256": [other_content],
            "scope": {
                "audience": ["libre"], "candidat": "libre", "collection": "test_collection",
                "matiere": "maths", "niveau": "terminale", "programme_version": "v1",
                "school_year": "2026-2027", "tenant": "libre_terminale", "visibility": "public", "voie": "generale",
            },
        }
        authority_path = gate_fixtures._write_authority(tmp_path / "authority.json", authority_doc)
        gate_fixtures._write_review_binding(tmp_path, authority_doc)
        with pytest.raises(ValueError, match="SEMANTIC_VALIDATION"):
            generate_coverage_report(
                catalog_path, rights_path=rights_path, pii_path=pii_path, routing_path=routing_path,
                golden_path=golden_path, authority_path=authority_path, manifest_path=manifest_path,
                expected_manifest_sha256=MANIFEST_SHA256, authority_now=AUTHORITY_NOW,
                authority_review_binding_path=tmp_path / "review_binding.json",
                authority_environment="production", expected_total=2,
            )

    def test_revoked_authorization_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        authorization_id = "h2b_test_authority_v1"
        # Un seul appel à _install_governed_root : _nominal_report() en
        # ferait un second, qui écraserait ce registre de révocation avec
        # sa propre valeur par défaut (aucune révocation) -- constaté en
        # le lançant une première fois par erreur (DID NOT RAISE).
        gate_fixtures._install_governed_root(monkeypatch, tmp_path, revoked=[authorization_id])
        with pytest.raises(Exception, match="(?i)revoked|revocation"):
            gate_fixtures._generate(
                tmp_path,
                _catalog_with_ingest_candidate(tmp_path),
                gate_fixtures._write_golden_spec(tmp_path),
                include_authority=True,
                expected_total=2,
            )

    def test_pii_not_cleared_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PII non blanchie : catalogue ET preuve PII cohérents (tous deux
        « non blanchi »), jamais une falsification du seul catalogue --
        celle-ci est une classe de refus différente, déjà couverte par
        ``verify_catalog_evidence_bindings`` (constatée en tentant
        initialement de trafiquer uniquement le catalogue : refusée avec
        « catalog PII gate evidence mismatch », un refus légitime mais pas
        celui que ce test veut isoler)."""
        gate_fixtures._install_governed_root(monkeypatch, tmp_path)
        routing_path, rights_path, pii_path, authority_path, manifest_path = gate_fixtures._write_external_evidence(
            tmp_path, include_authority=True
        )
        pii_doc = json.loads(pii_path.read_text(encoding="utf-8"))
        pii_doc["results"][0]["status"] = "QUARANTINED_PII"
        pii_path.write_text(json.dumps(pii_doc), encoding="utf-8")

        catalog = json.loads(_catalog_with_ingest_candidate(tmp_path).read_text())
        for obj in catalog["physical_objects"]:
            if obj["content_sha256"] == CONTENT_SHA256:
                obj["base_disposition"] = "INGEST"
                obj["disposition"] = "REVIEW_REQUIRED"
                obj["gate_statuses"]["pii"] = "BLOCKED_PII_DETECTED"
        catalog["disposition_counts"] = {"INGEST": 0, "REVIEW_REQUIRED": 1, "QUARANTINE": 0, "ARCHIVE_ONLY": 0, "EXCLUDE": 1, "UNSUPPORTED": 0}
        catalog_path = tmp_path / "catalog_pii_failure.json"
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

        report = generate_coverage_report(
            catalog_path, rights_path=rights_path, pii_path=pii_path, routing_path=routing_path,
            golden_path=gate_fixtures._write_golden_spec(tmp_path, expected_final="REVIEW_REQUIRED"),
            authority_path=authority_path, manifest_path=manifest_path,
            expected_manifest_sha256=MANIFEST_SHA256, authority_now=AUTHORITY_NOW,
            authority_review_binding_path=tmp_path / "review_binding.json",
            authority_environment="production", expected_total=2,
        )
        assert report.blocked_ingest_candidates == 1
        assert report.coverage_complete is False

    def test_rights_not_cleared_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Droits non clarifiés : même discipline que le test PII ci-dessus
        -- catalogue et preuve de droits cohérents, jamais une falsification
        isolée du catalogue seul."""
        gate_fixtures._install_governed_root(monkeypatch, tmp_path)
        routing_path, rights_path, pii_path, authority_path, manifest_path = gate_fixtures._write_external_evidence(
            tmp_path, include_authority=True
        )
        rights_doc = yaml.safe_load(rights_path.read_text(encoding="utf-8"))
        rights_doc["source_evidence"]["eduscol"]["rights_status"] = "REVIEW_REQUIRED"
        del rights_doc["source_evidence"]["eduscol"]["rights_decision_ref"]
        rights_path.write_text(yaml.safe_dump(rights_doc), encoding="utf-8")

        catalog = json.loads(_catalog_with_ingest_candidate(tmp_path).read_text())
        for obj in catalog["physical_objects"]:
            if obj["content_sha256"] == CONTENT_SHA256:
                obj["base_disposition"] = "INGEST"
                obj["disposition"] = "REVIEW_REQUIRED"
                obj["gate_statuses"]["rights"] = "BLOCKED_NOT_CLEARED"
        catalog["disposition_counts"] = {"INGEST": 0, "REVIEW_REQUIRED": 1, "QUARANTINE": 0, "ARCHIVE_ONLY": 0, "EXCLUDE": 1, "UNSUPPORTED": 0}
        catalog_path = tmp_path / "catalog_rights_failure.json"
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

        report = generate_coverage_report(
            catalog_path, rights_path=rights_path, pii_path=pii_path, routing_path=routing_path,
            golden_path=gate_fixtures._write_golden_spec(tmp_path, expected_final="REVIEW_REQUIRED"),
            authority_path=authority_path, manifest_path=manifest_path,
            expected_manifest_sha256=MANIFEST_SHA256, authority_now=AUTHORITY_NOW,
            authority_review_binding_path=tmp_path / "review_binding.json",
            authority_environment="production", expected_total=2,
        )
        assert report.blocked_ingest_candidates == 1
        assert report.coverage_complete is False


# ---------------------------------------------------------------------------
# Part C -- V2 multi-authorization release evidence. The report is the real
# CoverageReport type and crosses the real projection, bundle builder and
# promotion verifier. V1 rehearsal above remains deliberately untouched.
# ---------------------------------------------------------------------------


def _v2_scope(*, collection: str, matiere: str) -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_terminale",
            "collection": collection,
            "niveau": "terminale",
            "voie": "generale",
            "matiere": matiere,
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        }
    )


def _v2_campaign(authorization_set: AuthorizationSetV1) -> CorpusCampaignV2:
    return CorpusCampaignV2.model_validate(
        {
            "protocol_version": CORPUS_CAMPAIGN_V2_PROTOCOL_VERSION,
            "campaign_id": "e2e-multi-auth",
            "source_kind": "ghcr-oci",
            "source_registry": "ghcr.io",
            "source_repository": "cyranoaladin/rag-corpus",
            "source_oci_digest": "sha256:" + "3" * 64,
            "source_archive_sha256": "4" * 64,
            "source_tree_digest": "5" * 64,
            "archive_format": "tar.zst",
            "source_root": "corpus",
            "expected_manifest_sha256": authorization_set.corpus_manifest_sha256,
            "expected_catalog_digest": "6" * 64,
            "authorization_set_digest": authorization_set.digest(),
            "authority_required_count": authorization_set.authority_required_count,
            "authority_required_set_sha256": (
                authorization_set.authority_required_set_sha256
            ),
            "profile_manifest_digest": authorization_set.profile_manifest_digest,
            "release_scope_placement_digest": (
                authorization_set.release_scope_placement_digest
            ),
            "compiler_version": "corpus-catalog-compiler/2",
            "routing_config_digest": "7" * 64,
            "rights_config_digest": "8" * 64,
            "pii_config_digest": "9" * 64,
            "golden_spec_digest": "f" * 64,
            "environment": "production",
            "retention_days": 90,
        }
    )


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write_two_content_gate_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path, str, tuple[str, str]]:
    first_content = CONTENT_SHA256
    second_content = "b" * 64
    paths = (
        "01_EDUSCOL_OFFICIEL/current.pdf",
        "01_EDUSCOL_OFFICIEL/second.pdf",
    )
    manifest_raw = "".join(
        f"{content}  {path}\n"
        for content, path in zip((first_content, second_content), paths, strict=True)
    )
    manifest_sha256 = hashlib.sha256(manifest_raw.encode()).hexdigest()

    routing_path, rights_path, pii_path, _, manifest_path = (
        gate_fixtures._write_external_evidence(tmp_path, include_authority=False)
    )
    manifest_path.write_text(manifest_raw, encoding="utf-8")

    routing = yaml.safe_load(routing_path.read_text(encoding="utf-8"))
    routing["manifest_sha256"] = manifest_sha256
    routing_path.write_text(yaml.safe_dump(routing), encoding="utf-8")

    rights = yaml.safe_load(rights_path.read_text(encoding="utf-8"))
    rights["human_rights_decisions"]["eduscol"]["scope_manifest_sha256"] = (
        manifest_sha256
    )
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")

    pii = json.loads(pii_path.read_text(encoding="utf-8"))
    pii["corpus_manifest_sha256"] = manifest_sha256
    pii["required_pdf_path_count"] = 2
    pii["required_pdf_path_set_digest"] = hashlib.sha256(
        "".join(f"{path}\n" for path in sorted(paths)).encode()
    ).hexdigest()
    pii["summary"]["pii_scan_required"] = 2
    pii["results"].append(
        {
            "content_sha256": second_content,
            "physical_object_count": 1,
            "status": "CLEARED",
            "error_code": None,
        }
    )
    pii_path.write_text(json.dumps(pii), encoding="utf-8")

    catalog_path = gate_fixtures._write_real_catalog(tmp_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    first = catalog["physical_objects"][0]
    first["disposition"] = "REVIEW_REQUIRED"
    first["gate_statuses"]["authority"] = "BLOCKED_NOT_CLEARED"
    second = json.loads(json.dumps(first))
    second["content_sha256"] = second_content
    second["path"] = paths[1]
    second["attribution_metadata"]["source_url"] += "/second"
    manifest_item = catalog["physical_objects"][1]
    manifest_item["content_sha256"] = manifest_sha256
    catalog.update(
        {
            "manifest_sha256": manifest_sha256,
            "manifest_entries": 2,
            "physical_object_count": 3,
            "content_artifact_count": 3,
            "eduscol_unique_artifacts": 2,
            "eduscol_placement_count": 2,
            "eduscol_placements_classified": 2,
            "multi_placement_artifacts": 0,
            "disposition_counts": {
                "INGEST": 0,
                "REVIEW_REQUIRED": 2,
                "QUARANTINE": 0,
                "ARCHIVE_ONLY": 0,
                "EXCLUDE": 1,
                "UNSUPPORTED": 0,
            },
            "physical_objects": [first, second, manifest_item],
        }
    )
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    golden_path = gate_fixtures._write_golden_spec(
        tmp_path,
        expected_final="REVIEW_REQUIRED",
        expected_authority="BLOCKED_NOT_CLEARED",
    )
    golden = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
    golden["positive_controls"].append(
        {
            **golden["positive_controls"][0],
            "control_id": "pos_02",
            "sha256_prefix": second_content[:12],
        }
    )
    golden["coverage_summary"].update(
        {"total_controls": 3, "positive_controls": 2}
    )
    golden_path.write_text(yaml.safe_dump(golden, sort_keys=False), encoding="utf-8")

    currentness_path = tmp_path / "currentness.yml"
    currentness_path.write_text(
        yaml.safe_dump(
            {
                "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
                "corpus_manifest_sha256": manifest_sha256,
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    return (
        catalog_path,
        rights_path,
        pii_path,
        routing_path,
        golden_path,
        manifest_sha256,
        (first_content, second_content),
    )


def _write_crypto_authorization_release(
    governed_root: Path,
    *,
    manifest_sha256: str,
    contents: tuple[str, str],
    now: datetime,
) -> tuple[Path, AuthorizationSetV1, ReleaseScopePlacementGitInputs]:
    scopes = (
        _v2_scope(
            collection="rag_nexus_math_terminale_tc",
            matiere="mathematiques",
        ),
        _v2_scope(
            collection="rag_nexus_philo_terminale_tc",
            matiere="philosophie",
        ),
    )
    profile_documents: list[dict[str, object]] = []
    profiles: list[VerifiedProfileFactV1] = []
    profile_sources = (
        "profiles/h2-e2e-mathematiques.yml",
        "profiles/h2-e2e-philosophie.yml",
    )
    for index, scope in enumerate(scopes, start=1):
        document = dict(gate_fixtures._v2_profile_document())
        document["scope"] = scope.model_dump(mode="json")
        document["title"] = f"Profil E2E V2 {index}"
        profile = CollectionProfile.model_validate(document)
        fingerprint = collection_profile_fingerprint(profile)
        profile_documents.append(document)
        profiles.append(
            VerifiedProfileFactV1(
                profile_id=str(scope.collection),
                profile_version=profile.profile_version,
                profile_fingerprint=fingerprint,
                scope=scope,
            )
        )

    profile_manifest = {
        "manifest_version": "1",
        "provenance": "rehearsal cryptographique H2 V2",
        "generated_at": _utc_text(now),
        "profiles": [
            {
                "collection": profile.profile_id,
                "profile_version": profile.profile_version,
                "fingerprint": profile.profile_fingerprint,
                "approved_by": "test-authority",
                "approved_at": _utc_text(now),
            }
            for profile in profiles
        ],
    }
    profile_manifest_digest = profile_manifest_fingerprint(profile_manifest)
    placement = ReleaseScopePlacementV1.build(
        profile_manifest_digest=profile_manifest_digest,
        placements=tuple(
            ReleaseScopePlacementEntryV1(
                content_sha256=content,
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                profile_fingerprint=profile.profile_fingerprint,
                scope=profile.scope,
            )
            for content, profile in zip(contents, profiles, strict=True)
        ),
    )

    members: list[AuthorizationSetMemberV1] = []
    authorization_ids = ("release-mathematiques", "release-philosophie")
    for authorization_id, content, profile in zip(
        authorization_ids, contents, profiles, strict=True
    ):
        authority_document = dict(gate_fixtures._valid_authority_document())
        authority_document.update(
            {
                "authorization_id": authorization_id,
                "manifest_digest": profile_manifest_digest,
                "profile_id": profile.profile_id,
                "profile_version": profile.profile_version,
                "profile_fingerprint": profile.profile_fingerprint,
                "allowed_content_sha256": [content],
                "scope": profile.scope.model_dump(mode="json"),
                "valid_from": _utc_text(now - timedelta(days=30)),
                "valid_until": _utc_text(now + timedelta(days=90)),
            }
        )
        authority = ScopeAuthorizationArtifactV2.model_validate(authority_document)
        binding_path = gate_fixtures._write_review_binding(
            governed_root,
            authority_document,
            filename=f"{authorization_id}.binding.json",
            submitted_at=_utc_text(now - timedelta(days=6)),
            verified_at=_utc_text(now - timedelta(days=5)),
            expires_at=_utc_text(now + timedelta(days=30)),
        )
        member = AuthorizationSetMemberV1.model_validate(
            {
                "authorization_id": authorization_id,
                "authorization_digest": authority.digest(),
                "review_binding_digest": hashlib.sha256(
                    binding_path.read_bytes()
                ).hexdigest(),
                "scope": profile.scope,
                "scope_digest": scope_digest(profile.scope),
                "allowed_content_sha256": [content],
                "allowed_content_count": 1,
                "allowed_content_set_sha256": content_set_digest([content]),
                "valid_from": authority.valid_from,
                "valid_until": authority.valid_until,
            }
        )
        authorization_path = governed_root / member.authorization_path
        authorization_path.parent.mkdir(parents=True, exist_ok=True)
        authorization_path.write_bytes(authority.canonical_bytes())
        canonical_binding_path = governed_root / member.review_binding_path
        canonical_binding_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_binding_path.write_bytes(binding_path.read_bytes())
        members.append(member)

    authorization_set = AuthorizationSetV1.build(
        members=members,
        corpus_manifest_sha256=manifest_sha256,
        profile_manifest_digest=profile_manifest_digest,
        release_scope_placement_digest=placement.digest(),
        authority_required_content_sha256=contents,
    )
    set_path = governed_root / "governance/authorization-sets/h2-e2e.json"
    set_path.parent.mkdir(parents=True, exist_ok=True)
    set_path.write_bytes(authorization_set.canonical_bytes())

    paths = {
        "matrix": "governance/profile-matrix.json",
        "placements": "governance/placements.json",
        "registry": "governance/release-registry.json",
        "contents": "governance/expected-contents.txt",
        "profiles": "governance/verified-profiles.json",
        "manifest": "governance/profile-manifest.yml",
    }

    def write(relative: str, raw: bytes) -> None:
        path = governed_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    matrix = [
        {
            "partition_id": f"P{index:02d}",
            "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
            "content_count": 1,
            "content_sha256": [content],
            "profile_decision_required": False,
            "evidence_sources": [source_path],
            "dimensions": {
                name: {
                    "value": value,
                    "grounded": True,
                    "source_of_truth": source_path,
                }
                for name, value in profile.scope.model_dump(mode="json").items()
            },
        }
        for index, (content, profile, source_path) in enumerate(
            zip(contents, profiles, profile_sources, strict=True), start=1
        )
    ]
    accepted_placements = [
        {
            "content_sha256": content,
            "release_id": "release-h2-v2-e2e",
            "collection": profile.profile_id,
            "profile_version": profile.profile_version,
        }
        for content, profile in zip(contents, profiles, strict=True)
    ]
    release_registry = {
        "registry_version": "1",
        "school_year": "2026-2027",
        "releases": [
            {
                "release_id": "release-h2-v2-e2e",
                "collections": [profile.profile_id for profile in profiles],
            }
        ],
    }
    verified_profiles = {
        "profile_manifest_digest": profile_manifest_digest,
        "profiles": [
            {**profile.model_dump(mode="json"), "source_path": source_path}
            for profile, source_path in zip(profiles, profile_sources, strict=True)
        ],
    }
    json_bytes = lambda value: (  # noqa: E731 - fixture locale compacte
        json.dumps(value, sort_keys=True, indent=2) + "\n"
    ).encode()
    write(paths["matrix"], json_bytes(matrix))
    write(paths["placements"], json_bytes(accepted_placements))
    write(paths["registry"], json_bytes(release_registry))
    write(paths["contents"], "".join(f"{value}\n" for value in contents).encode())
    write(paths["profiles"], json_bytes(verified_profiles))
    write(paths["manifest"], yaml.safe_dump(profile_manifest, sort_keys=True).encode())
    for source_path, document in zip(
        profile_sources, profile_documents, strict=True
    ):
        write(source_path, yaml.safe_dump(document, sort_keys=True).encode())

    subprocess.run(["git", "init", "-q"], cwd=governed_root, check=True)
    subprocess.run(["git", "add", "."], cwd=governed_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Nexus Tests",
            "-c",
            "user.email=tests@nexus.invalid",
            "commit",
            "-qm",
            "two-authority exact release",
        ],
        cwd=governed_root,
        check=True,
    )
    source_tree_sha = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=governed_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return (
        set_path,
        authorization_set,
        ReleaseScopePlacementGitInputs(
            repository_root=governed_root,
            source_tree_sha=source_tree_sha,
            profile_proposal_matrix_path=paths["matrix"],
            accepted_placements_path=paths["placements"],
            release_registry_path=paths["registry"],
            expected_contents_path=paths["contents"],
            verified_profiles_path=paths["profiles"],
            profile_manifest_path=paths["manifest"],
        ),
    )


def _generate_crypto_v2_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    revoked: list[str] | None = None,
) -> tuple[AuthorizationSetV1, CoverageReport]:
    now = datetime.now(UTC)
    governed_root = gate_fixtures._install_governed_root(
        monkeypatch,
        tmp_path,
        revoked=revoked,
    )
    (
        catalog_path,
        rights_path,
        pii_path,
        routing_path,
        golden_path,
        manifest_sha256,
        contents,
    ) = _write_two_content_gate_inputs(tmp_path)
    set_path, authorization_set, release_scope_inputs = (
        _write_crypto_authorization_release(
            governed_root,
            manifest_sha256=manifest_sha256,
            contents=contents,
            now=now,
        )
    )
    manifest_path = tmp_path / "00_ADMIN/SHA256SUMS.txt"
    currentness_path = tmp_path / "currentness.yml"
    report = generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        manifest_path=manifest_path,
        expected_manifest_sha256=manifest_sha256,
        currentness_verification_path=currentness_path,
        authorization_set_path=set_path,
        authorization_material_root=governed_root,
        release_scope_git_inputs=release_scope_inputs,
        authority_environment="production",
        expected_total=3,
    )
    return authorization_set, report


def _build_v2_bundle(
    authorization_set: AuthorizationSetV1,
    campaign: CorpusCampaignV2,
    coverage_raw: bytes,
    *,
    merge_sha: str,
    merge_tree_sha: str,
) -> H2EvidenceBundleV2:
    return build_h2_evidence_bundle_v2(
        campaign_raw=campaign.canonical_bytes(),
        authorization_set_raw=authorization_set.canonical_bytes(),
        h2_coverage_evidence_raw=coverage_raw,
        review_view_sha256="5" * 64,
        repository="cyranoaladin/RAG",
        pull_request_number=127,
        pr_head_sha="1" * 40,
        pr_head_tree_sha=merge_tree_sha,
        merge_sha=merge_sha,
        merge_tree_sha=merge_tree_sha,
        workflow_path=".github/workflows/_produce-h2-evidence.yml",
        run_id="456",
        run_attempt=1,
    )


class TestE2EV2MultiAuthorizationRelease:
    def test_report_to_h2_bundle_to_promotion_binds_two_crypto_scopes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        authorization_set, report = _generate_crypto_v2_report(
            tmp_path,
            monkeypatch,
        )
        campaign = _v2_campaign(authorization_set).model_copy(
            update={
                "expected_catalog_digest": report.input_files["catalog"],
                "routing_config_digest": report.input_files["routing"],
                "rights_config_digest": report.input_files["rights"],
                "pii_config_digest": report.input_files["pii"],
                "golden_spec_digest": report.input_files["golden"],
            }
        )

        assert report.authorization_count == 2
        assert len({scope_digest(member.scope) for member in authorization_set.members}) == 2
        assert report.authorization_set_digest == authorization_set.digest()
        assert report.input_files["authorization_set"] == authorization_set.digest()
        assert report.authority_required_count == report.authority_covered_count == 2
        assert report.final_ingest_count == 2
        assert report.h2_coverage_gate_pass is True
        assert report.authority_review_bindings_verified is True
        assert report.authority_revocations_checked is True

        coverage = report_to_h2_coverage_evidence_v2(report)
        bundle = _build_v2_bundle(
            authorization_set,
            campaign,
            coverage.canonical_bytes(),
            merge_sha=report.git_commit,
            merge_tree_sha=report.release_scope_source_tree_sha,
        )
        verify_h2_evidence_bundle_v2_freshness(
            bundle,
            now=coverage.generated_at,
        )
        promotion = PromotionEvidenceV2.model_validate(
            PromotionEvidenceV2.fields_from_h2_bundle(
                bundle,
                image_provenance_run_id=789,
                image_provenance_run_attempt=1,
                promotion_workflow_path=".github/workflows/promote.yml",
                promotion_run_id=987,
                promotion_run_attempt=1,
                promotion_workflow_ref="refs/heads/main",
            )
        )
        verify_promotion_evidence_v2(promotion, h2_bundle=bundle)

        wrong_coverage_inputs = dict(coverage.input_file_digests)
        wrong_coverage_inputs["authorization_set"] = "f" * 64
        wrong_coverage = coverage.model_copy(
            update={
                "authorization_set_digest": "f" * 64,
                "input_file_digests": wrong_coverage_inputs,
            }
        )
        with pytest.raises(ReleaseEvidenceError, match="authorization_set_digest"):
            _build_v2_bundle(
                authorization_set,
                campaign,
                wrong_coverage.canonical_bytes(),
                merge_sha=report.git_commit,
                merge_tree_sha=report.release_scope_source_tree_sha,
            )

        substituted_promotion = promotion.model_copy(
            update={"h2_evidence_bundle_digest": "f" * 64}
        )
        with pytest.raises(ReleaseEvidenceError, match="h2_evidence_bundle_digest"):
            verify_promotion_evidence_v2(
                substituted_promotion,
                h2_bundle=bundle,
            )

    def test_real_global_verifier_refuses_one_revoked_member(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with pytest.raises(Exception, match="(?i)revoked|revocation"):
            _generate_crypto_v2_report(
                tmp_path,
                monkeypatch,
                revoked=["release-philosophie"],
            )
