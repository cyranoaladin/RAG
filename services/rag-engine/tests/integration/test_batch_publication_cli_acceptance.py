"""Test d'acceptation du parcours BATCH, depuis le vrai CLI (lot CU).

Il part de données au **format historique** — celles qu'écrit le point
d'entrée de release scellée — et exige qu'un job batch parcoure la chaîne
jusqu'à l'index produit, puis que son contenu soit récupérable.

Il commence en échec : c'est ce qui montre quel maillon manque réellement.
Chaque refus rencontré est consigné tel quel, jamais maquillé en succès
attendu.

Les autorités utilisées ici sont des **données de test**, explicitement
nommées comme telles. Elles n'autorisent aucune publication réelle.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

if os.environ.get("NEXUS_BATCH_CLI_ACCEPTANCE") != "1":
    pytest.skip(
        "batch CLI acceptance not requested (NEXUS_BATCH_CLI_ACCEPTANCE=1)",
        allow_module_level=True,
    )

#: Périmètre de la release scellée réelle — ses OCTETS servent de matière,
#: ses autorités ne sont pas rejouées comme autorités de publication.
RELEASE_DIR = REPOSITORY_ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate"
)
TRANSFER_MANIFEST = REPOSITORY_ROOT / (
    "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
)
PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("batch-cli-acceptance")


def _run(
    module: str, args: Sequence[str], env: Mapping[str, str], timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    child_env = {
        **os.environ,
        **env,
        "PYTHONPATH": f"{ENGINE_ROOT / 'src'}:{REPOSITORY_ROOT / 'packages/contracts/src'}",
    }
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=child_env,
        cwd=REPOSITORY_ROOT,
        check=False,
    )


def test_les_prerequis_du_banc_sont_reunis() -> None:
    """Un skip n'est pas une exécution : les prérequis sont vérifiés ici."""
    assert RELEASE_DIR.is_dir(), RELEASE_DIR
    assert (RELEASE_DIR / "production-profile-gate.release.json").is_file()
    assert (RELEASE_DIR / "artifacts.release.json").is_file()
    assert TRANSFER_MANIFEST.is_file(), TRANSFER_MANIFEST
    assert PROFILES_DIR.is_dir(), PROFILES_DIR
    assert len(list(PROFILES_DIR.glob("*.yml"))) == 11


def test_le_catalogue_scelle_se_charge_depuis_le_manifeste(
    control_pg: dict[str, str],
) -> None:
    """Maillon 1 — le catalogue vient du fichier que le manifeste nomme."""
    from ingestor.ingestion_control.sealed_release_catalog import (
        load_sealed_release_catalog,
    )

    manifeste = RELEASE_DIR / "production-profile-gate.release.json"
    catalogue = load_sealed_release_catalog(
        RELEASE_DIR,
        expected_release_manifest_sha256=_sha(manifeste),
        transfer_manifest_path=TRANSFER_MANIFEST,
        expected_transfer_manifest_sha256=_sha(TRANSFER_MANIFEST),
    )
    assert len(catalogue) == 315
    assert catalogue.media_type_invariant == "application/pdf"


def test_le_producteur_d_attestation_batch_existe() -> None:
    """Maillon 2 — l'outil qui produit l'artefact de revue batch.

    Le protocole ``LOT42-RELEASE-BATCH-V1`` a son contrat et son stockage.
    Cette épreuve établit si un PRODUCTEUR existe : sans lui, aucune
    attestation batch ne peut être proposée ni enregistrée, et la chaîne
    s'arrête avant le job.
    """
    aide = _run("ingestor.ingestion_worker.attest_publication_cli", ["--help"], {})
    assert aide.returncode == 0, aide.stderr
    sous_commandes = aide.stdout
    assert "release-batch" in sous_commandes or "batch" in sous_commandes, (
        "aucune sous-commande batch dans attest_publication_cli — le "
        "producteur d'attestation batch n'existe pas encore.\n"
        f"sous-commandes disponibles :\n{sous_commandes}"
    )


def test_un_job_batch_sans_identite_d_artefact_est_refuse(
    control_pg: dict[str, str],
) -> None:
    """Maillon 3 — « le plus récent » n'est pas une règle d'autorité."""
    from ingestor.ingestion_control.provisioning import (
        SealedReleaseRowError,
        find_authorised_artifact,
    )

    inconnu = uuid.uuid4()
    with psycopg.connect(app_dsn(control_pg)) as conn:
        with pytest.raises(SealedReleaseRowError, match="does not belong to resource"):
            find_authorised_artifact(
                conn, resource_id=uuid.uuid4(), artifact_id=inconnu
            )
        conn.rollback()


def test_le_schema_porte_l_identite_de_release_pour_une_attestation_batch(
    control_pg: dict[str, str],
) -> None:
    """Maillon 4 — la migration additive.

    Une ligne d'attestation batch doit pouvoir dire de QUELLE release elle
    relève. Sans colonne d'identité, ``require_release_batch_review_matches_release``
    n'aurait aucune donnée persistée à relire.
    """
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        colonnes = {
            ligne[0]
            for ligne in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='ingestion_control' "
                "  AND table_name='publication_attestations'"
            ).fetchall()
        }
        conn.rollback()
    assert "release_id" in colonnes, (
        "publication_attestations ne porte aucune identité de release : une "
        "attestation batch ne pourrait pas nommer la release qu'elle atteste.\n"
        f"colonnes présentes : {sorted(colonnes)}"
    )


#: Autorites de TEST du banc. Elles ne valent jamais autorisation reelle.
RELEASE_DE_TEST = "acceptance-batch-release-v1"
REVUE_DE_TEST = "revue-batch-acceptance"
AUTORISATION_DE_TEST = "acceptance-batch-scope"


def _semer_etat_historique(
    pg: dict[str, str], tmp_path: Path, *, digests: dict[str, str],
    github: object | None = None, combien: int = 2,
) -> dict[str, object]:
    """Ecrit des lignes au FORMAT HISTORIQUE — celui qu'ecrit l'ingestion de
    release scellee : ``canonical_url`` nulle, payload de release, aucun fait
    unitaire.

    C'est une preparation d'etat initial, pas un contournement : les
    controles que le parcours doit exercer restent tous en place.
    """
    from nexus_contracts.ingestion import ResourceScope

    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        create_ingestion_run,
        create_resource,
        persist_sealed_release_artifact,
        persist_sealed_release_candidate,
    )

    magasin = tmp_path / "store"
    artefacts: list[dict[str, object]] = []
    # Un document MULTICOLLECTION : le meme contenu place dans deux
    # collections. Ses identites et ses droits ne doivent pas fusionner.
    collections = (
        "rag_nexus_nsi_premiere_specialite",
        "rag_nexus_nsi_terminale_specialite",
    )
    contenus = _contenus_de_test(magasin, combien)

    scopes = {
        collection: ResourceScope(
            tenant="libre_terminale", collection=collection,
            niveau="terminale" if "terminale" in collection else "premiere",
            voie="generale", matiere="nsi", candidat="libre",
            audience=["aefe", "libre"], visibility="public",
            school_year="2026-2027", programme_version="EDUSCOL_CORPUS_20260808",
        )
        for collection in collections
    }

    with psycopg.connect(superuser_dsn(pg)) as conn:
        _semer_autorisation(conn, scopes[collections[0]], github=github)
        for collection in collections:
            run_id = create_ingestion_run(
                conn, scope=scopes[collection], profile_version="acceptance-v1",
                trigger="manual",
            )
            for sha, octets in contenus:
                payload = {
                    "release_id": RELEASE_DE_TEST,
                    # Les digests REELS de la release ecrite : la garde du
                    # catalogue refuse toute valeur qui ne serait pas la sienne.
                    "release_manifest_sha256": digests["manifest"],
                    "artifacts_release_sha256": digests["registry"],
                    "candidate_inventory_sha256": digests["inventory"],
                    "artifact_transfer_manifest_sha256": digests["transfer"],
                    "content_sha256": sha,
                    "collection": collection,
                    "chunk_count": 3,
                    "scope_authorization_id": AUTORISATION_DE_TEST,
                    "scope_authorization_digest": "c" * 64,
                    "provenance_artifact_url": (
                        "https://eduscol.education.gouv.fr/acceptance/doc.pdf"
                    ),
                    "provenance_discovery_url": (
                        "https://eduscol.education.gouv.fr/acceptance"
                    ),
                    "review_status": "reviewed",
                    "placement_status": "active",
                    "currentness": "current",
                    "type_doc": "ressource_officielle",
                    "pipeline_kind": SEALED_RELEASE_PIPELINE,
                    "protocol_version": "LOT42-RELEASE-BATCH-V1",
                }
                resource_id = create_resource(
                    conn, run_id=run_id, scope=scopes[collection],
                    dedup_key=sha, pipeline_kind=SEALED_RELEASE_PIPELINE,
                )
                persist_sealed_release_candidate(
                    conn, resource_id=resource_id, run_id=run_id, dedup_key=sha,
                    source_url=payload["provenance_artifact_url"],
                    domain="eduscol.education.gouv.fr",
                    proposed_type_doc="ressource_officielle", payload=payload,
                )
                artifact_id = persist_sealed_release_artifact(
                    conn, resource_id=resource_id, run_id=run_id, sha256=sha,
                    size_bytes=len(octets), mime_declared="application/pdf",
                    mime_detected="application/pdf",
                    provenance_url=payload["provenance_artifact_url"],
                    payload=payload,
                )
                # Les dix transitions HISTORIQUES, comme l'ingestion de
                # release scellee les ecrit. Elles sont referencees par
                # l'attestation, jamais reecrites.
                _semer_transitions(conn, resource_id=resource_id, run_id=run_id)
                artefacts.append({
                    "resource_id": resource_id, "artifact_id": artifact_id,
                    "content_sha256": sha, "collection": collection,
                })
        conn.commit()
    return {"magasin": magasin, "artefacts": artefacts, "contenus": contenus}


_SEQUENCE_HISTORIQUE = (
    ("DISCOVERED", "CANDIDATE"), ("CANDIDATE", "FETCHED"),
    ("FETCHED", "STORED"), ("STORED", "EXTRACTED"),
    ("EXTRACTED", "CLASSIFIED"), ("CLASSIFIED", "RIGHTS_CHECKED"),
    ("RIGHTS_CHECKED", "QUALITY_CHECKED"), ("QUALITY_CHECKED", "ROUTED"),
    ("ROUTED", "STAGED"), ("STAGED", "NEEDS_REVIEW"),
)


def _semer_transitions(
    conn: psycopg.Connection, *, resource_id: object, run_id: object
) -> None:
    """Les dix transitions du chemin scelle, au format historique."""
    for depuis, vers in _SEQUENCE_HISTORIQUE:
        conn.execute(
            "INSERT INTO ingestion_control.workflow_events "
            "  (event_id, run_id, resource_id, event_type, from_state,"
            "   to_state, actor) "
            "VALUES (%s, %s, %s, 'transition', %s, %s, 'acceptance-bench')",
            (uuid.uuid4(), run_id, resource_id, depuis, vers),
        )
    conn.execute(
        "UPDATE ingestion_control.resources "
        "   SET resource_state = 'NEEDS_REVIEW', state_version = 10 "
        " WHERE resource_id = %s", (resource_id,)
    )


def _semer_autorisation(
    conn: psycopg.Connection, scope: object, *, github: object | None = None
) -> None:
    """Autorisation de scope du BANC — donnee de test, jamais une autorite."""
    from datetime import UTC, datetime, timedelta

    obligatoires = [
        (nom, type_sql)
        for nom, type_sql in conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            " WHERE table_schema='ingestion_control' "
            "   AND table_name='scope_authorizations' "
            "   AND is_nullable='NO' AND column_default IS NULL "
            " ORDER BY ordinal_position"
        ).fetchall()
    ]
    ligne: dict[str, object] = {}
    for nom, type_sql in obligatoires:
        if type_sql == "uuid":
            ligne[nom] = uuid.uuid4()
        elif type_sql.startswith("timestamp"):
            ligne[nom] = datetime.now(UTC)
        elif type_sql == "boolean":
            ligne[nom] = True
        elif type_sql == "ARRAY":
            ligne[nom] = []
        elif type_sql in ("integer", "bigint", "smallint"):
            ligne[nom] = 1
        elif nom.endswith(("_base_sha", "_head_sha", "_blob_sha")):
            ligne[nom] = "b" * 40
        elif nom.endswith("_challenge"):
            ligne[nom] = "NEXUS-TRUSTED-REVIEW-V1:" + "a" * 64
        elif nom == "evidence_reviewer":
            ligne[nom] = "abenrhouma"
        elif nom.endswith(("_sha256", "_digest", "_fingerprint")):
            ligne[nom] = "a" * 64
        else:
            ligne[nom] = f"test-{nom}"
    ligne.update({
        "authorization_id": AUTORISATION_DE_TEST,
        "protocol_version": "LOT41A-V1",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "allowed_content_sha256": None,
        "allowed_domains": ["eduscol.education.gouv.fr"],
        "rights_categories": ["officiel_public"],
        "pii_absence_attested": True,
        "artifact_path": f"governance/authorizations/{AUTORISATION_DE_TEST}.json",
        "tenant": scope.tenant, "collection": scope.collection,
        "niveau": scope.niveau, "voie": scope.voie, "matiere": scope.matiere,
        "candidat": scope.candidat, "visibility": scope.visibility,
        "school_year": scope.school_year,
        "programme_version": scope.programme_version,
        "profile_version": "1.0",
    })
    if "audience" in ligne:
        ligne["audience"] = list(scope.audience)
    if "valid_from" in ligne:
        ligne["valid_from"] = datetime.now(UTC) - timedelta(days=1)
    if "valid_until" in ligne:
        ligne["valid_until"] = datetime.now(UTC) + timedelta(days=30)
    # ADR-0058 : une autorisation sans preuve de revue SCELLEE n'est plus
    # utilisable. Le banc en produit une STRUCTURELLEMENT VALIDE, dont le
    # challenge se derive de ses propres dimensions — la verification n'est
    # pas contournee, elle est satisfaite.
    # L'artefact d'autorisation est SERVI par le banc : le verificateur le
    # relit a chaque usage (c'est ce que le lot CT a etabli), et un artefact
    # absent est un refus — a raison.
    tete = "d" * 40
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifact

    artefact_modele = ScopeAuthorizationArtifact.model_validate({
        "protocol_version": "LOT41A-V1",
        "authorization_id": AUTORISATION_DE_TEST,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": {
            "tenant": scope.tenant, "collection": scope.collection,
            "niveau": scope.niveau, "voie": scope.voie,
            "matiere": scope.matiere, "candidat": scope.candidat,
            "audience": list(scope.audience), "visibility": scope.visibility,
            "school_year": scope.school_year,
            "programme_version": scope.programme_version,
        },
        "manifest_digest": str(ligne["manifest_digest"]),
        "profile_id": str(ligne["profile_id"]),
        "profile_version": str(ligne["profile_version"]),
        "profile_fingerprint": str(ligne["profile_fingerprint"]),
        "allowed_domains": ["eduscol.education.gouv.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "acceptance bench: CLEARED",
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2027-09-01T00:00:00Z",
    })
    artefact = artefact_modele.canonical_bytes()
    blob_sha = (
        github.put_blob(  # type: ignore[union-attr]
            path=f"governance/authorizations/{AUTORISATION_DE_TEST}.json",
            ref=tete, content=artefact,
        )
        if github is not None
        else "b" * 40
    )
    ligne.update({
        "evidence_head_sha": tete,
        "artifact_blob_sha": blob_sha,
        # Le digest PERSISTE doit etre celui de l'artefact reellement servi.
        "authorization_digest": artefact_modele.digest(),
        # Toute colonne persistee doit etre DERIVABLE de l'artefact servi :
        # c'est ce que le verificateur exige, et c'est ce qui empeche qu'un
        # UPDATE direct en base survive a la relecture.
        "pii_absence_evidence": artefact_modele.pii_absence_evidence,
        "profile_id": artefact_modele.profile_id,
        "profile_version": artefact_modele.profile_version,
        "profile_fingerprint": artefact_modele.profile_fingerprint,
        "manifest_digest": artefact_modele.manifest_digest,
        "valid_from": artefact_modele.valid_from,
        "valid_until": artefact_modele.valid_until,
        "evidence_repository": REPOSITORY,
        "evidence_pull_request": 6001,
        "evidence_base_sha": "9" * 40,
        "evidence_reviewer": "abenrhouma",
    })
    preuve, digest = _preuve_scellee_de_test(ligne)
    ligne["review_evidence"] = Jsonb(preuve)
    ligne["review_evidence_digest"] = digest

    noms = ", ".join(ligne)
    valeurs = ", ".join(f"%({nom})s" for nom in ligne)
    conn.execute(
        f"INSERT INTO ingestion_control.scope_authorizations ({noms}) "
        f"VALUES ({valeurs}) ON CONFLICT DO NOTHING",
        ligne,
    )


def _preuve_scellee_de_test(ligne: dict[str, object]) -> tuple[dict, str]:
    """Preuve de revue scellee du BANC, conforme a ADR-0058."""
    from datetime import UTC, datetime

    from nexus_contracts.trusted_review_evidence import (
        SealedTrustedReviewEvidenceV1,
    )

    preuve = SealedTrustedReviewEvidenceV1(
        protocol_version="NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1",
        repository=REPOSITORY,
        pull_request=6001,
        pull_request_base_ref="main",
        pull_request_base_sha="9" * 40,
        pull_request_head_sha=str(ligne["evidence_head_sha"]),
        pull_request_author="cyranoaladin",
        authorization_id=str(ligne["authorization_id"]),
        artifact_path=str(ligne["artifact_path"]),
        artifact_blob_sha=str(ligne["artifact_blob_sha"]),
        artifact_sha256=str(ligne["authorization_digest"]),
        reviewer=str(ligne["evidence_reviewer"]),
        review_id=int(ligne["evidence_review_id"]),
        review_node_id="PRR_acceptance_bench",
        review_submitted_at=datetime.now(UTC),
        challenge_protocol="NEXUS-TRUSTED-REVIEW-V1",
        challenge=str(ligne["evidence_challenge"]),
        head_pinned_status="success",
        head_pinned_context="trusted-human-review/head-pinned",
        recorded_at=datetime.now(UTC),
        recorder_version="acceptance-bench",
    )
    # Le challenge doit se DERIVER des dimensions scellees : on le recalcule
    # et on le repose, sinon la verification refuserait — a raison.
    attendu = preuve.expected_challenge()
    preuve = preuve.model_copy(update={"challenge": attendu})
    ligne["evidence_challenge"] = attendu
    return preuve.model_dump(mode="json"), preuve.digest()


def _ecrire_release_de_test(
    racine: Path, *, contenus: list[tuple[str, bytes]], placements: int
) -> dict[str, str]:
    """Ecrit une release de TEST coherente : manifeste, catalogue, evidences.

    Ces autorites sont celles du banc. Elles portent leur nature dans leur
    identifiant et ne sortent jamais de cette base jetable.
    """
    import hashlib as _h

    racine.mkdir(parents=True, exist_ok=True)

    artefacts = []
    chunks_par_contenu = {}
    for index, (sha, _) in enumerate(contenus):
        chunks = [
            {
                "chunk_id": _h.sha256(f"{sha}:{n}".encode()).hexdigest(),
                "chunk_sha256": _h.sha256(f"texte:{sha}:{n}".encode()).hexdigest(),
                "chunk_index": n, "page_start": n + 1, "page_end": n + 1,
                "character_count": 800, "token_count": 200,
            }
            for n in range(3)
        ]
        chunks_par_contenu[sha] = chunks
        artefacts.append({
            "artifact_id": sha, "content_sha256": sha,
            "source_path": f"01_EDUSCOL_OFFICIEL/acceptance/doc-{index}.pdf",
            "source_url": "https://eduscol.education.gouv.fr/acceptance/doc.pdf",
            "title": f"Document d'acceptation {index}",
            "type_doc": "ressource_officielle",
            "page_count": 3, "ignored_empty_pages": [],
            "chunks": chunks,
            "chunk_id_set_digest": "0" * 64,
            "chunk_sha256_set_digest": "0" * 64,
            "page_coverage_digest": "0" * 64,
        })

    def _ecrire(nom: str, document: dict) -> str:
        brut = json.dumps(document, ensure_ascii=False).encode("utf-8")
        (racine / nom).write_bytes(brut)
        return _h.sha256(brut).hexdigest()

    registre_sha = _ecrire("artifacts.release.json", {
        "release_id": RELEASE_DE_TEST, "artifacts": artefacts,
        "expected_counts": {
            "unique_artifacts": len(artefacts),
            "unique_chunks": sum(len(c) for c in chunks_par_contenu.values()),
        },
    })
    preflight_sha = _ecrire("preflight_evidence.json", {
        "evidence_kind": "PRODUCTION_PROFILE_GATE_PREFLIGHT_V1",
        "target_tokens": 384, "model_id": "intfloat/multilingual-e5-large",
        "artifacts": [
            {"content_sha256": a["content_sha256"], "page_count": a["page_count"],
             "source_path": a["source_path"], "chunks": a["chunks"]}
            for a in artefacts
        ],
    })
    currentness_sha = _ecrire("currentness_evidence.json", {
        "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
        "artifacts": [
            {"content_sha256": a["content_sha256"], "decision": "CURRENT",
             "byte_identity": True, "current_for_school_year": "2026-2027"}
            for a in artefacts
        ],
        "counts": {"artifacts": len(artefacts), "current": len(artefacts),
                   "evaluated": len(artefacts), "review_required": 0,
                   "unevaluated": 0},
    })
    corpus_sha = "d" * 64
    pii_sha = _ecrire("pii_evidence.json", {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": corpus_sha,
        "policy_sha256": "9" * 64, "scanner_sha256": "8" * 64,
        "remote_access_mode": "READ_ONLY", "remote_write_operations": 0,
        "raw_pii_in_output": False, "raw_pii_in_logs": False,
        "results": [
            {"content_sha256": a["content_sha256"], "status": "CLEARED",
             "pii_detected": False, "pages_scanned": a["page_count"],
             "characters_scanned": 2400,
             "source_path": a["source_path"], "evidence_sha256": "7" * 64}
            for a in artefacts
        ],
    })
    transfert_sha = _ecrire("transfer.json", {
        "files": [
            {"file": f"{a['content_sha256']}.pdf",
             "sha256_expected": a["content_sha256"],
             "sha256_observed": a["content_sha256"]}
            for a in artefacts
        ],
    })
    registre_droits = (
        "registry_id: acceptance_rights_registry\n"
        "human_rights_decisions:\n"
        "  acceptance_approval:\n"
        "    decision_type: HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL\n"
        "    decision_maker: banc d'acceptation\n"
        f"    scope_manifest_sha256: {corpus_sha}\n"
        "    scope_zone: \"01_EDUSCOL_OFFICIEL/\"\n"
        "    rights_category: officiel_public\n"
        "    approved_for_internal_rag: true\n"
        "    approved_for_production_rag: true\n"
        "    generic_rights_blocker: false\n"
        "source_evidence:\n"
        "  acceptance_source:\n"
        "    zone: \"01_EDUSCOL_OFFICIEL/\"\n"
        "    domain: eduscol.education.gouv.fr\n"
        "    provenance_status: VERIFIED\n"
        "    recommended_rights_category: officiel_public\n"
    )
    (racine / "rights.yml").write_text(registre_droits, encoding="utf-8")
    droits_sha = _h.sha256((racine / "rights.yml").read_bytes()).hexdigest()

    _ecrire("production-profile-gate.release.json", {
        "release_id": RELEASE_DE_TEST,
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
        "artifact_registry": {"path": "artifacts.release.json",
                              "sha256": registre_sha},
        "expected_counts": {
            "subjects": 2, "unique_artifacts": len(artefacts),
            "placements": placements,
            "unique_chunks": sum(len(c) for c in chunks_par_contenu.values()),
        },
        "authorities": {
            "preflight_evidence_sha256": preflight_sha,
            "currentness_evidence_sha256": currentness_sha,
            "pii_evidence_sha256": pii_sha,
            "artifact_transfer_manifest_sha256": transfert_sha,
            "rights_registry_sha256": droits_sha,
            "corpus_manifest_sha256": corpus_sha,
        },
    })
    manifeste_sha = _sha(racine / "production-profile-gate.release.json")
    return {
        "manifest": manifeste_sha, "registry": registre_sha,
        "inventory": corpus_sha, "transfer": transfert_sha,
        "rights": droits_sha,
    }


def _contenus_de_test(magasin: Path, combien: int = 2) -> list[tuple[str, bytes]]:
    """Les octets de test du banc, ecrits dans le magasin d'artefacts."""
    magasin.mkdir(parents=True, exist_ok=True)
    contenus = []
    for index in range(combien):
        octets = f"%PDF-1.7 acceptance-{index}".encode()
        sha = hashlib.sha256(octets).hexdigest()
        (magasin / f"{sha}.pdf").write_bytes(octets)
        contenus.append((sha, octets))
    return contenus


def test_la_projection_et_la_proposition_de_revue_batch(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 5 — la projection est persistee et l'artefact est produit.

    Le programme fait le travail : le test ne construit ni la projection ni
    l'artefact a sa place.
    """
    magasin = tmp_path / "store"
    contenus = _contenus_de_test(magasin)
    releases = tmp_path / "release"
    # La release est ecrite D'ABORD : ses digests sont ensuite ceux que les
    # lignes scellees declarent. L'inverse ferait refuser le catalogue, et
    # c'est bien ce que la garde doit faire.
    digests = _ecrire_release_de_test(
        releases, contenus=contenus, placements=len(contenus) * 2
    )
    etat = _semer_etat_historique(control_pg, tmp_path, digests=digests)

    propose = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        [
            "propose-release-batch-review",
            "--release-id", RELEASE_DE_TEST,
            "--release-dir", str(releases),
            "--release-manifest-sha256", digests["manifest"],
            "--transfer-manifest-path", str(releases / "transfer.json"),
            "--transfer-manifest-sha256", digests["transfer"],
            "--rights-registry-path", str(releases / "rights.yml"),
            "--review-id", REVUE_DE_TEST,
            "--evaluator", "acceptance-bench",
        ],
        {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg)},
    )
    assert propose.returncode == 0, propose.stderr
    assert "PROJECTION_PERSISTED" in propose.stdout, propose.stdout
    assert "REVIEW_ARTIFACT_DIGEST" in propose.stdout, propose.stdout

    # Lecture INDEPENDANTE : la projection existe bien en base.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        projetees = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE gate_passed) "
            "  FROM ingestion_control.sealed_release_projections "
            " WHERE release_id = %s", (RELEASE_DE_TEST,)
        ).fetchone()
        conn.rollback()
    assert projetees == (len(etat["artefacts"]), len(etat["artefacts"])), projetees


def test_l_attestation_batch_est_enregistree_apres_approbation(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 6 — l'enregistrement apres une revue de TEST approuvee.

    La revue est simulee par ``LocalGitHub`` : c'est une autorite de banc,
    nommee comme telle, qui ne sort jamais de cet environnement isole.
    """
    magasin = tmp_path / "store"
    contenus = _contenus_de_test(magasin)
    releases = tmp_path / "release"
    digests = _ecrire_release_de_test(
        releases, contenus=contenus, placements=len(contenus) * 2
    )
    github = LocalGitHub()
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    head = hashlib.sha1(b"acceptance-batch-head").hexdigest()
    github.add_approved_pr(
        number=7001, head_sha=head, base_sha="9" * 40, review_id=7011
    )
    _semer_etat_historique(control_pg, tmp_path, digests=digests, github=github)

    with local_github_server(github) as github_url:
        env = {
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg),
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
        }
        propose = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "propose-release-batch-review",
                "--release-id", RELEASE_DE_TEST,
                "--release-dir", str(releases),
                "--release-manifest-sha256", digests["manifest"],
                "--transfer-manifest-path", str(releases / "transfer.json"),
                "--transfer-manifest-sha256", digests["transfer"],
                "--rights-registry-path", str(releases / "rights.yml"),
                "--review-id", REVUE_DE_TEST,
                "--evaluator", "acceptance-bench",
            ],
            env,
        )
        assert propose.returncode == 0, propose.stderr
        chemin, octets = _artefact_propose(propose.stdout)
        github.put_blob(path=chemin, ref=head, content=octets)

        enregistre = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "record-release-batch-attestation",
                "--release-id", RELEASE_DE_TEST,
                "--review-id", REVUE_DE_TEST,
                "--repository", REPOSITORY,
                "--pull-request", "7001",
                "--expected-head", head,
                "--review-artifact-path", chemin,
            ],
            env,
        )
    assert enregistre.returncode == 0, enregistre.stderr
    assert "RELEASE_BATCH_ATTESTATIONS_RECORDED" in enregistre.stdout

    # Lecture INDEPENDANTE du plan de controle.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        lignes = conn.execute(
            "SELECT count(*), count(DISTINCT release_batch_review_digest),"
            "       count(*) FILTER (WHERE canonical_url IS NOT NULL),"
            "       count(*) FILTER (WHERE attributed_facts_digest IS NOT NULL)"
            "  FROM ingestion_control.publication_attestations"
            " WHERE protocol_version = 'LOT42-RELEASE-BATCH-V1'"
            "   AND release_id = %s", (RELEASE_DE_TEST,)
        ).fetchone()
        conn.rollback()
    # Quatre placements, UNE seule revue, aucune URL canonique, aucun digest
    # d'attribution unitaire.
    assert lignes == (4, 1, 0, 0), lignes


def _artefact_propose(sortie: str) -> tuple[str, bytes]:
    """Extrait le chemin et les octets canoniques produits par la proposition."""
    chemin = ""
    for ligne in sortie.splitlines():
        if ligne.startswith("REVIEW_ARTIFACT_PATH "):
            chemin = ligne.split(" ", 1)[1].strip()
    marqueur = sortie.index("{")
    return chemin, sortie[marqueur:].encode("utf-8")


def test_l_attestation_batch_se_verifie_a_l_usage(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 7 — le consommateur canonique accepte l'attestation batch.

    C'est la contradiction que l'audit initial avait localisee :
    ``verify_publication_attestation`` exigeait inconditionnellement un
    digest d'attribution unitaire, que le schema INTERDIT au batch. Une
    attestation conforme au schema etait donc inverifiable.
    """
    from ingestor.ingestion_control.publication_attestation import (
        PublicationAttestationInvalidError,
        verify_publication_attestation,
    )

    contexte = _preparer_attestation(control_pg, tmp_path)
    github, jeton, head = contexte["github"], contexte["jeton"], contexte["head"]

    with local_github_server(github) as github_url:
        env = {
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
        }
        anciens = {cle: os.environ.get(cle) for cle in env}
        os.environ.update(env)
        try:
            with psycopg.connect(app_dsn(control_pg)) as conn:
                verifiees = []
                for entree in contexte["artefacts"]:
                    verifiee = verify_publication_attestation(
                        conn,
                        resource_id=entree["resource_id"],
                        current_content_sha256=entree["content_sha256"],
                        current_profile_fingerprint=contexte["digests"]["registry"],
                        current_manifest_digest=contexte["digests"]["manifest"],
                    )
                    verifiees.append(verifiee)
                conn.rollback()
            assert len(verifiees) == 4
            assert {v.protocol_version for v in verifiees} == {
                "LOT42-RELEASE-BATCH-V1"
            }
            # Le digest d'attribution UNITAIRE reste absent, et son absence
            # est dite — jamais confondue avec « non verifie ».
            assert {v.attributed_facts_digest for v in verifiees} == {""}
            assert len({v.attestation_digest for v in verifiees}) == 1

            # CONTRE-EPREUVE : une ressource hors du perimetre approuve.
            with psycopg.connect(app_dsn(control_pg)) as conn:
                etrangere = uuid.uuid4()
                with pytest.raises(PublicationAttestationInvalidError):
                    verify_publication_attestation(
                        conn, resource_id=etrangere,
                        current_content_sha256="0" * 64,
                        current_profile_fingerprint=contexte["digests"]["registry"],
                        current_manifest_digest=contexte["digests"]["manifest"],
                    )
                conn.rollback()

            # CONTRE-EPREUVE : un contenu observe different de l'atteste.
            with psycopg.connect(app_dsn(control_pg)) as conn:
                with pytest.raises(PublicationAttestationInvalidError):
                    verify_publication_attestation(
                        conn,
                        resource_id=contexte["artefacts"][0]["resource_id"],
                        current_content_sha256="0" * 64,
                        current_profile_fingerprint=contexte["digests"]["registry"],
                        current_manifest_digest=contexte["digests"]["manifest"],
                    )
                conn.rollback()
        finally:
            for cle, valeur in anciens.items():
                if valeur is None:
                    os.environ.pop(cle, None)
                else:
                    os.environ[cle] = valeur


def _preparer_attestation(
    control_pg: dict[str, str], tmp_path: Path
) -> dict[str, object]:
    """Amene le banc jusqu'a des attestations batch enregistrees."""
    magasin = tmp_path / "store"
    contenus = _contenus_de_test(magasin)
    releases = tmp_path / "release"
    digests = _ecrire_release_de_test(
        releases, contenus=contenus, placements=len(contenus) * 2
    )
    github = LocalGitHub()
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    head = hashlib.sha1(b"acceptance-batch-head").hexdigest()
    github.add_approved_pr(
        number=7001, head_sha=head, base_sha="9" * 40, review_id=7011
    )
    etat = _semer_etat_historique(
        control_pg, tmp_path, digests=digests, github=github
    )
    with local_github_server(github) as github_url:
        env = {
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg),
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
        }
        propose = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "propose-release-batch-review",
                "--release-id", RELEASE_DE_TEST,
                "--release-dir", str(releases),
                "--release-manifest-sha256", digests["manifest"],
                "--transfer-manifest-path", str(releases / "transfer.json"),
                "--transfer-manifest-sha256", digests["transfer"],
                "--rights-registry-path", str(releases / "rights.yml"),
                "--review-id", REVUE_DE_TEST,
                "--evaluator", "acceptance-bench",
            ],
            env,
        )
        assert propose.returncode == 0, propose.stderr
        chemin, octets = _artefact_propose(propose.stdout)
        github.put_blob(path=chemin, ref=head, content=octets)
        enregistre = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "record-release-batch-attestation",
                "--release-id", RELEASE_DE_TEST,
                "--review-id", REVUE_DE_TEST,
                "--repository", REPOSITORY,
                "--pull-request", "7001",
                "--expected-head", head,
                "--review-artifact-path", chemin,
            ],
            env,
        )
        assert enregistre.returncode == 0, enregistre.stderr
    return {
        "github": github, "jeton": jeton, "head": head, "digests": digests,
        "releases": releases, "magasin": magasin,
        "artefacts": etat["artefacts"],
    }


def test_un_job_batch_sans_artefact_nomme_est_refuse(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Contre-epreuve A/B — aucune substitution vers « le plus recent ».

    Une SECONDE version d'artefact existe pour la ressource. Le traitement
    doit utiliser celle que le job nomme, ou refuser ; jamais retenir la
    plus recente parce qu'elle arrive en tete d'une requete ordonnee.
    """
    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        find_authorised_artifact,
        find_latest_artifact,
        persist_sealed_release_artifact,
    )

    contexte = _preparer_attestation(control_pg, tmp_path)
    premier = contexte["artefacts"][0]
    resource_id = premier["resource_id"]
    autorise = premier["artifact_id"]

    # B : plus recent, et JAMAIS couvert par la revue.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        run_id = conn.execute(
            "SELECT run_id FROM ingestion_control.resources WHERE resource_id = %s",
            (resource_id,),
        ).fetchone()[0]
        payload = conn.execute(
            "SELECT payload FROM ingestion_control.artifacts "
            " WHERE artifact_id = %s", (autorise,)
        ).fetchone()[0]
        plus_recent = persist_sealed_release_artifact(
            conn, resource_id=resource_id, run_id=run_id,
            sha256=premier["content_sha256"], size_bytes=999,
            mime_declared="application/pdf", mime_detected="application/pdf",
            provenance_url=payload["provenance_artifact_url"], payload=payload,
        )
        conn.commit()
    assert plus_recent != autorise

    with psycopg.connect(app_dsn(control_pg)) as conn:
        # « le plus recent » rend l'un des deux, selon un ordre que rien ne
        # garantit — les deux lignes peuvent porter le meme collected_at.
        # C'est precisement pourquoi ce n'est pas une regle d'autorite.
        dernier = find_latest_artifact(
            conn, resource_id=resource_id, sealed_catalog=_CatalogueMuet()
        )
        assert dernier is not None
        assert dernier.artifact_id in {autorise, plus_recent}

        # La selection par IDENTITE rend A, celui que la revue a couvert —
        # de maniere DETERMINISTE, quelle que soit l'autre version.
        choisi = find_authorised_artifact(
            conn, resource_id=resource_id, artifact_id=autorise,
            sealed_catalog=_CatalogueMuet(),
        )
        assert choisi.artifact_id == autorise

        # Un identifiant d'une AUTRE ressource est un refus.
        from ingestor.ingestion_control.provisioning import SealedReleaseRowError

        autre = contexte["artefacts"][2]["resource_id"]
        with pytest.raises(SealedReleaseRowError, match="does not belong"):
            find_authorised_artifact(
                conn, resource_id=autre, artifact_id=autorise,
                sealed_catalog=_CatalogueMuet(),
            )
        conn.rollback()

    # Et le discriminateur durable exige bien l'identite pour ce pipeline.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        kind = conn.execute(
            "SELECT pipeline_kind FROM ingestion_control.resources "
            " WHERE resource_id = %s", (resource_id,)
        ).fetchone()
        conn.rollback()
    assert kind == (SEALED_RELEASE_PIPELINE,)


class _CatalogueMuet:
    """Catalogue minimal du banc : il ne decide rien, il rend ce qu'on lui a
    donne. Les refus testes ici portent sur la SELECTION, pas sur lui."""

    def entry(self, *, content_sha256: str) -> dict[str, object]:
        return {"content_sha256": content_sha256, "page_count": 3,
                "title": None, "source_url": None}

    def resolve_rights(self, *, content_sha256: str) -> tuple[str, str, str]:
        return ("officiel_public", "acceptance_approval", "a" * 64)

    def media_type(self, *, content_sha256: str) -> str:
        return "application/pdf"


def test_les_jobs_batch_nomment_leur_artefact(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 8 — les jobs sont crees depuis les attestations ENREGISTREES.

    Chaque job batch nomme l'artefact qu'il publie. Le producteur derive
    cette identite des attestations reellement ecrites, jamais d'un choix
    libre.
    """
    from ingestor.ingestion_control.jobs import create_job

    contexte = _preparer_attestation(control_pg, tmp_path)

    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        attestations = conn.execute(
            "SELECT a.resource_id, a.artifact_id, a.attestation_id, r.run_id,"
            "       r.state_version"
            "  FROM ingestion_control.publication_attestations a"
            "  JOIN ingestion_control.resources r USING (resource_id)"
            " WHERE a.protocol_version = 'LOT42-RELEASE-BATCH-V1'"
            "   AND a.release_id = %s AND a.invalidated_at IS NULL"
            " ORDER BY a.resource_id", (RELEASE_DE_TEST,)
        ).fetchall()
        assert len(attestations) == 4, attestations
        jobs = []
        for resource_id, artifact_id, attestation_id, run_id, version in attestations:
            jobs.append(create_job(
                conn, run_id=run_id, resource_id=resource_id,
                job_type="publication_resume",
                payload={
                    "resource_id": str(resource_id),
                    "run_id": str(run_id),
                    "expected_state_version": version,
                    "publication_attestation_id": str(attestation_id),
                    # L'identite EXACTE : le batch l'exige, et le
                    # discriminateur durable fait appliquer cette exigence.
                    "artifact_id": str(artifact_id),
                },
            ))
        conn.commit()
    assert len(jobs) == 4

    # Lecture INDEPENDANTE : chaque job nomme bien son artefact.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        nommes = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE payload ? 'artifact_id')"
            "  FROM ingestion_control.jobs"
            " WHERE job_type = 'publication_resume' AND status = 'queued'"
        ).fetchone()
        conn.rollback()
    assert nommes == (4, 4), nommes


def test_le_parcours_batch_atteint_l_index_produit() -> None:
    """Maillon final — le job batch traverse la chaîne et publie.

    Cette épreuve reste rouge tant que les maillons ci-dessus manquent.
    Elle n'est pas neutralisée : son échec EST le résultat de départ.
    """
    pytest.fail(
        "parcours batch non exécutable : les maillons 2 (producteur "
        "d'attestation batch) et 4 (identité de release en base) manquent. "
        "Cette épreuve sera complétée dès qu'ils existeront."
    )
