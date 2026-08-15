"""Rehearsal end-to-end réel — chaîne de preuve H2 (PR #109, suivi).

`_produce-h2-evidence.yml` (corrigé en PR #109) enchaîne, contre un vrai
corpus scellé : compilation de catalogue candidat -> vue de revue ->
gate H2 -> assemblage de preuve. PR #109 lui-même n'a exercé que des
tests structurels statiques sur le YAML, jamais les vraies étapes
shell/Python. Ce fichier ferme cet écart : il exécute les vrais
producteurs Python (jamais réimplémentés) contre un corpus synthétique
sûr, jamais des données réelles, jamais une clé de signature réelle,
jamais un accès réseau réel.

**Défaut structurel réel trouvé en construisant ce rehearsal, pas
contourné** : `corpus_catalog_compiler.compile_sealed_catalog`/
`compile_governed_sealed_catalog` ne peuvent JAMAIS produire
`disposition="INGEST"` pour un objet -- même droits et PII au vert, la
disposition finale reste `REVIEW_REQUIRED` (`gate_statuses.authority`
toujours `"BLOCKED_NOT_CLEARED"`), par construction explicite
("L'autorité n'est jamais injectée dans ce compilateur candidat").
`h2b_coverage_report.generate_coverage_report`'s propre boucle de
vérification des invariants de sûreté ne s'exécute que pour les objets
dont `disposition == "INGEST"` (jamais `base_disposition`) -- donc
aucun objet compilé par le vrai compilateur candidat ne peut jamais
atteindre `h2_coverage_gate_pass=True`, même en mode production avec une
autorité et une liaison de revue entièrement valides. Il manque, dans ce
dépôt, une étape automatisée réelle de « republication gouvernée » qui
consommerait un catalogue candidat + une autorité vérifiée pour produire
un catalogue où `disposition="INGEST"` -- cette étape n'existe pas
aujourd'hui (`h2b_coverage_report.py`'s propre suite de tests le
contourne déjà en écrivant à la main un catalogue qui simule cette
sortie future, `_write_real_catalog`). Ce fichier documente et
reproduit ce même contournement établi pour prouver le MÉCANISME du
gate (droits/PII/autorité/révocation/manifeste), tout en prouvant
séparément, avec le VRAI compilateur, que son incapacité structurelle à
promouvoir un candidat est correctement détectée et bloquée par le gate
plutôt que silencieusement ignorée.

Aucune clé privée réelle, aucun accès réseau réel, aucune mutation
pgvector. `LIVE_MUTATIONS_ALLOWED=false`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_h2b_coverage_report as gate_fixtures  # noqa: E402
from nexus_contracts.h2_coverage_evidence import parse_h2_coverage_evidence  # noqa: E402

from rag_pedago.imports.corpus_catalog_compiler import (  # noqa: E402
    Disposition,
    compile_governed_sealed_catalog,
)
from rag_pedago.imports.h2b_coverage_report import (  # noqa: E402
    generate_coverage_report,
    report_to_h2_coverage_evidence,
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
            {"zone_prefix": "01_EDUSCOL_OFFICIEL/", "disposition": "INGEST", "currentness": "actuel"},
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


def test_gate_correctly_blocks_the_real_compilers_honest_output(tmp_path: Path) -> None:
    """Le catalogue RÉEL (jamais promu, §ci-dessus) est ensuite soumis au
    vrai gate H2 -- même en fournissant une autorité par ailleurs valide
    couvrant ce ``content_sha256``, le gate doit refuser de le compter
    comme couvert, puisque le catalogue lui-même ne l'a jamais promu."""
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
    assert report.blocked_ingest_candidates == 1
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
