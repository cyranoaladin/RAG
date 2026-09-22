"""Lot CV — le producteur émet MULTILEVEL_ARTIFACT_CURRENTNESS_V3 (ADR-0059).

Ce que ces épreuves fixent :

- la disposition d'un contenu vient de la matrice de servabilité gouvernée,
  produite sous la politique appliquée ; le producteur la RECALCULE depuis les
  faits que la matrice a utilisés, avec la même dérivation, et refuse tout
  désaccord — il ne la décide jamais ;
- un instantané ne porte aucun fait de vérification réseau, et un audit qui se
  déclare non vérifié ne peut pas en fournir ;
- une entrée par CONTENU, jamais par placement, et un inventaire dont les
  comptes sont ceux que le chargeur recompte ;
- le catalogue scellé dit ce qui a été prouvé : `current` pour une identité
  d'octets, `official_snapshot` pour un instantané, rien d'autre.

Fixtures synthétiques et petites : ni réseau, ni miroir PDF.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from rag_pedago.governance import currentness_disposition as politique_mod

ROOT = Path(__file__).resolve().parents[3]
MATRIX_SCRIPT = ROOT / "services/rag-pedago/scripts/construire_matrice_servabilite.py"
REAL_MATRIX = ROOT / "docs/reports/handoff/servability_matrix_v1.json"
REAL_EXCLUSION_REGISTRY = (
    ROOT / "docs/reports/evidence/release_currentness_exclusion_registry.json"
)
SERVED_RELEASE_ROOT = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"

SHA_A = "a" * 64
SHA_B = "b" * 64
COLLECTIONS = (
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
)
LISTING_URL = "https://eduscol.education.gouv.fr/1234/ressources-nsi"
DOWNLOAD_URL = "https://eduscol.education.gouv.fr/sites/default/files/document/nsi.pdf"
RELEASE_ID = "production-profile-gate-2026-2027-lot-cv-test"

V3_DOCUMENT_KEYS = {
    "evidence_kind",
    "school_year",
    "candidate_inventory_sha256",
    "corpus_manifest_sha256",
    "sealed_catalog_sha256",
    "placement_catalog_sha256",
    "catalog_delta_sha256",
    "effective_catalog_authority_sha256",
    "currentness_audit_sha256",
    "decision_basis",
    "currentness_policy_id",
    "currentness_policy_sha256",
    "servability_matrix_sha256",
    "counts",
    "partition",
    "artifacts",
}
V3_ENTRY_KEYS = {
    "content_sha256",
    "exact_path",
    "collections",
    "placement_facts",
    "current_for_school_year",
    "currentness_disposition",
    "source_status",
    "provenance_url",
    "fallback_conditions",
    "effective_currentness",
    "current_source_listing_url",
    "current_download_url",
    "current_download_sha256",
    "byte_identity",
    "reason_codes",
    "drive_modified_time",
}
DISPOSITIONS = (
    "VERIFIED_CURRENT",
    "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE",
    "NOT_CURRENT_DECLARED_BY_SOURCE",
    "UNKNOWN",
)
VERIFICATION_FACTS = (
    "effective_currentness",
    "current_source_listing_url",
    "current_download_url",
    "current_download_sha256",
    "byte_identity",
)
FALLBACK_CONDITIONS = {
    "OFFICIAL_INSTITUTIONAL_PROVENANCE",
    "CONTENT_SHA_PROVENANCE_MATCH",
    "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE",
    "NO_KNOWN_SUPERSEDING_CONFLICT",
}


def _builder() -> Any:
    from conftest import load_producer

    return load_producer()


def _matrix_module() -> Any:
    from conftest import load_script_module

    return load_script_module(MATRIX_SCRIPT, "construire_matrice_servabilite")


def _rows(sha: str = SHA_A) -> list[dict[str, Any]]:
    """Un contenu, deux placements : la population qui a produit 486 pour 319."""
    common = {
        "content_sha256": sha,
        "physical_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/commun.pdf",
        "drive_file_id": "drive-id",
        "drive_modified_time": "2026-08-04T00:00:00Z",
        "drive_size": "1024",
        "source_url": LISTING_URL,
        "current_download_url": DOWNLOAD_URL,
        "title": "Ressource commune",
        "external_document_type": "ressource",
        "external_subject": "nsi",
        "year": "2026",
        "source_evidence": "synthetic",
    }
    return [
        {
            **common,
            "collection": collection,
            "source_placement_id": f"placement-{sha[:4]}-{index}",
            "external_level": "premiere" if index == 0 else "terminale",
            "external_scope": "lycee/general/nsi",
            "partition_id": f"partition-{index}",
        }
        for index, collection in enumerate(COLLECTIONS)
    ]


def _matrix_row(sha: str = SHA_A, **overrides: Any) -> dict[str, Any]:
    row = {
        "content_sha256": sha,
        "provenance": "URL_EVIDENCE_FOUND",
        "program": "UNKNOWN",
        "currentness": "NEEDS_SECONDARY_EVIDENCE",
        "pii": "PII_CLEARED_OR_NOT_SCANNED",
        "indexability": "INDEXABLE",
        "source_role": "INSTITUTIONAL_PUBLICATION",
        "currentness_disposition": "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE",
        "verdict": "CANDIDATE_NO_BLOCKING_DIMENSION",
    }
    row.update(overrides)
    return row


def _write_matrix(tmp_path: Path, rows: list[dict[str, Any]]) -> tuple[Path, str]:
    document = {
        "kind": "NEXUS-SERVABILITY-MATRIX-V1",
        "SERVABILITY_ROWS_TOTAL": len(rows),
        "rows": rows,
    }
    path = tmp_path / "servability_matrix.json"
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _authority(tmp_path: Path, rows: list[dict[str, Any]] | None = None) -> Any:
    path, sha = _write_matrix(tmp_path, rows if rows is not None else [_matrix_row()])
    return _builder().load_governed_currentness_authority(path, sha)


def _inventory(builder: Any, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    delta, effective = builder._catalog_documents(rows)
    inventory = builder._candidate_inventory(rows, delta=delta, effective=effective)
    return inventory, hashlib.sha256(builder.canonical_json_bytes(inventory)).hexdigest()


def _unverified_audit(builder: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    audit, network_rows = builder.resolve_currentness_network_audit(
        rows,
        verify_official_downloads=False,
        release_id=RELEASE_ID,
        source_unreachable=True,
    )
    assert network_rows == []
    return audit


def _verified_audit(builder: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    network_rows = builder._expected_currentness_network_rows(rows)
    return builder._currentness_network_audit_document(network_rows, placement_rows=rows)


def _evidence(
    tmp_path: Path,
    *,
    rows: list[dict[str, Any]] | None = None,
    matrix_rows: list[dict[str, Any]] | None = None,
    audit: dict[str, Any] | None = None,
    inventory_mutation: Any = None,
    exclusion_registry: Any = None,
) -> dict[str, Any]:
    builder = _builder()
    rows = rows if rows is not None else _rows()
    inventory, inventory_sha = _inventory(builder, rows)
    if inventory_mutation is not None:
        inventory_mutation(inventory)
    _audit, evidence = builder._currentness_documents(
        rows,
        inventory=inventory,
        inventory_sha256=inventory_sha,
        network_audit=audit if audit is not None else _unverified_audit(builder, rows),
        authority=_authority(tmp_path, matrix_rows),
        exclusion_registry=exclusion_registry,
    )
    return evidence


# --- une seule dérivation du cas d'actualité ---------------------------------


def test_the_matrix_producer_and_the_builder_share_one_policy_case_derivation() -> None:
    """Deux traductions d'une ligne en cas d'actualité finiraient par diverger :
    la matrice et le producteur appellent la MÊME fonction du plan de contrôle."""
    matrix = _matrix_module()
    source = MATRIX_SCRIPT.read_text(encoding="utf-8")

    assert matrix.cas_depuis_ligne_de_matrice is politique_mod.cas_depuis_ligne_de_matrice
    assert "def _cas_d_actualite" not in source
    builder_source = Path(_builder().__file__).read_text(encoding="utf-8")
    assert "cas_depuis_ligne_de_matrice(" in builder_source


def test_fallback_conditions_are_the_ones_the_policy_evaluates() -> None:
    politique = politique_mod.charger_politique()
    cas = politique_mod.cas_depuis_ligne_de_matrice(_matrix_row(currentness="CURRENT_DECLARED"))

    conditions = politique_mod.conditions_de_repli(cas)

    assert set(conditions) == FALLBACK_CONDITIONS
    assert all(value is True for value in conditions.values())
    assert politique_mod.disposition_actualite(cas, politique) == (
        "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"
    )
    archive = politique_mod.cas_depuis_ligne_de_matrice(
        _matrix_row(currentness="ARCHIVE_DECLARED")
    )
    assert politique_mod.conditions_de_repli(archive)[
        "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE"
    ] is False


# --- autorité injectée, fail-closed ------------------------------------------


def test_the_matrix_and_its_digest_are_required(tmp_path: Path) -> None:
    builder = _builder()
    path, sha = _write_matrix(tmp_path, [_matrix_row()])

    with pytest.raises(ValueError, match="servability matrix"):
        builder.load_governed_currentness_authority(None, sha)
    with pytest.raises(ValueError, match="sha256"):
        builder.load_governed_currentness_authority(path, None)
    with pytest.raises(ValueError, match="servability matrix"):
        builder.load_governed_currentness_authority(tmp_path / "absente.json", sha)


def test_a_mismatched_matrix_digest_is_refused(tmp_path: Path) -> None:
    builder = _builder()
    path, _sha = _write_matrix(tmp_path, [_matrix_row()])

    with pytest.raises(ValueError, match="sha256 mismatch"):
        builder.load_governed_currentness_authority(path, "0" * 64)


def test_a_policy_that_is_not_applied_is_refused(tmp_path: Path) -> None:
    builder = _builder()
    path, sha = _write_matrix(tmp_path, [_matrix_row()])
    document = yaml.safe_load(politique_mod.CHEMIN_POLITIQUE.read_text(encoding="utf-8"))
    document["applied"] = False
    policy = tmp_path / "policy.yml"
    policy.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(politique_mod.PolitiqueNonAppliquee):
        builder.load_governed_currentness_authority(path, sha, policy_path=policy)


def test_the_authority_names_the_bytes_of_the_policy_and_of_the_matrix(
    tmp_path: Path,
) -> None:
    builder = _builder()
    path, sha = _write_matrix(tmp_path, [_matrix_row()])

    authority = builder.load_governed_currentness_authority(path, sha)

    assert authority.matrix_sha256 == sha
    assert authority.policy_sha256 == hashlib.sha256(
        politique_mod.CHEMIN_POLITIQUE.read_bytes()
    ).hexdigest()
    assert authority.policy_id == "NEXUS-RAG-CURRENTNESS-POLICY-V1"


def test_a_matrix_with_two_rows_for_one_content_is_refused(tmp_path: Path) -> None:
    builder = _builder()
    path, sha = _write_matrix(tmp_path, [_matrix_row(), _matrix_row()])

    with pytest.raises(ValueError, match="duplicated"):
        builder.load_governed_currentness_authority(path, sha)


# --- le document V3 -----------------------------------------------------------


def test_snapshot_evidence_has_the_exact_v3_shape_and_no_verification_fact(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    authority = _authority(tmp_path)

    assert set(evidence) == V3_DOCUMENT_KEYS
    assert evidence["evidence_kind"] == "MULTILEVEL_ARTIFACT_CURRENTNESS_V3"
    assert evidence["currentness_policy_id"] == "NEXUS-RAG-CURRENTNESS-POLICY-V1"
    assert evidence["currentness_policy_sha256"] == authority.policy_sha256
    assert evidence["servability_matrix_sha256"] == authority.matrix_sha256
    assert len(evidence["artifacts"]) == 1
    entry = evidence["artifacts"][0]
    assert set(entry) == V3_ENTRY_KEYS
    assert entry["currentness_disposition"] == "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"
    for fact in VERIFICATION_FACTS:
        assert entry[fact] is None, fact
    assert entry["fallback_conditions"] == {name: True for name in FALLBACK_CONDITIONS}
    assert entry["source_status"] == "NEEDS_SECONDARY_EVIDENCE"
    assert entry["provenance_url"] == LISTING_URL
    assert entry["current_for_school_year"] == "2026-2027"
    assert entry["drive_modified_time"] == "2026-08-04T00:00:00Z"


def test_one_entry_per_content_whatever_the_number_of_placements(tmp_path: Path) -> None:
    rows = _rows(SHA_A) + [_rows(SHA_B)[0]]
    evidence = _evidence(
        tmp_path, rows=rows, matrix_rows=[_matrix_row(SHA_A), _matrix_row(SHA_B)]
    )

    assert [entry["content_sha256"] for entry in evidence["artifacts"]] == [SHA_A, SHA_B]
    first = evidence["artifacts"][0]
    assert first["collections"] == sorted(COLLECTIONS)
    assert len(first["placement_facts"]) == 2
    assert {fact["source_placement_id"] for fact in first["placement_facts"]} == {
        row["source_placement_id"] for row in _rows(SHA_A)
    }


def test_counts_and_partition_are_keyed_by_the_four_dispositions(tmp_path: Path) -> None:
    rows = _rows(SHA_A) + [_rows(SHA_B)[0]]
    evidence = _evidence(
        tmp_path, rows=rows, matrix_rows=[_matrix_row(SHA_A), _matrix_row(SHA_B)]
    )

    assert evidence["counts"] == {
        "unique_artifacts": 2,
        "evaluated": 2,
        "VERIFIED_CURRENT": 0,
        "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": 2,
        "NOT_CURRENT_DECLARED_BY_SOURCE": 0,
        "UNKNOWN": 0,
    }
    assert evidence["partition"] == {
        "VERIFIED_CURRENT": [],
        "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": [SHA_A, SHA_B],
        "NOT_CURRENT_DECLARED_BY_SOURCE": [],
        "UNKNOWN": [],
    }
    for disposition in DISPOSITIONS:
        assert evidence["counts"][disposition] == len(evidence["partition"][disposition])
        assert evidence["partition"][disposition] == sorted(
            entry["content_sha256"]
            for entry in evidence["artifacts"]
            if entry["currentness_disposition"] == disposition
        )


def test_a_verification_fact_under_an_unverified_audit_is_refused(tmp_path: Path) -> None:
    """Le défaut de V2 : un audit « non vérifié » livré avec des identités
    d'octets. Le producteur ne choisit pas lequel croire : il refuse."""
    builder = _builder()
    rows = _rows()
    audit = _unverified_audit(builder, rows)
    audit["artifacts"] = builder._expected_currentness_network_rows(rows)

    with pytest.raises(ValueError, match="unverified"):
        _evidence(tmp_path, rows=rows, audit=audit)


def test_a_byte_identity_proven_by_a_verified_audit_is_verified_current(
    tmp_path: Path,
) -> None:
    builder = _builder()
    rows = _rows()
    evidence = _evidence(tmp_path, rows=rows, audit=_verified_audit(builder, rows))

    entry = evidence["artifacts"][0]
    assert set(entry) == V3_ENTRY_KEYS
    assert entry["currentness_disposition"] == "VERIFIED_CURRENT"
    assert entry["effective_currentness"] == "actuel"
    assert entry["byte_identity"] is True
    assert entry["current_download_sha256"] == SHA_A
    assert entry["current_download_url"] == DOWNLOAD_URL
    assert entry["current_source_listing_url"] == LISTING_URL
    assert entry["fallback_conditions"] is None
    assert evidence["partition"]["VERIFIED_CURRENT"] == [SHA_A]


def test_an_archive_source_status_is_never_a_snapshot(tmp_path: Path) -> None:
    """Une matrice qui déclarerait instantané un contenu archivé par la source
    est contredite par la politique elle-même : refus."""
    forged = _matrix_row(currentness="ARCHIVE_DECLARED")

    with pytest.raises(ValueError, match="disagrees"):
        _evidence(tmp_path, matrix_rows=[forged])


def test_a_matrix_disposition_the_policy_does_not_derive_is_refused(
    tmp_path: Path,
) -> None:
    forged = _matrix_row(provenance="NO_URL_EVIDENCE", currentness="NO_CATALOGUE_STATUS")

    with pytest.raises(ValueError, match="disagrees"):
        _evidence(tmp_path, matrix_rows=[forged])


def test_a_content_absent_from_the_matrix_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absent from the servability matrix"):
        _evidence(tmp_path, matrix_rows=[_matrix_row(SHA_B)])


def test_a_content_the_matrix_does_not_declare_servable_is_refused(
    tmp_path: Path,
) -> None:
    archived = _matrix_row(
        currentness="ARCHIVE_DECLARED",
        currentness_disposition="NOT_CURRENT_DECLARED_BY_SOURCE",
        verdict="BLOCKED_NOT_CURRENT_BY_SOURCE",
    )

    with pytest.raises(ValueError, match="not servable"):
        _evidence(tmp_path, matrix_rows=[archived])


def test_an_excluded_content_cannot_reach_the_evidence(tmp_path: Path) -> None:
    registry = SimpleNamespace(excluded_contents=frozenset({SHA_A}))

    with pytest.raises(ValueError, match="exclusion registry"):
        _evidence(tmp_path, exclusion_registry=registry)


def test_divergent_provenance_urls_for_one_content_are_refused(tmp_path: Path) -> None:
    def diverge(inventory: dict[str, Any]) -> None:
        inventory["collections"][1]["candidates"][0]["placements"][0]["source_url"] = (
            "https://eduscol.education.gouv.fr/9999/autre"
        )

    with pytest.raises(ValueError, match="provenance"):
        _evidence(tmp_path, inventory_mutation=diverge)


def test_a_snapshot_outside_the_official_hosts_is_refused(tmp_path: Path) -> None:
    rows = _rows()
    for row in rows:
        row["source_url"] = "https://example.org/copie"

    with pytest.raises(ValueError, match="provenance"):
        _evidence(tmp_path, rows=rows)


# --- inventaire : les comptes que le chargeur recompte ------------------------


def test_inventory_counts_are_exact_on_a_multi_placement_population() -> None:
    builder = _builder()
    rows = _rows(SHA_A) + [_rows(SHA_B)[0]]

    inventory, _sha = _inventory(builder, rows)

    assert inventory["counts"] == {
        "target_collections": 2,
        "unique_artifacts": 2,
        "placements": 3,
        "physical_objects": 2,
        "multi_placement_artifacts": 1,
    }
    per_collection = {c["collection"]: c["counts"] for c in inventory["collections"]}
    assert per_collection == {
        COLLECTIONS[0]: {"unique_artifacts": 2, "placements": 2},
        COLLECTIONS[1]: {"unique_artifacts": 1, "placements": 1},
    }
    pending = inventory["candidate_partition"]["exact_grade_gate_pending"]
    assert pending == [SHA_A, SHA_B]


def test_a_copied_inventory_is_recounted_and_its_exclusions_removed() -> None:
    """La voie de répétition recopiait l'inventaire de la release source : 486
    `unique_artifacts` pour 319 contenus, `multi_placement_artifacts: 0`, et
    une partition qui listait deux fois 167 contenus."""
    builder = _builder()
    rows = _rows(SHA_A) + _rows(SHA_B)
    source, _sha = _inventory(builder, rows)
    source["counts"] = {
        "target_collections": 2,
        "unique_artifacts": 4,
        "placements": 4,
        "physical_objects": 4,
        "multi_placement_artifacts": 0,
    }
    source["candidate_partition"]["exact_grade_gate_pending"] = [SHA_A, SHA_A, SHA_B, SHA_B]

    recounted = builder._recount_candidate_inventory(source, excluded=frozenset({SHA_B}))

    assert recounted["counts"] == {
        "target_collections": 2,
        "unique_artifacts": 1,
        "placements": 2,
        "physical_objects": 1,
        "multi_placement_artifacts": 1,
    }
    assert recounted["candidate_partition"]["exact_grade_gate_pending"] == [SHA_A]
    for collection in recounted["collections"]:
        assert {c["content_sha256"] for c in collection["candidates"]} == {SHA_A}
        assert collection["counts"] == {"unique_artifacts": 1, "placements": 1}
    untouched = {k: v for k, v in source.items() if k not in {"counts", "collections", "candidate_partition", "collection_partition"}}
    assert {k: recounted[k] for k in untouched} == untouched


# --- le catalogue scellé dit ce qui a été prouvé ------------------------------


def test_served_currentness_is_derived_from_the_v3_disposition(tmp_path: Path) -> None:
    builder = _builder()
    snapshot = _evidence(tmp_path)
    verified = _evidence(tmp_path, audit=_verified_audit(builder, _rows()))

    assert builder.served_currentness_from_evidence(snapshot) == {
        SHA_A: builder.ServedCurrentness("official_snapshot", LISTING_URL)
    }
    assert builder.served_currentness_from_evidence(verified) == {
        SHA_A: builder.ServedCurrentness("current", DOWNLOAD_URL)
    }


@pytest.mark.parametrize("disposition", ["NOT_CURRENT_DECLARED_BY_SOURCE", "UNKNOWN"])
def test_an_unpublishable_disposition_never_reaches_the_catalogue(
    tmp_path: Path, disposition: str
) -> None:
    builder = _builder()
    evidence = copy.deepcopy(_evidence(tmp_path))
    entry = evidence["artifacts"][0]
    entry["currentness_disposition"] = disposition

    with pytest.raises(ValueError, match="never reaches the catalogue"):
        builder.served_currentness_from_evidence(evidence)

    evidence["evidence_kind"] = "MULTILEVEL_ARTIFACT_CURRENTNESS_V2"
    with pytest.raises(ValueError, match="V3"):
        builder.served_currentness_from_evidence(evidence)


def test_a_placement_refuses_a_currentness_the_product_does_not_know() -> None:
    builder = _builder()
    profile = SimpleNamespace(
        scope=SimpleNamespace(
            audience=(SimpleNamespace(value="both"),),
            candidat=SimpleNamespace(value="both"),
            collection=COLLECTIONS[0],
            matiere="nsi",
            niveau=SimpleNamespace(value="premiere"),
            programme_version="BOEN",
            school_year="2026-2027",
            tenant="libre_premiere",
            visibility="internal",
            voie=SimpleNamespace(value="generale"),
        )
    )
    row = _rows()[0]
    for currentness in ("current", "official_snapshot"):
        placement = builder._placement(
            row,
            profile=profile,
            status="specialite",
            include_artifact_id=True,
            currentness=currentness,
        )
        assert placement["currentness"] == currentness
    with pytest.raises(ValueError, match="currentness"):
        builder._placement(
            row,
            profile=profile,
            status="specialite",
            include_artifact_id=True,
            currentness="actuel",
        )


def test_the_catalogue_carries_the_snapshot_and_cites_its_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _builder()
    rows = _rows()
    served = builder.served_currentness_from_evidence(_evidence(tmp_path, rows=rows))
    profiles = {
        collection: SimpleNamespace(
            profile_version="2.0.0",
            scope=SimpleNamespace(
                audience=(SimpleNamespace(value="both"),),
                candidat=SimpleNamespace(value="both"),
                collection=collection,
                matiere="nsi",
                niveau=SimpleNamespace(value="premiere" if index == 0 else "terminale"),
                programme_version="BOEN",
                school_year="2026-2027",
                tenant="libre_premiere" if index == 0 else "libre_terminale",
                visibility="internal",
                voie=SimpleNamespace(value="generale"),
            ),
        )
        for index, collection in enumerate(COLLECTIONS)
    }
    monkeypatch.setattr(builder, "profile_fingerprint", lambda _profile: "e" * 64)
    release_root = tmp_path / "profile_gate"
    documents = builder._release_topology_documents(
        rows,
        profiles=profiles,
        profile_manifest_digest="d" * 64,
        collection_config={c: {"statut": "specialite"} for c in COLLECTIONS},
        preflight_by_sha={
            SHA_A: {
                "content_sha256": SHA_A,
                "source_path": rows[0]["physical_path"],
                "page_count": 1,
                "ignored_empty_pages": [],
                "chunks": [
                    {
                        "chunk_index": 0,
                        "chunk_id": "1" * 64,
                        "chunk_sha256": "2" * 64,
                        "page_start": 1,
                        "page_end": 1,
                    }
                ],
            }
        },
        type_doc_mapping={"ressource": "ressource_officielle"},
        authorities={},
        models={},
        release_root=release_root,
        release_id=RELEASE_ID,
        school_year="2026-2027",
        served_currentness=served,
    )
    registry = json.loads(documents[release_root / "artifacts.release.json"])
    assert registry["artifacts"][0]["source_url"] == LISTING_URL
    subjects = [
        json.loads(raw) for path, raw in documents.items() if path.parent.name == "subjects"
    ]
    assert len(subjects) == 2
    assert {
        placement["currentness"] for subject in subjects for placement in subject["placements"]
    } == {"official_snapshot"}

    with pytest.raises(ValueError, match="served currentness"):
        builder._release_topology_documents(
            rows,
            profiles=profiles,
            profile_manifest_digest="d" * 64,
            collection_config={c: {"statut": "specialite"} for c in COLLECTIONS},
            preflight_by_sha={},
            type_doc_mapping={"ressource": "ressource_officielle"},
            authorities={},
            models={},
            release_root=release_root,
            release_id=RELEASE_ID,
            school_year="2026-2027",
            served_currentness={},
        )


# --- la voie CLI --------------------------------------------------------------


def test_the_cli_refuses_to_build_without_the_governed_matrix(tmp_path: Path) -> None:
    builder = _builder()
    with pytest.raises(SystemExit):
        builder.main(["--release-mode", "rehearsal", "--dry-run", "--release-id", RELEASE_ID])
    path, _sha = _write_matrix(tmp_path, [_matrix_row()])
    with pytest.raises(SystemExit):
        builder.main(
            [
                "--release-mode",
                "rehearsal",
                "--dry-run",
                "--release-id",
                RELEASE_ID,
                "--servability-matrix",
                str(path),
            ]
        )
    with pytest.raises(ValueError, match="sha256 mismatch"):
        builder.main(
            [
                "--release-mode",
                "rehearsal",
                "--dry-run",
                "--release-id",
                RELEASE_ID,
                "--servability-matrix",
                str(path),
                "--servability-matrix-sha256",
                "0" * 64,
            ]
        )


# --- sur les données réelles : la répétition du candidat profile_gate_v2 ------


def test_the_rehearsal_successor_is_an_honest_snapshot_release() -> None:
    """Rejoue la voie qui a produit `profile_gate_v2`, avec la matrice gouvernée.

    Le candidat historique embarquait une preuve V1 recopiée — 486 × CURRENT à
    côté d'un audit qui dit 0 vérifié — et un inventaire à 486 contenus pour
    319. Son successeur doit dire 315 instantanés, aucun vérifié, et des
    comptes que le chargeur recompte."""
    builder = _builder()
    registry = builder.load_and_validate_exclusion_registry(REAL_EXCLUSION_REGISTRY)
    authority = builder.load_governed_currentness_authority(
        REAL_MATRIX, hashlib.sha256(REAL_MATRIX.read_bytes()).hexdigest()
    )

    documents = builder.build_release(
        release_mode="rehearsal",
        source_release_root=SERVED_RELEASE_ROOT,
        release_id=RELEASE_ID,
        exclusion_registry=registry,
        currentness_authority=authority,
    )
    root = builder.RELEASE_ROOT

    def load(name: str) -> Any:
        return json.loads(documents[root / name])

    evidence = load("currentness_evidence.json")
    inventory = load("candidate_inventory.json")
    audit = load("currentness_network_audit.json")
    aggregate = load("production-profile-gate.release.json")

    assert evidence["evidence_kind"] == "MULTILEVEL_ARTIFACT_CURRENTNESS_V3"
    assert evidence["counts"] == {
        "unique_artifacts": 315,
        "evaluated": 315,
        "VERIFIED_CURRENT": 0,
        "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": 315,
        "NOT_CURRENT_DECLARED_BY_SOURCE": 0,
        "UNKNOWN": 0,
    }
    assert len(evidence["artifacts"]) == 315
    assert all(
        all(entry[fact] is None for fact in VERIFICATION_FACTS)
        for entry in evidence["artifacts"]
    )
    assert evidence["candidate_inventory_sha256"] == hashlib.sha256(
        documents[root / "candidate_inventory.json"]
    ).hexdigest()
    assert evidence["currentness_audit_sha256"] == hashlib.sha256(
        documents[root / "currentness_network_audit.json"]
    ).hexdigest()
    assert audit["currentness_status"] == "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE"
    assert audit["counts"] == {"verified": 0, "digest_mismatch": 0}
    assert audit["artifacts"] == []

    placements = sum(
        len(candidate["placements"])
        for collection in inventory["collections"]
        for candidate in collection["candidates"]
    )
    contents = {
        candidate["content_sha256"]
        for collection in inventory["collections"]
        for candidate in collection["candidates"]
    }
    assert len(contents) == 315
    assert placements == aggregate["expected_counts"]["placements"] == 479
    assert inventory["counts"]["unique_artifacts"] == 315
    assert inventory["counts"]["physical_objects"] == 315
    assert inventory["counts"]["placements"] == 479
    assert inventory["counts"]["multi_placement_artifacts"] > 0
    assert not contents & registry.excluded_contents
    pending = inventory["candidate_partition"]["exact_grade_gate_pending"]
    assert len(pending) == len(set(pending)) == 315

    served = {
        placement["currentness"]
        for path, raw in documents.items()
        if path.parent.name == "subjects"
        for placement in json.loads(raw)["placements"]
    }
    assert served == {"official_snapshot"}
    bindings = json.loads(documents[root / "authority_bindings.json"])["bindings"]
    for name, file_name in (
        ("candidate_inventory_sha256", "candidate_inventory.json"),
        ("currentness_evidence_sha256", "currentness_evidence.json"),
    ):
        digest = hashlib.sha256(documents[root / file_name]).hexdigest()
        assert bindings[name]["file_sha256"] == digest
        assert aggregate["authorities"][name] == digest
