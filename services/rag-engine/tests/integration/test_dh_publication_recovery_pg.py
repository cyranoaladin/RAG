"""Lot DH — récupération d'une publication dont la revue batch a été fermée trop tôt.

Parcours reproduit sur PostgreSQL jetable, par les VRAIS outils et CLI :

    revue valide -> attestations -> jobs (outil DG) -> fermeture de la PR
    -> refus réel de Worker B -> aperçu -> annulation (rôle applicatif)
    -> invalidation (rôle attestor) -> nouvelle revue de test -> nouvelles
    attestations -> nouveaux jobs -> préconditions -> Worker B -> publication
    -> retrieval -> rejeu sans doublon -> contrôle de fermeture.

Contre-épreuves : mauvaise base, mauvaise revue, mauvais rôle (outil ET
privilège SQL), mêmes comptes avec mauvaises identités, bail actif, complétion
tardive, interruption entre opérations et au milieu d'une opération.

**Autorités de TEST.** Les revues #7001/#7002 et les autorisations de scope
sont servies par ``LocalGitHub`` : ce sont des FIXTURES du banc, jamais des
approbations réelles. La décision de revue reste rendue par le code réel
d'ADR-0025.

**Embeddings de TEST.** Le modèle E5 n'est pas disponible dans cet
environnement ; l'étape de publication exécute la VRAIE itération de Worker B
(``run_publication_resume_iteration``, publisher gouverné, pins, retrieval)
avec ``CallableEmbeddingProvider`` — l'adaptateur de test explicite du dépôt,
dont l'identité de modèle est ``DEBUG`` et ne peut jamais se faire passer pour
E5. Le CLI de Worker B sur E5 réel reste une épreuve de la machine opérateur
(commande consignée dans le rapport DH).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts/go_live"))

from _local_github import REPOSITORY, VALID_TOKEN, LocalGitHub, local_github_server  # noqa: E402
from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    start_rag_product_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

if os.environ.get("NEXUS_DH_RECOVERY_PG") != "1":
    pytest.skip("banc DH non demandé (NEXUS_DH_RECOVERY_PG=1)", allow_module_level=True)

# Les primitives du banc batch (lot CU) sont RÉUTILISÉES, pas recopiées : état
# historique, autorisations r4 de test, proposition et enregistrement par les
# vrais CLI. Leur module se protège par une variable d'opt-in ; elle n'est
# posée que le temps de l'import.
_precedent = os.environ.get("NEXUS_BATCH_CLI_ACCEPTANCE")
os.environ["NEXUS_BATCH_CLI_ACCEPTANCE"] = "1"
try:
    import test_batch_publication_cli_acceptance as banc_batch  # noqa: E402
finally:
    if _precedent is None:
        os.environ.pop("NEXUS_BATCH_CLI_ACCEPTANCE", None)
    else:
        os.environ["NEXUS_BATCH_CLI_ACCEPTANCE"] = _precedent

import staging_v4_publication_recovery as dh  # noqa: E402

OUTIL_DH = REPOSITORY_ROOT / "scripts/go_live/staging_v4_publication_recovery.py"
OUTIL_DG = REPOSITORY_ROOT / "scripts/go_live/staging_v4_enqueue_publication.py"
ATTEST_CLI = "ingestor.ingestion_worker.attest_publication_cli"
PR_PERIMEE, PR_REPRISE = 7001, 7002
TETE_PERIMEE = hashlib.sha1(b"dh-revue-perimee-banc").hexdigest()
TETE_REPRISE = hashlib.sha1(b"dh-revue-reprise-banc").hexdigest()
REVUE_PERIMEE = "dh-revue-perimee-banc"
REVUE_REPRISE = "dh-revue-reprise-banc"
ATTENDU = {"attestations": 4, "resources": 4, "unique_contents": 2, "collections": 2, "publication_jobs": 4}


# ── bancs ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def inventaire_de_banc(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Un INVENTAIRE de modèle de banc : la release du banc en déclare
    l'empreinte. Ce n'est pas un modèle, et rien ne l'utilise comme tel."""
    racine = tmp_path_factory.mktemp("inventaire-e5-de-banc")
    (racine / "LISEZMOI").write_text("inventaire de banc DH — aucun poids de modèle\n")
    (racine / "SHA256SUMS").write_text(
        f"{hashlib.sha256((racine / 'LISEZMOI').read_bytes()).hexdigest()}  LISEZMOI\n"
    )
    precedent = os.environ.get("RAG_EMBEDDING_MODEL_CACHE_DIR")
    os.environ["RAG_EMBEDDING_MODEL_CACHE_DIR"] = str(racine)
    yield racine
    if precedent is None:
        os.environ.pop("RAG_EMBEDDING_MODEL_CACHE_DIR", None)
    else:
        os.environ["RAG_EMBEDDING_MODEL_CACHE_DIR"] = precedent


@pytest.fixture(scope="module")
def control_parcours() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("dh-recovery-chain")


@pytest.fixture(scope="module")
def control_perime() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("dh-recovery-stale")


@pytest.fixture(scope="module")
def product_pg() -> Iterator[dict[str, str]]:
    yield from start_rag_product_postgres("dh-recovery-product")


def _executer(script: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, check=False, timeout=600, cwd=REPOSITORY_ROOT,
        env={
            **os.environ, **env,
            "PYTHONPATH": f"{ENGINE_ROOT / 'src'}:{REPOSITORY_ROOT / 'packages/contracts/src'}",
        },
    )


def _outil(racine: Path, identite: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _executer(OUTIL_DH, ["--repository-root", str(racine), "--stale-review", str(identite), *args], env)


def _ecrire_identite(
    racine: Path, *, chemin: str, octets: bytes, pull_request: int = PR_PERIMEE,
    tete: str = TETE_PERIMEE, base: str = "ragdb", nom: str = "identite.json",
) -> Path:
    """L'identité de la revue périmée du banc, au format de celle de #257."""
    (racine / chemin).parent.mkdir(parents=True, exist_ok=True)
    (racine / chemin).write_bytes(octets)
    identite = racine / nom
    identite.write_text(json.dumps({
        "kind": dh.KIND_IDENTITE,
        "repository": REPOSITORY,
        "pull_request": pull_request,
        "head_sha": tete,
        "review_artifact_path": chemin,
        "review_artifact_sha256": hashlib.sha256(octets).hexdigest(),
        # La base jetable du banc s'appelle « ragdb » : la base historique du
        # banc reçoit donc un AUTRE nom, jamais celui de la cible.
        "database": base,
        "legacy_database": "ragdb_historique_du_banc",
        "expected": ATTENDU,
    }))
    return identite


def _preparer_etat_perime(
    control: dict[str, str], tmp_path: Path, github: LocalGitHub, jeton: Path
) -> dict[str, Any]:
    """Revue #7001 approuvée -> attestations -> jobs DG -> PR fermée."""
    banc = banc_batch._contexte_du_banc(tmp_path)
    github.add_approved_pr(number=PR_PERIMEE, head_sha=TETE_PERIMEE, base_sha="9" * 40, review_id=PR_PERIMEE + 10)
    with local_github_server(github) as url:
        env = banc_batch._environnement_d_autorite(control, github_url=url, jeton=jeton)
        artefacts = banc_batch._semer_etat_historique(control, contexte=banc, github=github, env=env)
        propose = banc_batch._run(ATTEST_CLI, banc_batch._arguments_de_proposition(banc, revue=REVUE_PERIMEE), env)
        assert propose.returncode == 0, propose.stderr
        chemin, octets = banc_batch._artefact_propose(propose.stdout)
        github.put_blob(path=chemin, ref=TETE_PERIMEE, content=octets)
        enregistre = banc_batch._run(ATTEST_CLI, banc_batch._arguments_d_enregistrement(
            banc, chemin=chemin, head=TETE_PERIMEE, revue=REVUE_PERIMEE, pull_request=PR_PERIMEE), env)
        assert enregistre.returncode == 0, enregistre.stderr
    enfile = _executer(OUTIL_DG, ["--release-id", banc.release_id, "--expected-jobs", "4"],
                       {"PG_INGESTION_CONTROL_DSN": app_dsn(control)})
    assert enfile.returncode == 0, enfile.stderr
    assert "crees=4" in enfile.stdout, enfile.stdout
    # Ce qui est arrivé à #257 : la PR n'est plus ouverte.
    github.close_pr(PR_PERIMEE)
    racine = tmp_path / "depot"
    identite = _ecrire_identite(racine, chemin=chemin, octets=octets)
    return {"banc": banc, "artefacts": artefacts, "chemin": chemin, "octets": octets,
            "racine": racine, "identite": identite}


def _etat_du_controle(control: dict[str, str]) -> dict[str, Any]:
    """Photographie complète des lignes que DH pourrait toucher."""
    with psycopg.connect(superuser_dsn(control)) as conn:
        jobs = conn.execute(
            "SELECT job_id, status, lease_token, lease_expires_at, claimed_by, attempt_count,"
            "       last_error, payload, updated_at FROM ingestion_control.jobs ORDER BY job_id"
        ).fetchall()
        attestations = conn.execute(
            "SELECT attestation_id, invalidated_at, invalidated_reason"
            "  FROM ingestion_control.publication_attestations ORDER BY attestation_id"
        ).fetchall()
        ressources = conn.execute(
            "SELECT resource_id, resource_state, state_version FROM ingestion_control.resources ORDER BY 1"
        ).fetchall()
        conn.rollback()
    return {"jobs": jobs, "attestations": attestations, "ressources": ressources}


def _encodeur_de_banc(passages: list[str]) -> list[list[float]]:
    """Vecteurs DÉTERMINISTES de test (1024 dimensions, jamais nuls)."""
    vecteurs = []
    for passage in passages:
        graine = hashlib.sha256(passage.encode("utf-8")).digest()
        vecteurs.append([((graine[i % 32] + i) % 251) / 125.0 - 1.0 + 1e-3 for i in range(1024)])
    return vecteurs


def _deps_worker_b(banc: Any, product_pg: dict[str, str]) -> Any:
    """Les dépendances que le CLI de Worker B assemble — sauf E5, remplacé par
    l'adaptateur de TEST explicite du dépôt (identité de modèle DEBUG)."""
    from ingestor.embedding_provider import CallableEmbeddingProvider
    from ingestor.ingestion_profiles.registry import load_profile_registry
    from ingestor.ingestion_worker.multilevel_publication_resume_cli import (
        _build_arg_parser,
        _extract_non_pdf_text,
        make_filesystem_artifact_reader,
        make_sealed_release_artifact_reader,
    )
    from ingestor.ingestion_worker.multilevel_runtime_authority import (
        load_multilevel_runtime_authorities,
        multilevel_runtime_authority_inputs_from_args,
    )
    from ingestor.ingestion_worker.publication_resume import PublicationResumeDeps

    args = _build_arg_parser().parse_args(banc_batch._arguments_de_worker_b(banc, iterations=1))
    profils = load_profile_registry(args.profiles_dir)
    autorites = load_multilevel_runtime_authorities(
        multilevel_runtime_authority_inputs_from_args(args), profile_registry=profils, environment="rehearsal",
    )
    resolver = autorites.placement_resolver
    catalogue = autorites.sealed_release_catalog
    return PublicationResumeDeps(
        owner="banc-dh-worker-b",
        product_dsn=product_pg["publisher_dsn"],
        artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
        sealed_artifact_reader=make_sealed_release_artifact_reader(args.artifact_store_dir),
        extract_text=_extract_non_pdf_text,
        embedding_provider=CallableEmbeddingProvider(encoder=_encodeur_de_banc),
        pii_evidence_registry=autorites.pii_evidence_registry,
        rights_evidence_registry=autorites.rights_evidence_registry,
        manifest_digest=resolver.release_profile_manifest_digest,
        placement_resolver=resolver,
        sealed_release_artifacts=catalogue.artifacts,
        sealed_media_type_invariant=catalogue.media_type_invariant,
    )


def _iterer_worker_b(control: dict[str, str], deps: Any, fois: int) -> list[Any]:
    from ingestor.ingestion_worker.publication_resume import run_publication_resume_iteration

    issues = []
    with psycopg.connect(app_dsn(control)) as conn:
        for _ in range(fois):
            issues.append(run_publication_resume_iteration(conn, deps=deps))
    return issues


class _Forge:
    """Expose la forge locale aux primitives GitHub appelées EN PROCESSUS."""

    def __init__(self, github: LocalGitHub, jeton: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.github, self.jeton, self.monkeypatch = github, jeton, monkeypatch

    def __enter__(self) -> str:
        self._serveur = local_github_server(self.github)
        url = self._serveur.__enter__()
        self.monkeypatch.setenv("NEXUS_GITHUB_API_BASE", url)
        self.monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(self.jeton))
        return url

    def __exit__(self, *exc: object) -> None:
        self._serveur.__exit__(*exc)


def _simuler_delai_ecoule(control: dict[str, str], job_id: object) -> None:
    """Simule l'écoulement du délai de reprise d'UN job (``next_attempt_at``).

    Seul le temps est simulé : ni statut, ni bail, ni compteur ne sont touchés.
    Sans cela, le banc devrait dormir le temps du backoff réel (10 s, 20 s)."""
    with psycopg.connect(superuser_dsn(control)) as conn:
        conn.execute("UPDATE ingestion_control.jobs SET next_attempt_at = now() WHERE job_id = %s", (job_id,))
        conn.commit()


# ── le parcours complet ────────────────────────────────────────────────────


def test_recuperation_de_bout_en_bout(
    inventaire_de_banc: Path,
    control_parcours: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_control.jobs import JobLeaseConflictError, claim_job, complete_job, record_job_retry

    control = control_parcours
    github, jeton = LocalGitHub(), tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    etat = _preparer_etat_perime(control, tmp_path, github, jeton)
    banc, racine, identite = etat["banc"], etat["racine"], etat["identite"]
    env_app = {"PG_INGESTION_CONTROL_DSN": app_dsn(control)}

    # ── 1. Refus RÉEL de Worker B : sa vraie itération, sur la PR fermée ──
    deps = _deps_worker_b(banc, product_pg)
    with _Forge(github, jeton, monkeypatch):
        issues = _iterer_worker_b(control, deps, 4)
    assert [issue.status for issue in issues] == ["retried"] * 4, issues
    assert all("reason=pull_request_not_open" in (issue.error or "") for issue in issues), issues
    jobs = [issue.job_id for issue in issues]
    # Le rôle applicatif ne PEUT pas persister l'invalidation : 4 actives.
    with psycopg.connect(superuser_dsn(control)) as conn:
        actives = conn.execute(
            "SELECT count(*) FROM ingestion_control.publication_attestations WHERE invalidated_at IS NULL"
        ).fetchone()[0]
        conn.rollback()
    assert actives == 4

    # Un job épuise ses tentatives (dead_letter) ; un autre est réclamé par un
    # worker qui s'arrête ensuite en gardant son bail (2 s).
    for _ in range(2):
        _simuler_delai_ecoule(control, jobs[0])
        with _Forge(github, jeton, monkeypatch):
            (issue,) = _iterer_worker_b(control, deps, 1)
        assert issue.job_id == jobs[0] and issue.status == "retried", issue
    _simuler_delai_ecoule(control, jobs[1])
    with psycopg.connect(app_dsn(control)) as conn:
        bail = claim_job(conn, owner="worker-b-interrompu", job_types=("publication_resume",), lease_duration_s=2)
        conn.commit()
    assert bail is not None and bail.job_id == jobs[1]

    # ── 2. Aperçu : bail ACTIF -> refus nommé, et rien d'écrit ──
    avant = _etat_du_controle(control)
    vue = _outil(racine, identite, ["preview"], env_app)
    assert vue.returncode == 1, vue.stdout + vue.stderr
    rendu = json.loads(vue.stdout[: vue.stdout.rindex("}") + 1])
    assert rendu["counts"]["job_states"] == {"dead_letter": 1, "queued": 2, "running_lease_active": 1}, rendu
    assert rendu["counts"]["attestation_states"] == {"active": 4}
    assert any("bail ACTIF" in ecart for ecart in rendu["ecarts"]), rendu
    empreinte_a, empreinte_j = rendu["attestation_set_sha256"], rendu["job_set_sha256"]
    annule = _outil(racine, identite, ["cancel-stale-jobs", "--attestation-set-sha256", empreinte_a,
                                       "--job-set-sha256", empreinte_j], env_app)
    assert annule.returncode == 1 and "bail ACTIF" in annule.stderr, annule.stdout + annule.stderr
    assert _etat_du_controle(control) == avant

    # ── 3. Mauvais rôle : refusé par l'outil, ET par PostgreSQL ──
    mauvais = _outil(racine, identite, ["cancel-stale-jobs", "--attestation-set-sha256", empreinte_a,
                                        "--job-set-sha256", empreinte_j],
                     {"PG_INGESTION_CONTROL_DSN": attestor_dsn(control)})
    assert mauvais.returncode == 1 and "rôle 'ingestion_control_attestor'" in mauvais.stderr, mauvais.stderr
    with psycopg.connect(attestor_dsn(control)) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE ingestion_control.jobs SET status = 'cancelled' WHERE job_id = %s", (jobs[2],))
        conn.rollback()
    with psycopg.connect(app_dsn(control)) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE ingestion_control.publication_attestations SET invalidated_at = now(),"
                         " invalidated_reason = 'x'")
        conn.rollback()
    with _Forge(github, jeton, monkeypatch):
        mauvais = _outil(racine, identite, ["invalidate-stale-attestations", "--attestation-set-sha256", empreinte_a],
                         {"PG_INGESTION_CONTROL_ATTESTOR_DSN": app_dsn(control)})
    assert mauvais.returncode == 1 and "rôle 'ingestion_control_app'" in mauvais.stderr, mauvais.stderr
    assert _etat_du_controle(control) == avant

    # ── 4. Le bail EXPIRE (sans être libéré) : annulation, pas confusion ──
    time.sleep(2.5)
    vue = _outil(racine, identite, ["preview"], env_app)
    assert vue.returncode == 0, vue.stdout + vue.stderr
    rendu = json.loads(vue.stdout[: vue.stdout.rindex("}") + 1])
    assert rendu["counts"]["job_states"] == {"dead_letter": 1, "queued": 2, "running_lease_expired": 1}
    assert (rendu["attestation_set_sha256"], rendu["job_set_sha256"]) == (empreinte_a, empreinte_j)
    annule = _outil(racine, identite, ["cancel-stale-jobs", "--attestation-set-sha256", empreinte_a,
                                       "--job-set-sha256", empreinte_j], env_app)
    assert annule.returncode == 0, annule.stderr
    assert ("annules_bail_expire=1 annules_en_file=2 preserves_dead_letter=1") in annule.stdout, annule.stdout

    # Complétion TARDIVE du worker interrompu : refusée, rien n'est écrasé.
    with psycopg.connect(app_dsn(control)) as conn:
        with pytest.raises(JobLeaseConflictError):
            complete_job(conn, job_id=bail.job_id, lease_token=bail.lease_token, status="succeeded")
        conn.rollback()
        with pytest.raises(JobLeaseConflictError):
            record_job_retry(conn, job_id=bail.job_id, lease_token=bail.lease_token, error="tardif")
        conn.rollback()
        # Un worker relancé ne réclame rien : tout est terminal.
        assert claim_job(conn, owner="worker-b-relance", job_types=("publication_resume",)) is None
        conn.rollback()
    apres_annulation = _etat_du_controle(control)
    par_job = {ligne[0]: ligne for ligne in apres_annulation["jobs"]}
    assert par_job[jobs[0]][1] == "dead_letter"
    for job_id in jobs[1:]:
        statut, bail_restant, motif, charge = par_job[job_id][1], par_job[job_id][2], par_job[job_id][6], par_job[job_id][7]
        assert statut == "cancelled" and bail_restant is None
        # Le refus de Worker B reste lisible : l'annulation ne l'efface pas.
        assert "pull_request_not_open" in (motif or ""), motif
        marque = charge[dh.CLE_ANNULATION]
        assert marque["attestation_set_sha256"] == empreinte_a and marque["cancelled_at"]
    assert par_job[jobs[1]][7][dh.CLE_ANNULATION]["previous_lease"] == "expired_not_released"
    assert par_job[jobs[1]][7][dh.CLE_ANNULATION]["previous_claimed_by"] == "worker-b-interrompu"

    # ── 5. Interruption ENTRE opérations, puis rejeu identique : rien ne bouge ──
    rejeu = _outil(racine, identite, ["cancel-stale-jobs", "--attestation-set-sha256", empreinte_a,
                                      "--job-set-sha256", empreinte_j], env_app)
    assert rejeu.returncode == 0 and "deja_annules=3 preserves_dead_letter=1" in rejeu.stdout, rejeu.stdout
    assert _etat_du_controle(control) == apres_annulation

    # ── 6. Invalidation : jamais d'une revue qui vérifie encore ──
    github.pulls[PR_PERIMEE]["state"] = "open"
    with _Forge(github, jeton, monkeypatch):
        refus = _outil(racine, identite, ["invalidate-stale-attestations", "--attestation-set-sha256", empreinte_a],
                       {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control)})
    assert refus.returncode == 1 and "encore approuvée" in refus.stderr, refus.stderr
    github.close_pr(PR_PERIMEE)
    with _Forge(github, jeton, monkeypatch):
        invalide = _outil(racine, identite, ["invalidate-stale-attestations", "--attestation-set-sha256", empreinte_a],
                          {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control)})
    assert invalide.returncode == 0, invalide.stderr
    assert "live_reason=pull_request_not_open invalidees=4" in invalide.stdout, invalide.stdout
    apres_invalidation = _etat_du_controle(control)
    with _Forge(github, jeton, monkeypatch):
        rejeu = _outil(racine, identite, ["invalidate-stale-attestations", "--attestation-set-sha256", empreinte_a],
                       {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control)})
    assert rejeu.returncode == 0 and "deja_invalidees=4" in rejeu.stdout, rejeu.stdout
    assert _etat_du_controle(control) == apres_invalidation
    for _aid, moment, motif in apres_invalidation["attestations"]:
        assert moment is not None and motif.startswith(f"{dh.MARQUE_DH} attestation_set_sha256={empreinte_a} ")

    # ── 7. Nouvelle revue de TEST, nouvelles attestations, anciennes conservées ──
    github.add_approved_pr(number=PR_REPRISE, head_sha=TETE_REPRISE, base_sha="9" * 40, review_id=PR_REPRISE + 10)
    with local_github_server(github) as url:
        env = banc_batch._environnement_d_autorite(control, github_url=url, jeton=jeton)
        propose = banc_batch._run(ATTEST_CLI, banc_batch._arguments_de_proposition(banc, revue=REVUE_REPRISE), env)
        assert propose.returncode == 0, propose.stderr
        assert "already_present=4" in propose.stdout, propose.stdout  # projection réutilisée, non réécrite
        chemin_b, octets_b = banc_batch._artefact_propose(propose.stdout)
        assert chemin_b != etat["chemin"]
        github.put_blob(path=chemin_b, ref=TETE_REPRISE, content=octets_b)
        arguments = banc_batch._arguments_d_enregistrement(
            banc, chemin=chemin_b, head=TETE_REPRISE, revue=REVUE_REPRISE, pull_request=PR_REPRISE)
        enregistre = banc_batch._run(ATTEST_CLI, arguments, env)
        assert enregistre.returncode == 0 and "written=4 already_present=0" in enregistre.stdout, enregistre.stdout
        rejeu = banc_batch._run(ATTEST_CLI, arguments, env)
        assert "written=0 already_present=4" in rejeu.stdout, rejeu.stdout

    # ── 8. Préconditions avant mise en file ──
    def precondition(pr: int, tete: str, etape: str) -> subprocess.CompletedProcess[str]:
        with _Forge(github, jeton, monkeypatch):
            return _outil(racine, identite, ["review-precondition", "--pull-request", str(pr),
                                             "--expected-head", tete, "--stage", etape], env_app)

    assert precondition(PR_PERIMEE, TETE_PERIMEE, "enqueue").returncode == 1
    assert precondition(PR_REPRISE, TETE_PERIMEE, "enqueue").returncode == 1
    ok = precondition(PR_REPRISE, TETE_REPRISE, "enqueue")
    assert ok.returncode == 0 and "REVIEW_PRECONDITION_OK stage=enqueue" in ok.stdout, ok.stdout + ok.stderr

    enfile = _executer(OUTIL_DG, ["--release-id", banc.release_id, "--expected-jobs", "4"], env_app)
    assert enfile.returncode == 0 and "crees=4 deja_en_file=0" in enfile.stdout, enfile.stdout + enfile.stderr
    enfile = _executer(OUTIL_DG, ["--release-id", banc.release_id, "--expected-jobs", "4"], env_app)
    assert "crees=0 deja_en_file=4" in enfile.stdout, enfile.stdout
    lance = precondition(PR_REPRISE, TETE_REPRISE, "worker-b")
    assert lance.returncode == 0 and "live_jobs=4" in lance.stdout, lance.stdout + lance.stderr

    # L'aperçu reste rejouable : l'historique de #257 est intact, la reprise
    # est reconnue comme successeur, jamais comme ligne étrangère.
    vue = _outil(racine, identite, ["preview"], env_app)
    assert vue.returncode == 0, vue.stdout + vue.stderr
    rendu = json.loads(vue.stdout[: vue.stdout.rindex("}") + 1])
    assert rendu["counts"]["successor_attestations"] == 4 and rendu["counts"]["successor_jobs"] == 4
    assert rendu["attestation_set_sha256"] == empreinte_a

    fermeture = _outil(racine, identite, ["closure-check"], env_app)
    assert fermeture.returncode == 1, fermeture.stdout  # rien n'est encore publié

    # ── 9. Worker B publie, sous la nouvelle revue ──
    with _Forge(github, jeton, monkeypatch):
        issues = _iterer_worker_b(control, deps, 5)
    assert [issue.status for issue in issues[:4]] == ["succeeded"] * 4, issues
    assert issues[4].worked is False  # plus rien en file : ni ancien job, ni doublon
    contenus = sorted(contenu.content_sha256 for contenu in banc.contenus)
    avant_rejeu = banc_batch._compter_dans_le_produit(product_pg, contenus)
    assert avant_rejeu[0] == 2 and avant_rejeu[1] == 4 and avant_rejeu[2] > 0, avant_rejeu
    trouves = banc_batch._recuperer_par_le_retrieval(product_pg, banc)
    assert trouves and {c.artifact_id for c in trouves} <= set(contenus), trouves

    # ── 10. Rejeu après écriture produit : aucun doublon ──
    nouveaux = [issue.job_id for issue in issues[:4]]
    with psycopg.connect(superuser_dsn(control)) as conn:
        conn.execute(
            "UPDATE ingestion_control.jobs SET status = 'queued', lease_token = NULL,"
            " lease_expires_at = NULL, claimed_by = NULL WHERE job_id = ANY(%s)", (nouveaux,))
        conn.commit()
    with _Forge(github, jeton, monkeypatch):
        repris = _iterer_worker_b(control, deps, 4)
    assert [issue.status for issue in repris] == ["succeeded"] * 4, repris
    assert banc_batch._compter_dans_le_produit(product_pg, contenus) == avant_rejeu

    # ── 11. Fermeture : sûre seulement maintenant ; historique complet ──
    fermeture = _outil(racine, identite, ["closure-check"], env_app)
    assert fermeture.returncode == 0 and "REVIEW_CLOSURE_SAFE" in fermeture.stdout, fermeture.stdout + fermeture.stderr
    with psycopg.connect(superuser_dsn(control)) as conn:
        bilan = conn.execute(
            "SELECT human_review_pull_request, invalidated_at IS NULL, count(*)"
            "  FROM ingestion_control.publication_attestations GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
        statuts = dict(conn.execute(
            "SELECT status, count(*) FROM ingestion_control.jobs GROUP BY 1").fetchall())
        pins = conn.execute(
            "SELECT count(*), count(DISTINCT publication_review_pull_request),"
            "       min(publication_review_pull_request) FROM ingestion_control.publication_commit_pins"
        ).fetchone()
        conn.rollback()
    assert bilan == [(PR_PERIMEE, False, 4), (PR_REPRISE, True, 4)], bilan
    assert statuts == {"dead_letter": 1, "cancelled": 3, "succeeded": 4}, statuts
    assert pins == (4, 1, PR_REPRISE), pins


# ── contre-épreuves sur un état périmé partagé (aucune n'écrit) ────────────


@pytest.fixture(scope="module")
def etat_perime(
    inventaire_de_banc: Path, control_perime: dict[str, str], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("dh-perime")
    github, jeton = LocalGitHub(), tmp / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    etat = _preparer_etat_perime(control_perime, tmp, github, jeton)
    etat.update(control=control_perime, github=github, jeton=jeton)
    return etat


def _instantane(etat: dict[str, Any]) -> tuple[Any, Any]:
    revue = dh.charger_revue_perimee(etat["identite"], racine=etat["racine"])
    with psycopg.connect(app_dsn(etat["control"])) as conn:
        instantane = dh.prendre_instantane(conn, revue, avec_jobs=True)
        conn.rollback()
    return revue, instantane


def test_l_etat_perime_du_banc_est_conforme(etat_perime: dict[str, Any]) -> None:
    revue, instantane = _instantane(etat_perime)
    vue = dh.analyser(instantane, revue)
    assert vue.ecarts == [], vue.ecarts
    assert vue.comptes["job_states"] == {"queued": 4}
    assert vue.comptes["attestation_states"] == {"active": 4}


def test_mauvaise_base_et_mauvaise_revue_refusent_sans_ecrire(etat_perime: dict[str, Any]) -> None:
    control, racine = etat_perime["control"], etat_perime["racine"]
    env = {"PG_INGESTION_CONTROL_DSN": app_dsn(control)}
    avant = _etat_du_controle(control)
    cas = {
        "base": _ecrire_identite(racine, chemin=etat_perime["chemin"], octets=etat_perime["octets"],
                                 base="ragdb_profile_gate_v4", nom="mauvaise-base.json"),
        "revue": _ecrire_identite(racine, chemin=etat_perime["chemin"], octets=etat_perime["octets"],
                                  pull_request=PR_PERIMEE + 1, nom="mauvaise-revue.json"),
        "tete": _ecrire_identite(racine, chemin=etat_perime["chemin"], octets=etat_perime["octets"],
                                 tete="f" * 40, nom="mauvaise-tete.json"),
    }
    for nom, identite in cas.items():
        vue = _outil(racine, identite, ["preview"], env)
        assert vue.returncode == 1, (nom, vue.stdout)
        rendu = json.loads(vue.stdout[: vue.stdout.rindex("}") + 1])
        annule = _outil(racine, identite, ["cancel-stale-jobs", "--attestation-set-sha256",
                                           rendu["attestation_set_sha256"], "--job-set-sha256",
                                           rendu["job_set_sha256"] or "0" * 64], env)
        assert annule.returncode == 1, (nom, annule.stdout)
    assert "ragdb_profile_gate_v4" in _outil(racine, cas["base"], ["preview"], env).stdout
    assert _etat_du_controle(control) == avant
    # La base historique n'est jamais une cible, même si l'identité la nommait.
    revue = dh.charger_revue_perimee(etat_perime["identite"], racine=racine)
    historique = dh.RevuePerimee(**{**revue.__dict__, "legacy_database": "ragdb"})
    with psycopg.connect(app_dsn(control)) as conn:
        vue = dh.analyser(dh.prendre_instantane(conn, historique, avec_jobs=True), historique)
        conn.rollback()
    assert any("base historique" in ecart for ecart in vue.ecarts)


def _mutations() -> dict[str, Any]:
    """Même nombre de lignes, identité fausse : chaque cas DOIT être refusé."""

    def attestation(champ: str, valeur: Any) -> Any:
        def muter(inst: Any) -> None:
            inst.attestations[0][champ] = valeur
        return muter

    def job(champ: str, valeur: Any) -> Any:
        def muter(inst: Any) -> None:
            inst.jobs[0]["payload"] = {**inst.jobs[0]["payload"], champ: valeur}
        return muter

    def echanger_jobs(inst: Any) -> None:
        a, b = inst.jobs[0]["payload"], inst.jobs[1]["payload"]
        inst.jobs[0]["payload"] = {**a, "publication_attestation_id": b["publication_attestation_id"]}
        inst.jobs[1]["payload"] = {**b, "publication_attestation_id": a["publication_attestation_id"]}

    def job_etranger(inst: Any) -> None:
        inst.jobs[0]["job_type"] = "resource_pipeline"

    def ressource_etrangere(inst: Any) -> None:
        inst.ressources_release = set(list(inst.ressources_release)[1:]) | {str(uuid.uuid4())}

    def pin(inst: Any) -> None:
        inst.pins.append({"publication_attestation_id": inst.attestations[0]["attestation_id"],
                          "resource_id": inst.attestations[0]["resource_id"],
                          "publication_review_pull_request": PR_PERIMEE,
                          "publication_review_head_sha": TETE_PERIMEE})

    return {
        "manifeste de release": attestation("release_manifest_sha256", "0" * 64),
        "registre d'artefacts": attestation("artifacts_release_sha256", "1" * 64),
        "inventaire": attestation("candidate_inventory_sha256", "2" * 64),
        "manifeste de transfert": attestation("artifact_transfer_manifest_sha256", "3" * 64),
        "release de l'artefact": attestation("artifact_release_id", "production-profile-gate-2026-2027-v3"),
        "base de revue": attestation("human_review_base_sha", "8" * 40),
        "relecteur": attestation("human_review_reviewer", "quelqu-un-d-autre"),
        "identifiant de revue": attestation("review_id", "autre-revue"),
        "collection croisée": attestation("resource_collection", "rag_nexus_autre"),
        "autorisation étrangère": attestation("scope_authorization_id", "lot41a-staging-v4-autre-r4"),
        "contenu": attestation("artifact_sha256", "4" * 64),
        "ressource promue": attestation("resource_state", "REVIEWED"),
        "bail de ressource actif": attestation("resource_lease_active", True),
        "jobs échangés": echanger_jobs,
        "artefact du job": job("artifact_id", str(uuid.uuid4())),
        "version attendue": job("expected_state_version", 99),
        "clé de dédoublonnage": job("dedup_key", "publication:autre"),
        "job étranger": job_etranger,
        "ressource hors release": ressource_etrangere,
        "pin de commit": pin,
    }


@pytest.mark.parametrize("cas", sorted(_mutations()))
def test_memes_comptes_avec_mauvaises_identites_sont_refuses(etat_perime: dict[str, Any], cas: str) -> None:
    revue, instantane = _instantane(etat_perime)
    reference = dh.analyser(instantane, revue)
    assert reference.ecarts == []
    mute = copy.deepcopy(instantane)
    _mutations()[cas](mute)
    vue = dh.analyser(mute, revue)
    assert len(mute.attestations) == len(instantane.attestations) and len(mute.jobs) == len(instantane.jobs)
    assert vue.ecarts, f"{cas} : même compte, identité fausse, et pourtant accepté"


class _ConnexionInterrompue:
    """Délègue à une vraie connexion, et s'interrompt au N-ième UPDATE."""

    def __init__(self, conn: psycopg.Connection, apres: int) -> None:
        self._conn, self._reste = conn, apres

    def execute(self, requete: str, *args: Any) -> Any:
        if requete.lstrip().startswith("UPDATE"):
            if self._reste == 0:
                raise RuntimeError("interruption simulée au milieu de l'opération")
            self._reste -= 1
        return self._conn.execute(requete, *args)


def test_une_interruption_au_milieu_d_une_operation_ne_valide_rien(
    etat_perime: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    control = etat_perime["control"]
    revue, instantane = _instantane(etat_perime)
    vue = dh.analyser(instantane, revue)
    avant = _etat_du_controle(control)
    with psycopg.connect(app_dsn(control)) as conn:
        with pytest.raises(RuntimeError, match="interruption"):
            dh.annuler_jobs_perimes(_ConnexionInterrompue(conn, 2), revue,
                                    attestation_set=vue.attestation_set_sha256, job_set=vue.job_set_sha256)
        conn.rollback()
    with psycopg.connect(attestor_dsn(control)) as conn:
        with pytest.raises(RuntimeError, match="interruption"):
            dh.invalider_attestations_perimees(_ConnexionInterrompue(conn, 2), revue,
                                               attestation_set=vue.attestation_set_sha256,
                                               raison_live="pull_request_not_open")
        conn.rollback()
    assert _etat_du_controle(control) == avant
    # Une empreinte qui n'est pas celle de l'aperçu est un refus, avant toute écriture.
    with psycopg.connect(app_dsn(control)) as conn:
        with pytest.raises(dh.RecuperationRefusee, match="attestation_set_sha256"):
            dh.annuler_jobs_perimes(conn, revue, attestation_set="0" * 64, job_set=vue.job_set_sha256)
        conn.rollback()
    assert _etat_du_controle(control) == avant
