"""Banc partagé des chaînes staging sur les VRAIES releases (lots CY, CZ).

Les modules ``test_v2_backfill_v3_adoption_real_releases`` (adoption V2→V3)
et ``test_v4_staging_direct_real_chain`` (ingestion directe de V4) exécutent
les vrais CLI sur les octets réels. Ce module ne contient que l'outillage
commun : lancement d'un CLI sous un environnement explicite, readiness de
staging signée par une clé de banc, magasin d'artefacts rehaché, forge
locale, relectures des deux bases, arguments canoniques des CLI.

Rien ici n'est une autorité réelle : la clé de readiness, la forge, le
manifeste de transfert nommé et les bases sont des données de TEST.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))

from _local_github import REPOSITORY, LocalGitHub, local_github_server  # noqa: E402
from _pg_authority import app_dsn, superuser_dsn  # noqa: E402

RELEASES = REPOSITORY_ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
V2_DIR = RELEASES / "profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate"
V3_DIR = RELEASES / "profile_gate_v3/release-f8fb983d04f4b7c1/profile_gate"
V4_DIR = RELEASES / "profile_gate_v4/release-024f8625ebfeb7ce/profile_gate"
V2_ID = "production-profile-gate-2026-2027-v2"
V3_ID = "production-profile-gate-2026-2027-v3"
V4_ID = "production-profile-gate-2026-2027-v4"
V2_MANIFEST_SHA256 = "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
V3_MANIFEST_SHA256 = "c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16"
V4_MANIFEST_SHA256 = "bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be"
MANIFESTE = "production-profile-gate.release.json"
TRANSFER_V2 = REPOSITORY_ROOT / "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
PROFILES_V2 = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"
PROFILE_MANIFEST_V2 = ENGINE_ROOT / "configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml"
PROFILES_V4 = ENGINE_ROOT / "configs/ingestion_profiles/v3_livraison_315"
PROFILE_MANIFEST_V4 = ENGINE_ROOT / "configs/ingestion_profiles/ingestion_manifest_v3_livraison_315.yml"
AUTORISATIONS_R2 = REPOSITORY_ROOT / "governance/authorizations"
MIRRORS_ENV = "NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS"
MODELE_E5_ENV = "RAG_EMBEDDING_MODEL_CACHE_DIR"

#: La chaîne de revue PII RÉELLE (ADR-0047), commune à V3 et V4, et son ancre.
CHAINE_PII = {
    "--pii-decision-set-path": "governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json",
    "--pii-review-receipt-path": "governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json",
    "--review-trust-anchor-path": "governance/trust-anchors/review-binding-v1.json",
    "--pii-review-index-path": "docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json",
}
RELEVEURS = REPOSITORY_ROOT / "scripts/github/trusted-reviewers.json"
REGISTRE_DE_DROITS = REPOSITORY_ROOT / "services/rag-pedago/configs/rights_evidence_registry.yml"

#: L'image que la readiness du banc nomme et que le banc déclare en cours
#: d'exécution. Identité de TEST, jamais une image réelle.
WORKER_IMAGE = "ghcr.io/nexus/ingestion-worker-bench@sha256:" + "a" * 64


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifeste(release_dir: Path) -> dict[str, Any]:
    return dict(json.loads((release_dir / MANIFESTE).read_bytes()))


def run(
    module: str, args: Sequence[str], env: Mapping[str, str], timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    """Le vrai CLI, dans un processus à part, sous l'environnement donné SEUL.

    Aucune variable de readiness, de DSN ni d'accès GitHub n'est héritée de
    l'appelant : ce que le CLI exige se lit dans ``env``, et nulle part ailleurs.
    """
    pythonpath = ":".join(
        str(p)
        for p in (
            ENGINE_ROOT / "src",
            REPOSITORY_ROOT / "packages/contracts/src",
            REPOSITORY_ROOT / "packages/release-chain/src",
            REPOSITORY_ROOT / "packages/pdf-page-policy/src",
        )
    )
    child_env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        **env,
        "PYTHONPATH": pythonpath,
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


def champs(sortie: str, marqueur: str) -> dict[str, str]:
    ligne = next(ligne for ligne in sortie.splitlines() if ligne.startswith(marqueur))
    return dict(morceau.split("=", 1) for morceau in ligne.split()[1:] if "=" in morceau)


def empreinte(valeur: Any) -> str:
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def acces_github(github_url: str, jeton: Path) -> dict[str, str]:
    return {"NEXUS_GITHUB_API_BASE": github_url, "NEXUS_GITHUB_TOKEN_FILE": str(jeton)}


def remplacer(arguments: Sequence[str], option: str, valeur: str) -> list[str]:
    copie = list(arguments)
    copie[copie.index(option) + 1] = valeur
    return copie


def magasin_reel(tmp_path: Path) -> Path:
    """Le magasin d'artefacts, reconstruit depuis les miroirs et rehaché.

    Les 315 contenus sont communs à V2, V3 et V4."""
    brut = os.environ.get(MIRRORS_ENV, "").strip()
    if not brut:
        raise AssertionError(f"{MIRRORS_ENV} is required: the 315 real PDFs are never assumed")
    racines = [Path(r) for r in brut.split(":") if r.strip()]
    catalogue = json.loads((V2_DIR / "artifacts.release.json").read_bytes())
    magasin = tmp_path / "artifact-store"
    magasin.mkdir()
    absents: list[str] = []
    for entree in catalogue["artifacts"]:
        contenu = entree["content_sha256"]
        for racine in racines:
            source = racine / entree["source_path"]
            if source.is_file() and sha(source) == contenu:
                shutil.copyfile(source, magasin / f"{contenu}.pdf")
                break
        else:
            absents.append(entree["source_path"])
    assert not absents, f"{len(absents)} real PDF(s) not found: {absents[:3]}"
    return magasin


def transfert_nomme(tmp_path: Path, release_id: str) -> Path:
    """Un manifeste de transfert au nom de ``release_id`` — document de TEST
    dérivé de celui de V2 (mêmes 315 objets), jamais une preuve."""
    chemin = tmp_path / f"bench_{release_id}_artifact_transfer_manifest.json"
    chemin.write_text(
        json.dumps(
            {
                **json.loads(TRANSFER_V2.read_bytes()),
                "release_id": release_id,
                "manifest_kind": "REAL_RELEASE_ADOPTION_BENCH_TRANSFER_V1",
                "bench_note": "test document derived from the V2 transfer; not evidence",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return chemin


def readiness(tmp_path: Path, *, release_id: str, manifest_sha256: str) -> dict[str, str]:
    """Une readiness de STAGING (NEXUS-STAGING-READINESS-V1) signée par une clé
    de banc, nommant UNE release et l'image du banc. Fichiers en lecture
    seule, comme sur l'hôte."""
    from nexus_contracts.staging_readiness import (  # noqa: PLC0415
        STAGING_READINESS_PROTOCOL,
        StagingReadinessManifestV1,
        sign_staging_readiness_manifest,
        staging_public_key_hex,
    )

    graine = secrets.token_hex(32)
    key_id = f"banc-releases-{uuid.uuid4().hex[:12]}"
    repertoire = tmp_path / f"readiness-{uuid.uuid4().hex[:8]}"
    repertoire.mkdir(parents=True)
    maintenant = datetime.now(UTC)
    document = StagingReadinessManifestV1(
        protocol_version=STAGING_READINESS_PROTOCOL,
        environment="rehearsal",
        repository=REPOSITORY,
        merge_sha="c" * 40,
        worker_image=WORKER_IMAGE,
        allowed_release_id=release_id,
        allowed_release_manifest_sha256=manifest_sha256,
        control_dsn_differs_from_product=True,
        key_id=key_id,
        issued_at=maintenant - timedelta(minutes=5),
        expires_at=maintenant + timedelta(hours=8),
    )
    chemin = repertoire / "staging-readiness.json"
    chemin.write_bytes(
        sign_staging_readiness_manifest(document, private_key_hex=graine, key_id=key_id).canonical_bytes()
    )
    ancre = repertoire / "staging-readiness-anchor.json"
    ancre.write_text(
        json.dumps(
            {
                "protocol_version": STAGING_READINESS_PROTOCOL,
                "keys": [
                    {
                        "key_id": key_id,
                        "algorithm": "ed25519",
                        "public_key": staging_public_key_hex(graine),
                        "environment": "rehearsal",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    chemin.chmod(0o444)
    ancre.chmod(0o444)
    return {
        "NEXUS_ENVIRONMENT": "rehearsal",
        "NEXUS_EXPECTED_READINESS_PROTOCOL": STAGING_READINESS_PROTOCOL,
        "NEXUS_READINESS_MANIFEST_PATH": str(chemin),
        "NEXUS_READINESS_MANIFEST_SHA256": sha(chemin),
        "NEXUS_STAGING_READINESS_TRUST_ANCHOR": str(ancre),
        "NEXUS_ACTUAL_WORKER_IMAGE": WORKER_IMAGE,
    }


def r2_reelles() -> dict[str, tuple[str, bytes]]:
    """Les onze r2 RÉELLES du dépôt : collection → (identifiant, octets)."""
    r2: dict[str, tuple[str, bytes]] = {}
    for fichier in sorted(AUTORISATIONS_R2.glob("lot41a-staging-v2-*-r2.json")):
        document = json.loads(fichier.read_bytes())
        r2[document["scope"]["collection"]] = (document["authorization_id"], fichier.read_bytes())
    assert len(r2) == 11, sorted(r2)
    return r2


def autorisations_derivees(generateur: Path) -> dict[str, tuple[str, bytes]]:
    """Les onze autorisations LOT41A-V2 d'un générateur ``go_live`` (r3, r4) :
    collection → (identifiant, octets canoniques)."""
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: PLC0415

    for paquet in ("contracts", "release-chain", "pdf-page-policy"):
        chemin = str(REPOSITORY_ROOT / f"packages/{paquet}/src")
        if chemin not in sys.path:
            sys.path.insert(0, chemin)
    spec = importlib.util.spec_from_file_location(f"generateur_{generateur.stem}", generateur)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    derivees: dict[str, tuple[str, bytes]] = {}
    for identifiant, document in module.construire(REPOSITORY_ROOT).items():
        artefact = ScopeAuthorizationArtifactV2.model_validate(document)
        derivees[artefact.scope.collection] = (identifiant, artefact.canonical_bytes())
    assert len(derivees) == 11, sorted(derivees)
    return derivees


def enregistrer(
    *,
    github: LocalGitHub,
    env: Mapping[str, str],
    documents: Sequence[tuple[str, bytes]],
    numero: int,
    graine: str,
) -> None:
    """Sert chaque artefact sur la forge du banc et le fait enregistrer par le
    VRAI ``authorize_scope_cli`` (rôle authority)."""
    from nexus_contracts.authority_artifacts import canonical_authorization_path  # noqa: PLC0415

    for decalage, (identifiant, octets) in enumerate(documents):
        pr = numero + decalage
        tete = hashlib.sha1(f"auth:{identifiant}:{graine}".encode()).hexdigest()
        github.add_approved_pr(number=pr, head_sha=tete, base_sha="9" * 40, review_id=pr + 5000)
        github.put_blob(path=canonical_authorization_path(identifiant), ref=tete, content=octets)
        enregistre = run(
            "ingestor.ingestion_worker.authorize_scope_cli",
            [
                "record-authorization",
                "--authorization-id", identifiant,
                "--repository", REPOSITORY,
                "--pull-request", str(pr),
                "--expected-head", tete,
            ],
            env,
        )
        assert enregistre.returncode == 0, (identifiant, enregistre.stderr)


def arguments_worker_a(
    *,
    release_dir: Path,
    profiles_dir: Path,
    transfert: Path,
    magasin: Path,
    autorisations: Mapping[str, str],
    extra: Sequence[str] = (),
) -> list[str]:
    args = [
        "--release-dir", str(release_dir),
        "--release-manifest-sha256", sha(release_dir / MANIFESTE),
        "--artifacts-release-sha256", sha(release_dir / "artifacts.release.json"),
        "--candidate-inventory-sha256", sha(release_dir / "candidate_inventory.json"),
        "--artifact-transfer-manifest-path", str(transfert),
        "--artifact-transfer-manifest-sha256", sha(transfert),
        "--artifact-store-dir", str(magasin),
        "--profiles-dir", str(profiles_dir),
        "--owner", "real-release-bench",
        "--expected-role", "ingestion_control_app",
    ]
    for collection, autorisation_id in sorted(autorisations.items()):
        args += ["--scope-authorization", f"{collection}={autorisation_id}"]
    return [*args, *extra]


def arguments_de_proposition(
    *, release_dir: Path, release_id: str, transfert: Path, revue: str
) -> list[str]:
    args = [
        "propose-release-batch-review",
        "--release-id", release_id,
        "--release-dir", str(release_dir),
        "--release-manifest-sha256", sha(release_dir / MANIFESTE),
        "--transfer-manifest-path", str(transfert),
        "--transfer-manifest-sha256", sha(transfert),
        "--rights-registry-path", str(REGISTRE_DE_DROITS),
        "--review-id", revue,
        "--evaluator", "real-release-bench",
        "--pii-review-reviewers-sha256", sha(RELEVEURS),
        "--repository-root", str(REPOSITORY_ROOT),
    ]
    for option, chemin in CHAINE_PII.items():
        args += [option, str(REPOSITORY_ROOT / chemin)]
    return args


def arguments_d_enregistrement(
    *, release_id: str, revue: str, pull_request: int, tete: str, chemin: str
) -> list[str]:
    return [
        "record-release-batch-attestation",
        "--release-id", release_id,
        "--review-id", revue,
        "--repository", REPOSITORY,
        "--pull-request", str(pull_request),
        "--expected-head", tete,
        "--review-artifact-path", chemin,
    ]


def artefact_propose(sortie: str) -> tuple[str, bytes]:
    chemin = next(
        ligne.split(" ", 1)[1].strip()
        for ligne in sortie.splitlines()
        if ligne.startswith("REVIEW_ARTIFACT_PATH ")
    )
    return chemin, sortie[sortie.index("{") :].encode("utf-8")


def arguments_worker_b(
    *,
    release_dir: Path,
    profiles_dir: Path,
    profile_manifest: Path,
    magasin: Path,
    transfert: Path,
    modele: Path,
) -> list[str]:
    """La sémantique EXACTE de ``scripts/go_live/staging_v3_arguments.worker_b``
    appliquée à ``release_dir``, chemins du conteneur remplacés par ceux du
    dépôt. Chaque empreinte est recalculée et confrontée à la release."""
    document = manifeste(release_dir)
    autorites = document["authorities"]
    liaisons = json.loads((release_dir / "authority_bindings.json").read_bytes())
    assert liaisons["profile_manifest_fingerprint"] == autorites["profile_manifest_sha256"]
    assert sha(profile_manifest) == liaisons["profile_manifest_file_sha256"]
    config = ENGINE_ROOT / "configs/rag_collections.yml"
    args = [
        "--profiles-dir", str(profiles_dir),
        "--artifact-store-dir", str(magasin),
        "--owner", "real-release-worker-b",
        "--expected-role", "ingestion_control_app",
        "--expected-product-role", "rag_publisher",
        "--release-manifest-path", str(release_dir / MANIFESTE),
        "--release-manifest-sha256", sha(release_dir / MANIFESTE),
        "--collection-config-path", str(config),
        "--collection-config-sha256", sha(config),
        "--corpus-manifest-sha256", autorites["corpus_manifest_sha256"],
        "--repository-root", str(REPOSITORY_ROOT),
        "--pii-review-reviewers-sha256", sha(RELEVEURS),
        "--artifact-transfer-manifest-path", str(transfert),
        "--artifact-transfer-manifest-sha256", sha(transfert),
        "--embedding-artifact-root", str(modele),
        "--embedding-inventory-sha256", document["models"]["embedding"]["inventory_sha256"],
        "--profile-manifest-path", str(profile_manifest),
        "--profile-manifest-sha256", sha(profile_manifest),
    ]
    for option, cle, chemin_depot, nom_release in (
        ("--candidate-inventory", "candidate_inventory_sha256", None, "candidate_inventory.json"),
        ("--currentness-evidence", "currentness_evidence_sha256", None, "currentness_evidence.json"),
        ("--programme-registry", "programme_registry_sha256", None, "programme_registry.json"),
        ("--pii-evidence", "pii_evidence_sha256", None, "pii_evidence.json"),
        ("--levels-mapping", "level_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_multilevel_levels.yml", None),
        ("--subjects-mapping", "subject_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml", None),
        ("--document-types-mapping", "document_type_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_multilevel_document_types.yml", None),
        ("--rights-evidence", "rights_registry_sha256", "services/rag-pedago/configs/rights_evidence_registry.yml", None),
        ("--pii-decision-set", "pii_decision_set_sha256", CHAINE_PII["--pii-decision-set-path"], None),
        ("--pii-review-receipt", "pii_review_receipt_sha256", CHAINE_PII["--pii-review-receipt-path"], None),
        ("--review-trust-anchor", "pii_review_trust_anchor_sha256", CHAINE_PII["--review-trust-anchor-path"], None),
        ("--pii-review-index", "pii_review_index_sha256", CHAINE_PII["--pii-review-index-path"], None),
    ):
        chemin = REPOSITORY_ROOT / chemin_depot if chemin_depot else release_dir / str(nom_release)
        reel = sha(chemin)
        assert reel == autorites[cle], (chemin, reel, autorites[cle])
        args += [f"{option}-path", str(chemin), f"{option}-sha256", reel]
    return args


def compte_par_table(pg: dict[str, str]) -> dict[str, int]:
    """Le nombre de lignes de CHAQUE table du plan de contrôle."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        tables = [
            ligne[0]
            for ligne in conn.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'ingestion_control' AND table_type = 'BASE TABLE'"
                " ORDER BY table_name"
            ).fetchall()
        ]
        comptes = {}
        for table in tables:
            ligne = conn.execute(f'SELECT count(*) FROM ingestion_control."{table}"').fetchone()  # noqa: S608
            comptes[table] = int(ligne[0]) if ligne else 0
        conn.rollback()
    return comptes


def ecarts(avant: Mapping[str, int], apres: Mapping[str, int]) -> dict[str, tuple[int, int]]:
    return {t: (avant.get(t, 0), apres[t]) for t in apres if apres[t] != avant.get(t, 0)}


def produit(produit_pg: dict[str, str]) -> dict[str, Any]:
    """La base produit, relue indépendamment (rôle administrateur du banc)."""
    with psycopg.connect(produit_pg["admin_dsn"]) as conn:
        placements = conn.execute(
            "SELECT placement_id, artifact_id, collection, currentness, placement_status,"
            "       review_status, authorization_id, publication_attestation_id,"
            "       programme_version, visibility, source_placement_id"
            "  FROM public.rag_artifact_placements ORDER BY placement_id"
        ).fetchall()
        chunks = conn.execute(
            "SELECT artifact_id, collection, count(*), min(vector_dims(vector)),"
            "       max(vector_dims(vector)), count(*) FILTER (WHERE vector IS NULL),"
            "       array_agg(DISTINCT programme_version), array_agg(DISTINCT visibility),"
            "       array_agg(DISTINCT rights)"
            "  FROM public.rag_chunks GROUP BY artifact_id, collection ORDER BY 1, 2"
        ).fetchall()
        identites = conn.execute(
            "SELECT artifact_id, collection, chunk_id, chunk_sha256, chunk_index"
            "  FROM public.rag_chunks ORDER BY 1, 2, 5"
        ).fetchall()
        artefacts = conn.execute("SELECT count(*) FROM public.rag_artifacts").fetchone()
        conn.rollback()
    return {
        "placements": placements,
        "chunks": chunks,
        "identites": identites,
        "artifacts": artefacts[0] if artefacts else 0,
    }


def creer_les_jobs(
    pg: dict[str, str], *, release_id: str, cibles: Sequence[tuple[str, str]]
) -> dict[str, dict[str, Any]]:
    """Un job de publication par placement ``(collection, préfixe de contenu)``,
    nommant l'attestation batch active de ``release_id`` qui le couvre."""
    from ingestor.ingestion_control.jobs import create_job  # noqa: PLC0415

    jobs: dict[str, dict[str, Any]] = {}
    with psycopg.connect(superuser_dsn(pg)) as conn:
        for collection, prefixe in cibles:
            lignes = conn.execute(
                "SELECT r.resource_id, a.artifact_id, a.sha256, r.run_id, r.state_version,"
                "       pa.attestation_id"
                "  FROM ingestion_control.resources r"
                "  JOIN ingestion_control.artifacts a USING (resource_id)"
                "  JOIN ingestion_control.publication_attestations pa"
                "    ON pa.resource_id = r.resource_id AND pa.release_id = %s"
                "   AND pa.invalidated_at IS NULL"
                " WHERE r.collection = %s AND a.sha256 LIKE %s",
                (release_id, collection, f"{prefixe}%"),
            ).fetchall()
            assert len(lignes) == 1, (collection, prefixe, lignes)
            resource_id, artifact_id, contenu, run_id, version, attestation_id = lignes[0]
            job_id = create_job(
                conn, run_id=run_id, resource_id=resource_id, job_type="publication_resume",
                payload={
                    "resource_id": str(resource_id),
                    "run_id": str(run_id),
                    "expected_state_version": version,
                    "publication_attestation_id": str(attestation_id),
                    "artifact_id": str(artifact_id),
                },
            )
            jobs[str(job_id)] = {
                "collection": collection, "sha": contenu, "resource_id": resource_id,
                "attestation_id": str(attestation_id),
            }
        conn.commit()
    return jobs


def lancer_worker_b(
    control_pg: dict[str, str],
    produit_pg: dict[str, str],
    *,
    github: LocalGitHub,
    jeton: Path,
    readiness_env: Mapping[str, str],
    arguments: Sequence[str],
    timeout: int = 3600,
) -> subprocess.CompletedProcess[str]:
    """Le VRAI Worker B, rôles opérationnels, forge du banc ouverte."""
    with local_github_server(github) as github_url:
        return run(
            "ingestor.ingestion_worker.multilevel_publication_resume_cli",
            arguments,
            {
                **readiness_env,
                "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
                "PG_RAG_DSN": produit_pg["publisher_dsn"],
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "CUDA_VISIBLE_DEVICES": "",
                **acces_github(github_url, jeton),
            },
            timeout=timeout,
        )


def refus_au_demarrage(sortie: subprocess.CompletedProcess[str]) -> str:
    """Un refus au démarrage : code 1, motif nommé, aucun job réclamé."""
    assert sortie.returncode == 1, (sortie.stdout, sortie.stderr)
    assert "MULTILEVEL_PUBLICATION_WORKER_STARTUP_FAILED" in sortie.stderr, sortie.stderr
    assert "ITERATION" not in sortie.stdout, sortie.stdout
    return sortie.stderr.strip()


def erreurs_d_iteration(stderr: str) -> list[str]:
    return [
        ligne for ligne in stderr.splitlines()
        if ligne.startswith("MULTILEVEL_PUBLICATION_WORKER_ITERATION_ERROR")
    ]
