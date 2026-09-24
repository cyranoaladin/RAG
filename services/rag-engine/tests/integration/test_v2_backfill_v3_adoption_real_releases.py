"""La chaîne staging complète de V3, sur les VRAIES releases (lots CY, CZ).

Ce module rejoue, par les vrais CLI et sur les octets réels, ce que le
staging exécutera pour qualifier V3 (ADR-0059, ADR-0060) :

1. état historique : les 479 placements de V2 écrits par le vrai Worker A
   sous les autorisations RÉELLES ``lot41a-staging-v2-*-r2`` (LOT41A-V1),
   puis privés de leurs attributions, comme sur le staging ;
2. ``--only-attributions`` sur V2, sous une readiness de staging nommant V2 ;
3. ``adopt-predecessor-release`` pour V3 (manifeste de transfert au nom de V3) ;
4. enregistrement des onze r3 (``build_lot41a_r3_authorizations.construire``),
   puis ``bind-publication-authorities`` ;
5. ``propose-release-batch-review`` (chaîne PII réelle), approbation sur la
   forge du banc, ``record-release-batch-attestation`` ;
6. Worker B sous une readiness de STAGING nommant V3, avec les arguments de
   ``scripts/go_live/staging_v3_arguments.worker_b`` ; publication d'un
   sous-ensemble borné, relecture indépendante des deux bases, retrieval.

Chaque contre-épreuve demandée est un test : readiness d'une autre release,
manifeste de profils altéré ou autre, chaîne PII non autorisée, autorité V1
sans liaison, r3 étrangère ou incomplète, readiness de staging sous
production, reprise après écriture produit.

Les autorités fabriquées ici sont des **données de test** : forge locale,
clé de readiness de banc, manifeste de transfert V3 dérivé. Les r2, les r3,
la chaîne PII et son ancre sont les documents réels (ou leur dérivation
canonique). Rien ne sort des bases jetables.

Prérequis (sinon le module est ignoré, ou échoue nommément) :

- ``NEXUS_REAL_RELEASE_ADOPTION=1`` ;
- ``NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS`` : racines de corpus séparées par
  ``:`` où se trouvent les ``source_path`` du catalogue V2 ;
- ``RAG_EMBEDDING_MODEL_CACHE_DIR`` : l'artefact E5 réel (inventaire 58ad18db…) ;
- Docker (bases jetables, supprimées à la sortie).
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
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

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
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    start_rag_product_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

if os.environ.get("NEXUS_REAL_RELEASE_ADOPTION") != "1":
    pytest.skip(
        "real V2 backfill / V3 adoption not requested (NEXUS_REAL_RELEASE_ADOPTION=1)",
        allow_module_level=True,
    )

RELEASES = REPOSITORY_ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
V2_DIR = RELEASES / "profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate"
V3_DIR = RELEASES / "profile_gate_v3/release-f8fb983d04f4b7c1/profile_gate"
V2_ID = "production-profile-gate-2026-2027-v2"
V3_ID = "production-profile-gate-2026-2027-v3"
V2_MANIFEST_SHA256 = "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
V3_MANIFEST_SHA256 = "c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16"
TRANSFER_V2 = REPOSITORY_ROOT / (
    "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
)
PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"
PROFILE_MANIFEST = ENGINE_ROOT / "configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml"
AUTORISATIONS_R2 = REPOSITORY_ROOT / "governance/authorizations"
GENERATEUR_R3 = REPOSITORY_ROOT / "scripts/go_live/build_lot41a_r3_authorizations.py"
MIRRORS_ENV = "NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS"
MODELE_E5_ENV = "RAG_EMBEDDING_MODEL_CACHE_DIR"

#: La chaîne de revue PII RÉELLE de V3 (ADR-0047) et son ancre réelle.
CHAINE_PII_V3 = {
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

#: Le sous-ensemble publié : quatre placements, quatre collections, dont un
#: contenu DETECTED_REVIEWED_ACCEPTED (ebe2d96d…) et un contenu placé dans
#: deux collections (8eb23c91…).
PLACEMENTS_PUBLIES = (
    ("rag_nexus_dgemc_terminale_option", "ebe2d96d2460"),
    ("rag_nexus_svt_premiere_specialite", "8eb23c91b035"),
    ("rag_nexus_svt_terminale_specialite", "8eb23c91b035"),
    ("rag_nexus_hlp_premiere_specialite", "8d8d833b4051"),
)
CONTENU_DRA = "ebe2d96d2460"

_RUN_ID = uuid.uuid4().hex[:10]
REVUE_V3 = f"lot42-release-batch-v3-reelle-{_RUN_ID}"


# --- Outils -----------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digests(release_dir: Path) -> dict[str, str]:
    return {
        "release_manifest_sha256": _sha(release_dir / "production-profile-gate.release.json"),
        "artifacts_release_sha256": _sha(release_dir / "artifacts.release.json"),
        "candidate_inventory_sha256": _sha(release_dir / "candidate_inventory.json"),
    }


def _run(
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


def _champs(sortie: str, marqueur: str) -> dict[str, str]:
    ligne = next(ligne for ligne in sortie.splitlines() if ligne.startswith(marqueur))
    return dict(morceau.split("=", 1) for morceau in ligne.split()[1:] if "=" in morceau)


def _empreinte(valeur: Any) -> str:
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _acces_github(github_url: str, jeton: Path) -> dict[str, str]:
    return {"NEXUS_GITHUB_API_BASE": github_url, "NEXUS_GITHUB_TOKEN_FILE": str(jeton)}


def _magasin_reel(tmp_path: Path) -> Path:
    """Le magasin d'artefacts, reconstruit depuis les miroirs et rehaché."""
    brut = os.environ.get(MIRRORS_ENV, "").strip()
    if not brut:
        pytest.fail(f"{MIRRORS_ENV} is required: the 315 real PDFs are never assumed")
    racines = [Path(r) for r in brut.split(":") if r.strip()]
    catalogue = json.loads((V2_DIR / "artifacts.release.json").read_bytes())
    magasin = tmp_path / "artifact-store"
    magasin.mkdir()
    absents: list[str] = []
    for entree in catalogue["artifacts"]:
        sha = entree["content_sha256"]
        for racine in racines:
            source = racine / entree["source_path"]
            if source.is_file() and _sha(source) == sha:
                shutil.copyfile(source, magasin / f"{sha}.pdf")
                break
        else:
            absents.append(entree["source_path"])
    assert not absents, f"{len(absents)} real PDF(s) not found: {absents[:3]}"
    return magasin


def _readiness(
    tmp_path: Path, *, release_id: str, manifest_sha256: str
) -> dict[str, str]:
    """Une readiness de STAGING (NEXUS-STAGING-READINESS-V1) signée par une clé
    de banc, nommant UNE release et l'image du banc."""
    from nexus_contracts.staging_readiness import (  # noqa: PLC0415
        STAGING_READINESS_PROTOCOL,
        StagingReadinessManifestV1,
        sign_staging_readiness_manifest,
        staging_public_key_hex,
    )

    graine = secrets.token_hex(32)
    key_id = f"banc-v2-v3-{uuid.uuid4().hex[:12]}"
    repertoire = tmp_path / f"readiness-{uuid.uuid4().hex[:8]}"
    repertoire.mkdir(parents=True)
    maintenant = datetime.now(UTC)
    manifeste = StagingReadinessManifestV1(
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
        expires_at=maintenant + timedelta(hours=6),
    )
    chemin = repertoire / "staging-readiness.json"
    chemin.write_bytes(
        sign_staging_readiness_manifest(manifeste, private_key_hex=graine, key_id=key_id).canonical_bytes()
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
    # En lecture seule, comme sur l'hôte : un refus doit venir du protocole
    # ou de l'identité, jamais d'une permission de fichier.
    chemin.chmod(0o444)
    ancre.chmod(0o444)
    return {
        "NEXUS_ENVIRONMENT": "rehearsal",
        "NEXUS_EXPECTED_READINESS_PROTOCOL": STAGING_READINESS_PROTOCOL,
        "NEXUS_READINESS_MANIFEST_PATH": str(chemin),
        "NEXUS_READINESS_MANIFEST_SHA256": _sha(chemin),
        "NEXUS_STAGING_READINESS_TRUST_ANCHOR": str(ancre),
        "NEXUS_ACTUAL_WORKER_IMAGE": WORKER_IMAGE,
    }


# --- Autorités ----------------------------------------------------------------


def _r2_reelles() -> dict[str, tuple[str, bytes]]:
    """Les onze r2 RÉELLES du dépôt : collection → (identifiant, octets)."""
    r2: dict[str, tuple[str, bytes]] = {}
    for fichier in sorted(AUTORISATIONS_R2.glob("lot41a-staging-v2-*-r2.json")):
        document = json.loads(fichier.read_bytes())
        r2[document["scope"]["collection"]] = (document["authorization_id"], fichier.read_bytes())
    assert len(r2) == 11, sorted(r2)
    return r2


def _r3_derivees() -> dict[str, tuple[str, bytes]]:
    """Les onze r3, par le générateur du lot CZ : collection → (id, octets)."""
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("build_lot41a_r3", GENERATEUR_R3)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    r3: dict[str, tuple[str, bytes]] = {}
    for identifiant, document in module.construire(REPOSITORY_ROOT).items():
        artefact = ScopeAuthorizationArtifactV2.model_validate(document)
        r3[artefact.scope.collection] = (identifiant, artefact.canonical_bytes())
    assert len(r3) == 11, sorted(r3)
    return r3


def _enregistrer(
    *, github: LocalGitHub, env: Mapping[str, str], documents: Sequence[tuple[str, bytes]], numero: int
) -> None:
    """Sert chaque artefact sur la forge du banc et le fait enregistrer par le
    VRAI ``authorize_scope_cli`` (rôle authority)."""
    from nexus_contracts.authority_artifacts import canonical_authorization_path  # noqa: PLC0415

    for decalage, (identifiant, octets) in enumerate(documents):
        pr = numero + decalage
        tete = hashlib.sha1(f"auth:{identifiant}:{_RUN_ID}".encode()).hexdigest()
        github.add_approved_pr(number=pr, head_sha=tete, base_sha="9" * 40, review_id=pr + 5000)
        github.put_blob(path=canonical_authorization_path(identifiant), ref=tete, content=octets)
        enregistre = _run(
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


# --- Arguments des CLI ------------------------------------------------------


def _arguments_worker_a(
    *, magasin: Path, autorisations: Mapping[str, str], extra: Sequence[str] = ()
) -> list[str]:
    d = _digests(V2_DIR)
    args = [
        "--release-dir", str(V2_DIR),
        "--release-manifest-sha256", d["release_manifest_sha256"],
        "--artifacts-release-sha256", d["artifacts_release_sha256"],
        "--candidate-inventory-sha256", d["candidate_inventory_sha256"],
        "--artifact-transfer-manifest-path", str(TRANSFER_V2),
        "--artifact-transfer-manifest-sha256", _sha(TRANSFER_V2),
        "--artifact-store-dir", str(magasin),
        "--profiles-dir", str(PROFILES_DIR),
        "--owner", "real-release-adoption-bench",
        "--expected-role", "ingestion_control_app",
    ]
    for collection, autorisation_id in sorted(autorisations.items()):
        args += ["--scope-authorization", f"{collection}={autorisation_id}"]
    return [*args, *extra]


def _arguments_d_adoption(transfert: Path) -> list[str]:
    d = _digests(V3_DIR)
    return [
        "adopt-predecessor-release",
        "--release-id", V3_ID,
        "--release-dir", str(V3_DIR),
        "--release-manifest-sha256", d["release_manifest_sha256"],
        "--artifacts-release-sha256", d["artifacts_release_sha256"],
        "--candidate-inventory-sha256", d["candidate_inventory_sha256"],
        "--transfer-manifest-path", str(transfert),
        "--transfer-manifest-sha256", _sha(transfert),
        "--predecessor-release-id", V2_ID,
        "--predecessor-release-manifest-sha256", V2_MANIFEST_SHA256,
        "--adopted-by", "real-release-adoption-bench",
    ]


def _arguments_de_liaison(par_collection: Mapping[str, str]) -> list[str]:
    args = ["bind-publication-authorities", "--release-id", V3_ID, "--bound-by", "real-release-bench"]
    for collection, identifiant in sorted(par_collection.items()):
        args += ["--scope-authorization", f"{collection}={identifiant}"]
    return args


def _arguments_de_proposition_v3(transfert: Path, *, revue: str) -> list[str]:
    args = [
        "propose-release-batch-review",
        "--release-id", V3_ID,
        "--release-dir", str(V3_DIR),
        "--release-manifest-sha256", V3_MANIFEST_SHA256,
        "--transfer-manifest-path", str(transfert),
        "--transfer-manifest-sha256", _sha(transfert),
        "--rights-registry-path", str(REGISTRE_DE_DROITS),
        "--review-id", revue,
        "--evaluator", "real-release-adoption-bench",
        "--pii-review-reviewers-sha256", _sha(RELEVEURS),
        "--repository-root", str(REPOSITORY_ROOT),
    ]
    for option, chemin in CHAINE_PII_V3.items():
        args += [option, str(REPOSITORY_ROOT / chemin)]
    return args


def _arguments_worker_b(*, magasin: Path, transfert: Path, modele: Path) -> list[str]:
    """La sémantique EXACTE de ``scripts/go_live/staging_v3_arguments.worker_b``,
    chemins du conteneur remplacés par ceux du dépôt."""
    manifeste = json.loads((V3_DIR / "production-profile-gate.release.json").read_bytes())
    autorites = manifeste["authorities"]
    liaisons = json.loads((V3_DIR / "authority_bindings.json").read_bytes())
    assert liaisons["profile_manifest_fingerprint"] == autorites["profile_manifest_sha256"]
    assert _sha(PROFILE_MANIFEST) == liaisons["profile_manifest_file_sha256"]
    config = ENGINE_ROOT / "configs/rag_collections.yml"
    args = [
        "--profiles-dir", str(PROFILES_DIR),
        "--artifact-store-dir", str(magasin),
        "--owner", "real-release-adoption-worker-b",
        "--expected-role", "ingestion_control_app",
        "--expected-product-role", "rag_publisher",
        "--release-manifest-path", str(V3_DIR / "production-profile-gate.release.json"),
        "--release-manifest-sha256", V3_MANIFEST_SHA256,
        "--collection-config-path", str(config),
        "--collection-config-sha256", _sha(config),
        "--corpus-manifest-sha256", autorites["corpus_manifest_sha256"],
        "--repository-root", str(REPOSITORY_ROOT),
        "--pii-review-reviewers-sha256", _sha(RELEVEURS),
        "--artifact-transfer-manifest-path", str(transfert),
        "--artifact-transfer-manifest-sha256", _sha(transfert),
        "--embedding-artifact-root", str(modele),
        "--embedding-inventory-sha256", manifeste["models"]["embedding"]["inventory_sha256"],
        "--profile-manifest-path", str(PROFILE_MANIFEST),
        "--profile-manifest-sha256", _sha(PROFILE_MANIFEST),
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
        ("--pii-decision-set", "pii_decision_set_sha256", CHAINE_PII_V3["--pii-decision-set-path"], None),
        ("--pii-review-receipt", "pii_review_receipt_sha256", CHAINE_PII_V3["--pii-review-receipt-path"], None),
        ("--review-trust-anchor", "pii_review_trust_anchor_sha256", CHAINE_PII_V3["--review-trust-anchor-path"], None),
        ("--pii-review-index", "pii_review_index_sha256", CHAINE_PII_V3["--pii-review-index-path"], None),
    ):
        chemin = REPOSITORY_ROOT / chemin_depot if chemin_depot else V3_DIR / str(nom_release)
        reel = _sha(chemin)
        assert reel == autorites[cle], (chemin, reel, autorites[cle])
        args += [f"{option}-path", str(chemin), f"{option}-sha256", reel]
    return args


def _remplacer(arguments: Sequence[str], option: str, valeur: str) -> list[str]:
    copie = list(arguments)
    copie[copie.index(option) + 1] = valeur
    return copie


# --- Relectures -------------------------------------------------------------


def _etat_historique(pg: dict[str, str]) -> dict[str, Any]:
    """Les identités acquises de V2 — ce qu'aucune étape n'a le droit de modifier."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        ressources = conn.execute(
            "SELECT resource_id, collection, dedup_key, pipeline_kind, run_id"
            "  FROM ingestion_control.resources ORDER BY resource_id"
        ).fetchall()
        artefacts = conn.execute(
            "SELECT artifact_id, resource_id, sha256, run_id, payload"
            "  FROM ingestion_control.artifacts ORDER BY artifact_id"
        ).fetchall()
        candidats = conn.execute("SELECT * FROM ingestion_control.resource_candidates ORDER BY 1").fetchall()
        conn.rollback()
    return {
        "resources": _empreinte(ressources),
        "artifacts": _empreinte(artefacts),
        "resource_candidates": _empreinte(candidats),
        "counts": (len(ressources), len(artefacts), len(candidats)),
        "release_ids": sorted({ligne[4]["release_id"] for ligne in artefacts}),
        "acquisition_authorities": sorted({ligne[4]["scope_authorization_id"] for ligne in artefacts}),
    }


def _compte_par_table(pg: dict[str, str]) -> dict[str, int]:
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


def _ecarts(avant: Mapping[str, int], apres: Mapping[str, int]) -> dict[str, tuple[int, int]]:
    return {t: (avant.get(t, 0), apres[t]) for t in apres if apres[t] != avant.get(t, 0)}


def _produit(produit_pg: dict[str, str]) -> dict[str, Any]:
    with psycopg.connect(produit_pg["admin_dsn"]) as conn:
        placements = conn.execute(
            "SELECT placement_id, artifact_id, collection, currentness, placement_status,"
            "       review_status, authorization_id, publication_attestation_id"
            "  FROM public.rag_artifact_placements ORDER BY placement_id"
        ).fetchall()
        chunks = conn.execute(
            "SELECT artifact_id, collection, count(*), min(vector_dims(vector)),"
            "       max(vector_dims(vector)), count(*) FILTER (WHERE vector IS NULL)"
            "  FROM public.rag_chunks GROUP BY artifact_id, collection ORDER BY 1, 2"
        ).fetchall()
        artefacts = conn.execute("SELECT count(*) FROM public.rag_artifacts").fetchone()
        conn.rollback()
    return {"placements": placements, "chunks": chunks, "artifacts": artefacts[0] if artefacts else 0}


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("v3-real-chain")


@pytest.fixture(scope="module")
def produit_pg() -> Iterator[dict[str, str]]:
    yield from start_rag_product_postgres("v3-real-product")


@pytest.fixture(scope="module")
def banc(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Le matériel partagé : magasin réel, manifeste de transfert V3 (TEST),
    readiness de staging, modèle E5."""
    tmp_path = tmp_path_factory.mktemp("banc")
    modele = os.environ.get(MODELE_E5_ENV, "").strip()
    if not modele:
        pytest.fail(f"{MODELE_E5_ENV} is required: Worker B really embeds")
    transfert_v3 = tmp_path / "bench_v3_artifact_transfer_manifest.json"
    transfert_v3.write_text(
        json.dumps(
            {
                **json.loads(TRANSFER_V2.read_bytes()),
                "release_id": V3_ID,
                "manifest_kind": "REAL_RELEASE_ADOPTION_BENCH_TRANSFER_V1",
                "bench_note": "test document derived from the V2 transfer; not evidence",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    return {
        "tmp_path": tmp_path,
        "magasin": _magasin_reel(tmp_path),
        "transfert_v3": transfert_v3,
        "jeton": jeton,
        "modele": Path(modele),
        "readiness_v2": _readiness(tmp_path, release_id=V2_ID, manifest_sha256=V2_MANIFEST_SHA256),
        "readiness_v3": _readiness(tmp_path, release_id=V3_ID, manifest_sha256=V3_MANIFEST_SHA256),
    }


def _jusqu_a_l_adoption(
    pg: dict[str, str], banc: Mapping[str, Any], github: LocalGitHub
) -> dict[str, Any]:
    """État historique (r2 réelles, V1) → rattrapage V2 → adoption V3.

    Chaque étape est ASSERTÉE : un échec arrête à l'étape qui a échoué."""
    r2 = _r2_reelles()
    base = {"PG_INGESTION_CONTROL_DSN": app_dsn(pg)}
    with local_github_server(github) as github_url:
        acces = _acces_github(github_url, banc["jeton"])
        _enregistrer(
            github=github,
            env={"PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(pg), **acces},
            documents=[r2[c] for c in sorted(r2)],
            numero=8100,
        )
        autorisations_r2 = {collection: identifiant for collection, (identifiant, _o) in r2.items()}
        ingere = _run(
            "ingestor.ingestion_worker.sealed_release_ingestion_cli",
            _arguments_worker_a(magasin=banc["magasin"], autorisations=autorisations_r2),
            {**base, **banc["readiness_v2"], **acces},
        )
    assert ingere.returncode == 0, ingere.stderr
    fin = _champs(ingere.stdout, "SEALED_RELEASE_INGESTION_DONE")
    assert (fin["resources"], fin["artifacts"], fin["terminal_state"]) == ("479", "479", "NEEDS_REVIEW")

    # L'état de staging : lignes écrites avant que Worker A n'établisse les
    # attributions.
    with psycopg.connect(superuser_dsn(pg)) as conn:
        retirees = conn.execute("DELETE FROM ingestion_control.artifact_attributions RETURNING 1").fetchall()
        conn.commit()
    assert len(retirees) == 479
    historique = _etat_historique(pg)
    assert historique["counts"] == (479, 479, 479)
    assert historique["acquisition_authorities"] == sorted(autorisations_r2.values())

    rattrape = _run(
        "ingestor.ingestion_worker.sealed_release_ingestion_cli",
        _arguments_worker_a(
            magasin=banc["magasin"], autorisations=autorisations_r2, extra=["--only-attributions"]
        ),
        {**base, **banc["readiness_v2"]},
    )
    assert rattrape.returncode == 0, rattrape.stderr
    bilan = _champs(rattrape.stdout, "SEALED_RELEASE_ATTRIBUTION_BACKFILL_DONE")
    assert (bilan["examined"], bilan["written"], bilan["missing_rows"]) == ("479", "479", "0")

    adopte = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_d_adoption(banc["transfert_v3"]),
        {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(pg)},
    )
    assert adopte.returncode == 0, adopte.stderr
    adoption = _champs(adopte.stdout, "ADOPTION_RECORDED")
    assert (adoption["placements"], adoption["written"], adoption["currentness"]) == (
        "479", "479", "official_snapshot",
    )
    assert _etat_historique(pg) == historique
    return {
        "historique": historique,
        "r2": autorisations_r2,
        "rattrapage": rattrape.stdout.strip().splitlines()[-1],
        "adoption": adopte.stdout.strip(),
    }


@pytest.fixture(scope="module")
def github() -> LocalGitHub:
    return LocalGitHub()


@pytest.fixture(scope="module")
def adopte(control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub) -> dict[str, Any]:
    etat = _jusqu_a_l_adoption(control_pg, banc, github)
    print("REAL_CHAIN_BACKFILL", etat["rattrapage"])
    print("REAL_CHAIN_ADOPTION", etat["adoption"])
    return etat


@pytest.fixture(scope="module")
def r3_enregistrees(
    adopte: dict[str, Any], control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub
) -> dict[str, str]:
    """Les onze r3, enregistrées par le vrai CLI d'autorité — pas encore liées."""
    r3 = _r3_derivees()
    with local_github_server(github) as github_url:
        _enregistrer(
            github=github,
            env={
                "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
                **_acces_github(github_url, banc["jeton"]),
            },
            documents=[r3[c] for c in sorted(r3)],
            numero=8200,
        )
    return {collection: identifiant for collection, (identifiant, _o) in r3.items()}


@pytest.fixture(scope="module")
def lie(
    r3_enregistrees: dict[str, str],
    control_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> dict[str, Any]:
    """Les onze r3 liées aux 479 placements adoptés."""
    par_collection = r3_enregistrees
    with local_github_server(github) as github_url:
        acces = _acces_github(github_url, banc["jeton"])
        avant = _compte_par_table(control_pg)
        lier = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_liaison(par_collection),
            {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg), **acces},
        )
        print("REAL_CHAIN_BIND", lier.stdout.strip(), lier.stderr.strip())
        assert lier.returncode == 0, lier.stderr
        rejoue = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_liaison(par_collection),
            {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg), **acces},
        )
    assert rejoue.returncode == 0, rejoue.stderr
    return {
        "r3": par_collection,
        "sortie": lier.stdout.strip(),
        "rejeu": rejoue.stdout.strip(),
        "ecarts": _ecarts(avant, _compte_par_table(control_pg)),
    }


@pytest.fixture(scope="module")
def atteste(
    lie: dict[str, Any], control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub
) -> dict[str, Any]:
    """Proposition (sans GitHub), approbation sur la forge du banc, enregistrement."""
    attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg)}
    propose = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_de_proposition_v3(banc["transfert_v3"], revue=REVUE_V3),
        attestor,
    )
    print("REAL_CHAIN_PROPOSE", propose.stdout.splitlines()[:3], propose.stderr[-1500:])
    assert propose.returncode == 0, propose.stderr
    chemin = next(
        ligne.split(" ", 1)[1].strip()
        for ligne in propose.stdout.splitlines()
        if ligne.startswith("REVIEW_ARTIFACT_PATH ")
    )
    octets = propose.stdout[propose.stdout.index("{") :].encode("utf-8")
    tete = hashlib.sha1(f"revue-v3:{_RUN_ID}".encode()).hexdigest()
    github.add_approved_pr(number=8401, head_sha=tete, base_sha="9" * 40, review_id=8411)
    github.put_blob(path=chemin, ref=tete, content=octets)
    with local_github_server(github) as github_url:
        enregistre = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "record-release-batch-attestation",
                "--release-id", V3_ID,
                "--review-id", REVUE_V3,
                "--repository", REPOSITORY,
                "--pull-request", "8401",
                "--expected-head", tete,
                "--review-artifact-path", chemin,
            ],
            {**attestor, **_acces_github(github_url, banc["jeton"])},
        )
    print("REAL_CHAIN_RECORD", enregistre.stdout.strip()[-600:], enregistre.stderr[-1500:])
    assert enregistre.returncode == 0, enregistre.stderr
    return {
        "propose": propose.stdout.splitlines()[0],
        "revue": json.loads(octets),
        "record": enregistre.stdout.strip().splitlines()[-1],
    }


def _creer_les_jobs(pg: dict[str, str], cibles: Sequence[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    """Un job de publication par placement, nommant l'attestation V3 qui le couvre."""
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
                (V3_ID, collection, f"{prefixe}%"),
            ).fetchall()
            assert len(lignes) == 1, (collection, prefixe, lignes)
            resource_id, artifact_id, sha, run_id, version, attestation_id = lignes[0]
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
                "collection": collection, "sha": sha, "resource_id": resource_id,
                "attestation_id": str(attestation_id),
            }
        conn.commit()
    return jobs


def _environnement_worker_b(
    control_pg: dict[str, str], produit_pg: dict[str, str], readiness: Mapping[str, str]
) -> dict[str, str]:
    return {
        **readiness,
        "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
        "PG_RAG_DSN": produit_pg["publisher_dsn"],
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "",
    }


def _lancer_worker_b(
    control_pg: dict[str, str],
    produit_pg: dict[str, str],
    banc: Mapping[str, Any],
    github: LocalGitHub,
    *,
    arguments: Sequence[str],
    readiness: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    with local_github_server(github) as github_url:
        return _run(
            "ingestor.ingestion_worker.multilevel_publication_resume_cli",
            arguments,
            {
                **_environnement_worker_b(control_pg, produit_pg, readiness or banc["readiness_v3"]),
                **_acces_github(github_url, banc["jeton"]),
            },
            timeout=3600,
        )


def _arguments_b(banc: Mapping[str, Any]) -> list[str]:
    return _arguments_worker_b(
        magasin=banc["magasin"], transfert=banc["transfert_v3"], modele=banc["modele"]
    )


@pytest.fixture(scope="module")
def publie(
    atteste: dict[str, Any],
    control_pg: dict[str, str],
    produit_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> dict[str, Any]:
    """Worker B, readiness de staging nommant V3, sur le sous-ensemble borné."""
    jobs = _creer_les_jobs(control_pg, PLACEMENTS_PUBLIES)
    debut = time.monotonic()
    worker = _lancer_worker_b(
        control_pg, produit_pg, banc, github,
        arguments=[*_arguments_b(banc), "--poll-interval-s", "1", "--max-iterations", str(len(jobs))],
    )
    duree = time.monotonic() - debut
    print("REAL_CHAIN_WORKER_B_SECONDS", round(duree, 1))
    print("REAL_CHAIN_WORKER_B_STDOUT", worker.stdout[-4000:])
    print("REAL_CHAIN_WORKER_B_STDERR", worker.stderr[-4000:])
    assert worker.returncode == 0, worker.stderr
    return {
        "jobs": jobs,
        "sortie": worker.stdout,
        "erreurs": [
            ligne for ligne in worker.stderr.splitlines()
            if ligne.startswith("MULTILEVEL_PUBLICATION_WORKER_ITERATION_ERROR")
        ],
        "succes": worker.stdout.count("status=succeeded") == len(jobs),
        "secondes": duree,
        "produit": _produit(produit_pg),
    }


def _refus_au_demarrage(sortie: subprocess.CompletedProcess[str]) -> str:
    assert sortie.returncode == 1, (sortie.stdout, sortie.stderr)
    assert "MULTILEVEL_PUBLICATION_WORKER_STARTUP_FAILED" in sortie.stderr, sortie.stderr
    assert "ITERATION" not in sortie.stdout, sortie.stdout
    return sortie.stderr.strip()


# --- La chaîne ----------------------------------------------------------------


def test_les_releases_reelles_sont_celles_attendues() -> None:
    """Un skip n'est pas une exécution : les octets réels sont vérifiés ici."""
    assert _sha(V2_DIR / "production-profile-gate.release.json") == V2_MANIFEST_SHA256
    assert _sha(V3_DIR / "production-profile-gate.release.json") == V3_MANIFEST_SHA256
    assert TRANSFER_V2.is_file()
    assert len(list(PROFILES_DIR.glob("*.yml"))) == 11
    pii = json.loads((V3_DIR / "pii_evidence.json").read_bytes())
    statuts = {r["content_sha256"][:12]: r["status"] for r in pii["results"]}
    assert statuts[CONTENU_DRA] == "DETECTED_REVIEWED_ACCEPTED"


def test_1_rattrapage_v2_puis_adoption_v3_sous_autorites_r2_reelles(adopte: dict[str, Any]) -> None:
    assert "examined=479 written=479" in adopte["rattrapage"]
    assert "placements=479 written=479" in adopte["adoption"]


def test_e_une_r3_etrangere_ou_incomplete_n_est_pas_liee(
    r3_enregistrees: dict[str, str],
    control_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> None:
    """AVANT toute liaison : une r3 d'une autre collection, ou une r3 qui ne
    nomme pas un contenu, ne lie rien — pas même les placements qu'elle couvre."""
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: PLC0415

    r3 = _r3_derivees()
    document = json.loads(r3["rag_nexus_dgemc_terminale_option"][1])
    retire = document["allowed_content_sha256"][0]
    document["authorization_id"] = f"lot41a-bench-dgemc-partielle-{_RUN_ID}"
    document["allowed_content_sha256"] = document["allowed_content_sha256"][1:]
    partielle = ScopeAuthorizationArtifactV2.model_validate(document)
    # Une autorité qui nomme TOUS les contenus de SVT terminale, mais dont le
    # scope est SVT première : seule la collection la disqualifie.
    document = json.loads(r3["rag_nexus_svt_premiere_specialite"][1])
    document["authorization_id"] = f"lot41a-bench-svt-autre-collection-{_RUN_ID}"
    document["allowed_content_sha256"] = json.loads(r3["rag_nexus_svt_terminale_specialite"][1])[
        "allowed_content_sha256"
    ]
    autre_collection = ScopeAuthorizationArtifactV2.model_validate(document)
    with local_github_server(github) as github_url:
        acces = _acces_github(github_url, banc["jeton"])
        _enregistrer(
            github=github,
            env={"PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg), **acces},
            documents=[
                (partielle.authorization_id, partielle.canonical_bytes()),
                (autre_collection.authorization_id, autre_collection.canonical_bytes()),
            ],
            numero=8300,
        )
        avant = _compte_par_table(control_pg)
        assert avant["sealed_release_publication_authorizations"] == 0
        attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg), **acces}
        etrangere = dict(r3_enregistrees)
        etrangere["rag_nexus_svt_terminale_specialite"] = r3_enregistrees["rag_nexus_svt_premiere_specialite"]
        incomplete = dict(r3_enregistrees)
        incomplete["rag_nexus_dgemc_terminale_option"] = partielle.authorization_id
        mauvaise_collection = dict(r3_enregistrees)
        mauvaise_collection["rag_nexus_svt_terminale_specialite"] = autre_collection.authorization_id
        for nom, mapping, motif in (
            ("r3 d'une autre collection", etrangere, "does not name content"),
            ("contenus complets, autre collection", mauvaise_collection, "covers collection"),
            ("r3 incomplète", incomplete, f"does not name content {retire}"),
        ):
            refus = _run(
                "ingestor.ingestion_worker.attest_publication_cli", _arguments_de_liaison(mapping), attestor
            )
            print("REAL_CHAIN_E", nom, refus.stderr.strip())
            assert refus.returncode == 1 and "BINDING_REFUSED" in refus.stderr, refus.stderr
            assert motif in refus.stderr, refus.stderr
    assert _compte_par_table(control_pg) == avant


def test_2_les_r3_sont_liees_sans_reecrire_l_acquis(
    lie: dict[str, Any], adopte: dict[str, Any], control_pg: dict[str, str]
) -> None:
    assert "collections=11 written=479 already_present=0" in lie["sortie"], lie["sortie"]
    assert "written=0 already_present=479" in lie["rejeu"], lie["rejeu"]
    assert lie["ecarts"] == {"sealed_release_publication_authorizations": (0, 479)}, lie["ecarts"]
    # L'autorité d'ACQUISITION reste celle des r2 : rien n'est réécrit.
    assert _etat_historique(control_pg) == adopte["historique"]


def test_3_la_revue_batch_nomme_les_r3_et_l_attestation_est_enregistree(
    atteste: dict[str, Any], lie: dict[str, Any], adopte: dict[str, Any]
) -> None:
    assert "written=479" in atteste["propose"] and "blocked=0" in atteste["propose"], atteste
    assert "written=479" in atteste["record"], atteste["record"]
    texte = json.dumps(atteste["revue"])
    assert all(identifiant in texte for identifiant in lie["r3"].values())
    assert not any(identifiant in texte for identifiant in adopte["r2"].values())
    assert atteste["revue"]["placement_evidence"]["currentness"] == "official_snapshot"


def test_4a_worker_b_demarre_qualifie_et_l_attestation_liee_aux_r3_tient(
    publie: dict[str, Any], control_pg: dict[str, str]
) -> None:
    """Démarrage sous qualification, puis vérification vivante de l'attestation
    batch (LOT41A-V2, contenu nommé, même collection) : aucune n'est invalidée,
    et aucun refus ne porte sur l'autorité."""
    sortie = publie["sortie"]
    assert "authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION" in sortie, sortie
    assert f"release_id={V3_ID}" in sortie
    print("REAL_CHAIN_WORKER_B_ERRORS", publie["erreurs"])
    for erreur in publie["erreurs"]:
        assert "authorization" not in erreur and "LOT41A" not in erreur, erreur
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        invalidees = conn.execute(
            "SELECT count(*) FROM ingestion_control.publication_attestations"
            " WHERE release_id = %s AND invalidated_at IS NOT NULL",
            (V3_ID,),
        ).fetchone()
        conn.rollback()
    assert invalidees == (0,), invalidees


def test_4_worker_b_publie_le_sous_ensemble_sous_qualification(
    publie: dict[str, Any],
    lie: dict[str, Any],
    control_pg: dict[str, str],
    produit_pg: dict[str, str],
) -> None:
    assert publie["succes"], publie["erreurs"]

    # Plan de contrôle, relu indépendamment.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        etats = conn.execute(
            "SELECT resource_state, count(*) FROM ingestion_control.resources"
            " WHERE resource_id = ANY(%s) GROUP BY 1",
            ([job["resource_id"] for job in publie["jobs"].values()],),
        ).fetchall()
        conn.rollback()
    assert etats == [("RETRIEVAL_ELIGIBLE", 4)], etats

    # Base produit, relue indépendamment.
    produit = publie["produit"]
    placements = produit["placements"]
    print("REAL_CHAIN_PRODUCT_PLACEMENTS", placements)
    print("REAL_CHAIN_PRODUCT_CHUNKS", produit["chunks"], "ARTIFACTS", produit["artifacts"])
    assert {(p[2], p[1][:12]) for p in placements} == set(PLACEMENTS_PUBLIES)
    assert {p[3] for p in placements} == {"official_snapshot"}
    assert {(p[4], p[5]) for p in placements} == {("active", "reviewed")}
    assert {(p[2], p[6]) for p in placements} == {(c, lie["r3"][c]) for c, _s in PLACEMENTS_PUBLIES}
    assert {p[7] for p in placements} == {j["attestation_id"] for j in publie["jobs"].values()}
    assert produit["artifacts"] == 3
    catalogue = {
        a["content_sha256"]: len(a["chunks"])
        for a in json.loads((V3_DIR / "artifacts.release.json").read_bytes())["artifacts"]
    }
    for artifact_id, _collection, nombre, dim_min, dim_max, nuls in produit["chunks"]:
        assert (dim_min, dim_max, nuls) == (1024, 1024, 0)
        assert nombre == catalogue[artifact_id], (artifact_id, nombre, catalogue[artifact_id])

    # Retrieval réel, sous une identité SVT terminale.
    with psycopg.connect(produit_pg["admin_dsn"]) as conn:
        texte = conn.execute(
            "SELECT text FROM public.rag_chunks WHERE artifact_id LIKE %s ORDER BY chunk_index LIMIT 1",
            ("8eb23c91b035%",),
        ).fetchone()
        conn.rollback()
    assert texte is not None and texte[0]
    requete = " ".join([m for m in str(texte[0]).split() if len(m) > 6][:4])
    trouves = _recuperer(produit_pg, "rag_nexus_svt_terminale_specialite", requete)
    print("REAL_CHAIN_RETRIEVAL", requete, [(c.artifact_id[:12], c.source_uri) for c in trouves])
    assert any(c.artifact_id.startswith("8eb23c91b035") for c in trouves), trouves
    assert all(c.artifact_id.startswith("8eb23c91b035") for c in trouves), "une autre collection a fui"


# --- Contre-épreuves ----------------------------------------------------------


def test_a_une_readiness_d_une_autre_release_est_refusee(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    refus = _lancer_worker_b(
        control_pg, produit_pg, banc, github,
        arguments=[*_arguments_b(banc), "--once"], readiness=banc["readiness_v2"],
    )
    print("REAL_CHAIN_A", _refus_au_demarrage(refus))
    assert "staging readiness authorises release manifest" in refus.stderr
    assert _produit(produit_pg) == publie["produit"]


def test_b_un_manifeste_de_profils_altere_ou_de_staging_est_refuse(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    from ingestor.ingestion_profiles.registry import (  # noqa: PLC0415
        load_profile_registry,
        profile_fingerprint,
    )

    tmp_path: Path = banc["tmp_path"]
    brut = PROFILE_MANIFEST.read_text(encoding="utf-8")
    empreinte = brut.split("fingerprint: ", 1)[1].split("\n", 1)[0].strip()
    altere = tmp_path / "altered_profile_manifest.yml"
    altere.write_text(brut.replace(empreinte, "0" * 64, 1), encoding="utf-8")
    staging = tmp_path / "bench_staging_profile_manifest.json"
    registre = load_profile_registry(PROFILES_DIR)
    staging.write_text(
        json.dumps({
            "manifest_kind": "NEXUS_STAGING_PROFILE_MANIFEST_V1",
            "provenance": "real-release bench; test document",
            "generated_at": "2026-09-24T00:00:00Z",
            "authority_mode": "STAGING_LOCAL_GITHUB_ONLY",
            "production_approval": False,
            "profiles": [
                {"collection": c, "profile_version": v, "fingerprint": profile_fingerprint(p)}
                for (c, v), p in sorted(registre.items())
            ],
        }),
        encoding="utf-8",
    )
    for fichier in (altere, staging):
        arguments = _remplacer(_arguments_b(banc), "--profile-manifest-path", str(fichier))
        arguments = _remplacer(arguments, "--profile-manifest-sha256", _sha(fichier))
        refus = _lancer_worker_b(
            control_pg, produit_pg, banc, github, arguments=[*arguments, "--once"]
        )
        print("REAL_CHAIN_B", fichier.name, _refus_au_demarrage(refus))
    assert _produit(produit_pg) == publie["produit"]


def test_c_une_chaine_pii_d_une_autre_ancre_est_refusee(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    """Une ancre de revue qui n'est pas l'ancre réelle : clé de TEST déclarée
    ``test``, puis clé étrangère déclarée ``production``. Le reçu réel ne se
    vérifie sous aucune des deux."""
    from nexus_contracts.review_binding import public_key_hex  # noqa: PLC0415

    reelle = json.loads((REPOSITORY_ROOT / CHAINE_PII_V3["--review-trust-anchor-path"]).read_bytes())
    for environnement in ("test", "production"):
        ancre = banc["tmp_path"] / f"bench_review_binding_anchor_{environnement}.json"
        ancre.write_text(
            json.dumps({
                "protocol_version": reelle["protocol_version"],
                "keys": [{
                    **reelle["keys"][0],
                    "public_key": public_key_hex(secrets.token_hex(32)),
                    "environment": environnement,
                    "comment": "bench key — never an authority",
                }],
            }),
            encoding="utf-8",
        )
        arguments = _remplacer(_arguments_b(banc), "--review-trust-anchor-path", str(ancre))
        arguments = _remplacer(arguments, "--review-trust-anchor-sha256", _sha(ancre))
        refus = _lancer_worker_b(control_pg, produit_pg, banc, github, arguments=[*arguments, "--once"])
        print("REAL_CHAIN_C", environnement, _refus_au_demarrage(refus))
    assert _produit(produit_pg) == publie["produit"]


def test_f_une_readiness_de_staging_sous_production_est_refusee(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    sous_production = {**banc["readiness_v3"], "NEXUS_ENVIRONMENT": "production"}
    protocole_de_production = {
        **banc["readiness_v3"],
        "NEXUS_EXPECTED_READINESS_PROTOCOL": "NEXUS-PRODUCTION-READINESS-V1",
        "NEXUS_READINESS_REHEARSAL_TRUST_ANCHOR": banc["readiness_v3"]["NEXUS_STAGING_READINESS_TRUST_ANCHOR"],
        "NEXUS_RELEASE_SHA": "c" * 40,
    }
    for nom, readiness in (("environment=production", sous_production), ("production protocol", protocole_de_production)):
        refus = _lancer_worker_b(
            control_pg, produit_pg, banc, github,
            arguments=[*_arguments_b(banc), "--once"], readiness=readiness,
        )
        print("REAL_CHAIN_F", nom, _refus_au_demarrage(refus))
    assert _produit(produit_pg) == publie["produit"]


def test_g_une_reprise_apres_ecriture_produit_ne_duplique_ni_ne_change_l_autorite(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    """Interruption APRÈS l'écriture produit, AVANT l'acquittement : le bail
    tombe, les MÊMES jobs redeviennent réclamables et sont repris."""
    # Une reprise suppose une première écriture produit : sans elle, ce test
    # ne prouverait rien, et il le dit au lieu de passer.
    assert publie["succes"], f"no first publication to resume: {publie['erreurs']}"
    jobs = list(publie["jobs"])
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        remis = conn.execute(
            "UPDATE ingestion_control.jobs SET status = 'queued', lease_token = NULL,"
            "       lease_expires_at = NULL, claimed_by = NULL"
            " WHERE job_id = ANY(%s) RETURNING job_id",
            (jobs,),
        ).fetchall()
        conn.commit()
    assert len(remis) == 4
    repris = _lancer_worker_b(
        control_pg, produit_pg, banc, github,
        arguments=[*_arguments_b(banc), "--poll-interval-s", "1", "--max-iterations", "4"],
    )
    print("REAL_CHAIN_G", repris.stdout[-1500:], repris.stderr[-1500:])
    assert repris.returncode == 0, repris.stderr
    assert repris.stdout.count("status=succeeded") == 4, repris.stdout + repris.stderr
    assert _produit(produit_pg) == publie["produit"]
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        etats = conn.execute(
            "SELECT status, count(*) FROM ingestion_control.jobs WHERE job_id = ANY(%s) GROUP BY 1",
            (jobs,),
        ).fetchall()
        conn.rollback()
    assert etats == [("succeeded", 4)], etats


# --- (d) sur une seconde base : l'autorité r2 (V1), sans liaison ---------------


@pytest.fixture(scope="module")
def control_pg_sans_liaison() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("v3-real-unbound")


def test_d_une_autorite_r2_sans_liaison_ne_publie_rien(
    control_pg_sans_liaison: dict[str, str],
    produit_pg: dict[str, str],
    banc: dict[str, Any],
) -> None:
    """Sans ``bind-publication-authorities``, les faits batch portent l'autorité
    d'ACQUISITION (r2, LOT41A-V1). Elle ne fonde aucune publication."""
    pg = control_pg_sans_liaison
    github = LocalGitHub()
    etat = _jusqu_a_l_adoption(pg, banc, github)
    attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(pg)}
    # La liaison des r2 elles-mêmes est refusée : V1 ne borne aucun contenu.
    with local_github_server(github) as github_url:
        lier_r2 = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_liaison(etat["r2"]),
            {**attestor, **_acces_github(github_url, banc["jeton"])},
        )
    print("REAL_CHAIN_D_BIND_R2", lier_r2.stderr.strip())
    assert lier_r2.returncode == 1 and "LOT41A-V2" in lier_r2.stderr, lier_r2.stderr

    revue = f"{REVUE_V3}-sans-liaison"
    propose = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_de_proposition_v3(banc["transfert_v3"], revue=revue),
        attestor,
    )
    print("REAL_CHAIN_D_PROPOSE", propose.returncode, propose.stdout.splitlines()[:1], propose.stderr[-800:])
    produit_avant = _produit(produit_pg)
    if propose.returncode != 0:
        return
    chemin = next(
        ligne.split(" ", 1)[1].strip()
        for ligne in propose.stdout.splitlines()
        if ligne.startswith("REVIEW_ARTIFACT_PATH ")
    )
    octets = propose.stdout[propose.stdout.index("{") :].encode("utf-8")
    assert all(identifiant in octets.decode() for identifiant in etat["r2"].values())
    tete = hashlib.sha1(f"revue-v3-sans-liaison:{_RUN_ID}".encode()).hexdigest()
    github.add_approved_pr(number=8501, head_sha=tete, base_sha="9" * 40, review_id=8511)
    github.put_blob(path=chemin, ref=tete, content=octets)
    with local_github_server(github) as github_url:
        enregistre = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "record-release-batch-attestation",
                "--release-id", V3_ID, "--review-id", revue, "--repository", REPOSITORY,
                "--pull-request", "8501", "--expected-head", tete, "--review-artifact-path", chemin,
            ],
            {**attestor, **_acces_github(github_url, banc["jeton"])},
        )
    print("REAL_CHAIN_D_RECORD", enregistre.returncode, enregistre.stdout[-400:], enregistre.stderr[-800:])
    if enregistre.returncode != 0:
        return
    jobs = _creer_les_jobs(pg, [("rag_nexus_svt_terminale_specialite", "8eb23c91b035")])
    worker = _lancer_worker_b(
        pg, produit_pg, banc, github,
        arguments=[*_arguments_b(banc), "--poll-interval-s", "1", "--max-iterations", "1"],
    )
    print("REAL_CHAIN_D_WORKER_B", worker.stdout[-1200:], worker.stderr[-1500:])
    assert "status=succeeded" not in worker.stdout, worker.stdout
    assert "LOT41A-V2" in worker.stderr or "does not bind content" in worker.stderr, worker.stderr
    assert _produit(produit_pg) == produit_avant
    with psycopg.connect(superuser_dsn(pg)) as conn:
        etat_ressource = conn.execute(
            "SELECT resource_state FROM ingestion_control.resources WHERE resource_id = %s",
            (next(iter(jobs.values()))["resource_id"],),
        ).fetchone()
        conn.rollback()
    assert etat_ressource == ("NEEDS_REVIEW",), etat_ressource


# --- Retrieval ----------------------------------------------------------------


def _recuperer(produit: dict[str, str], collection: str, requete: str) -> list[Any]:
    """Le chemin de retrieval réel : identité signée, scope serveur, pgvector.

    Repris du test d'acceptation batch, pour une collection SVT terminale."""
    import base64  # noqa: PLC0415
    import hmac  # noqa: PLC0415

    from ingestor.collection_config import load_collection_config  # noqa: PLC0415
    from ingestor.identity_v2 import (  # noqa: PLC0415
        load_identity_verifier_config,
        verify_identity_token,
    )
    from ingestor.retrieval_pg_v2 import PgCandidateStore  # noqa: PLC0415
    from ingestor.retrieval_scope_v2 import build_server_retrieval_scope  # noqa: PLC0415

    secret = "banc-reel-v3-internal-secret-32-bytes-min"
    variables = {
        "NEXUS_INTERNAL_TOKEN_SECRET": secret,
        "NEXUS_INTERNAL_TOKEN_ISSUER": "banc-cockpit",
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": "banc-engine",
        "NEXUS_SSO_ISSUER": "banc-sso",
        "NEXUS_SSO_AUDIENCE": "banc-cockpit-audience",
    }
    anciens = {cle: os.environ.get(cle) for cle in variables}
    os.environ.update(variables)
    try:
        config = load_identity_verifier_config()
        artefact = config.artifact
        maintenant = int(time.time())
        identite = {
            "aud": variables["NEXUS_SSO_AUDIENCE"], "exp": maintenant + 600,
            "iss": variables["NEXUS_SSO_ISSUER"], "jti": "banc-reel-v3-jti",
            "tenant": "libre_terminale", "niveau": "terminale", "role": "admin",
            "school_year": "2026-2027", "sub": "psn_bancreelv30000001",
            "pedagogical_profile": {
                "voie": "generale", "matieres": ["svt"], "statut_enseignement": "specialite",
                "candidat": "libre", "audience": "libre",
            },
        }
        charge = {
            "protocol_version": "1",
            "iss": variables["NEXUS_INTERNAL_TOKEN_ISSUER"],
            "aud": variables["NEXUS_INTERNAL_TOKEN_AUDIENCE"],
            "sub": identite["sub"], "jti": identite["jti"],
            "iat": maintenant, "exp": maintenant + 300,
            "identity": identite,
            "scope_id": artefact.scope_id,
            "scope_digest": artefact.sha256_digest(),
            "allowed_collections": [sujet.collection for sujet in artefact.subjects],
        }

        def _b64(valeur: bytes) -> str:
            return base64.urlsafe_b64encode(valeur).rstrip(b"=").decode("ascii")

        entete = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        corps = _b64(json.dumps(charge).encode())
        signature = hmac.new(secret.encode(), f"{entete}.{corps}".encode("ascii"), hashlib.sha256).digest()
        verifiee = verify_identity_token(f"{entete}.{corps}.{_b64(signature)}", config=config)
        scope = build_server_retrieval_scope(
            verifiee,
            collection=collection,
            collection_config=load_collection_config(ENGINE_ROOT / "configs/rag_collections.yml"),
        )
        store = PgCandidateStore(lambda: psycopg.connect(produit["retrieval_dsn"]), scope)
        return list(store.lexical(raw_query=requete, collection=collection, limit=10))
    finally:
        for cle, valeur in anciens.items():
            if valeur is None:
                os.environ.pop(cle, None)
            else:
                os.environ[cle] = valeur
